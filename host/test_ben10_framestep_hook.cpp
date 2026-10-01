/*
 * Test of host/ben10_framestep_hook.cpp (plan 2026-09-30-ben10-60fps.md, Task 3): what the mid-asm
 * hooks do to the guest context. Each policy runs in its own child process (the hook state is a
 * process-wide magic static read from PS3_BEN10_FPS at the first call).
 *   clang++ -std=c++20 -Wall -Wextra -I host -I ../ps3recomp/include -I ../ps3recomp/runtime/ppu \
 *       -I ../ps3recomp/runtime/syscalls -I ../ps3recomp/runtime/memory \
 *       host/test_ben10_framestep_hook.cpp host/ben10_framestep_hook.cpp host/ben10_framestep.c \
 *       -o /tmp/t_fs_hook && /tmp/t_fs_hook
 * (host/ben10_framestep.c is C: compile it with clang -c first if the C++ driver rejects it.)
 */
#include "ppu_context.h"
#include "ppu_memory.h"

#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/wait.h>
#include <unistd.h>

/* runtime symbols the guest-memory accessors reference; a tiny fake guest memory instead */
extern "C" {
uint8_t *vm_base = nullptr;
int ppu_guest_range_committed(uint32_t, uint32_t) { return 1; }
void gow2_midasm_Ben10ModeR3(ppu_context *);
void gow2_midasm_Ben10ModeR0(ppu_context *);
void gow2_midasm_Ben10LimiterEnter(ppu_context *);
void gow2_midasm_Ben10FrameStep(ppu_context *);
}

static int g_fail, g_checks;
#define CHECK(c) do { g_checks++; if (!(c)) { g_fail++; \
    fprintf(stdout, "FAIL %s:%d: %s\n", __FILE__, __LINE__, #c); } } while (0)

static ppu_context *fresh(void)
{
    ppu_context *c = (ppu_context *)aligned_alloc(64, (sizeof(ppu_context) + 63) & ~(size_t)63);
    memset(c, 0, sizeof *c);
    for (int i = 0; i < 32; i++) {
        c->gpr[i] = 0x1111111111111111ull * (uint64_t)(i + 1) ^ 0xDEADBEEF00ull;
        c->fpr[i] = 1.5 + i;
    }
    c->cr = 0x12345678; c->lr = 0x3DC09C; c->ctr = 0xCAFE; c->xer = 0xBEEF;
    c->gpr[2] = 0x20000;                       /* TOC inside the fake guest memory */
    return c;
}

/* every register of `a` equals `b`'s except GPR `except` (-1 = none) */
static bool same_but(const ppu_context *a, const ppu_context *b, int except)
{
    ppu_context x = *a, y = *b;
    if (except >= 0) { x.gpr[except] = 0; y.gpr[except] = 0; }
    return memcmp(&x, &y, sizeof x) == 0;
}

static int child(const char *mode)
{
    static uint8_t mem[0x40000];
    vm_base = mem;
    ppu_context *c = fresh(), *ref = fresh();

    if (!strcmp(mode, "unset")) {
        /* long enough (1.3 s) for an active hook to close its one-second [FRAMESTEP] window */
        for (int i = 0; i < 650; i++) {
            gow2_midasm_Ben10ModeR3(c); gow2_midasm_Ben10ModeR0(c);
            gow2_midasm_Ben10LimiterEnter(c); gow2_midasm_Ben10FrameStep(c);
            usleep(2000);
        }
        CHECK(memcmp(c, ref, sizeof *c) == 0);           /* OFF: no register of the guest touched */
        return g_fail ? 1 : 0;
    }
    int want = !strcmp(mode, "30") ? 0 : 1;              /* 60 -> 1, auto starts safe at 0 */
    if (!strcmp(mode, "auto")) want = 0;

    c->gpr[3] = 0; ref->gpr[3] = (uint64_t)(int64_t)want;
    gow2_midasm_Ben10ModeR3(c);                          /* the game's loaded word was 0 */
    CHECK(c->gpr[3] == ref->gpr[3]);
    CHECK(same_but(c, ref, 3));                          /* only r3 changes */
    c->gpr[0] = 0; ref->gpr[0] = (uint64_t)(int64_t)want;
    gow2_midasm_Ben10ModeR0(c);
    CHECK(c->gpr[0] == ref->gpr[0]);
    CHECK(same_but(c, ref, 3));                          /* only r0 (and the r3 set before) */
    c->gpr[0] = 7; ref->gpr[0] = 7;                      /* a sign-extension case: forced from -1 */
    c->gpr[3] = 0xFFFFFFFFFFFFFFFFull;
    gow2_midasm_Ben10ModeR3(c);
    CHECK(c->gpr[3] == (uint64_t)(int64_t)want);

    /* observing hooks never write the guest registers (r3 = the game's own ticks included) */
    *ref = *c;
    for (int i = 0; i < 650; i++) {
        usleep(2000);
        gow2_midasm_Ben10LimiterEnter(c);
        /* vary the game's ticks (10/20/30/odd): a hook that wrote any constant, 10 included, is caught */
        uint64_t gt = (i % 4 == 3) ? 17u : 10u * (uint64_t)(1 + i % 3);
        c->gpr[3] = gt; ref->gpr[3] = gt;
        gow2_midasm_Ben10FrameStep(c);
        CHECK(memcmp(c, ref, sizeof *c) == 0);
    }
    return g_fail ? 1 : 0;
}

int main(int argc, char **argv)
{
    if (argc == 3 && !strcmp(argv[1], "--child")) return child(argv[2]);
    const char *modes[] = {"unset", "30", "60", "auto"};
    int bad = 0;
    for (const char *m : modes) {
        int errp[2];
        if (pipe(errp) != 0) return 2;
        pid_t p = fork();
        if (p == 0) {
            dup2(errp[1], 2); close(errp[0]); close(errp[1]);
            if (!strcmp(m, "unset")) unsetenv("PS3_BEN10_FPS"); else setenv("PS3_BEN10_FPS", m, 1);
            execl(argv[0], argv[0], "--child", m, (char *)nullptr);
            _exit(127);
        }
        close(errp[1]);
        char eb[4096]; size_t en = 0; ssize_t r;
        while ((r = read(errp[0], eb + en, sizeof eb - en)) > 0 && en < sizeof eb) en += (size_t)r;
        close(errp[0]);
        int st = 0; waitpid(p, &st, 0);
        int rc = WIFEXITED(st) ? WEXITSTATUS(st) : 255;
        if (!strcmp(m, "unset") && en != 0) { rc = 1; printf("  OFF printed %zu bytes on stderr\n", en); }
        if (strcmp(m, "unset") != 0 && en == 0) { rc = 1; printf("  policy %s printed nothing\n", m); }
        printf("  hook policy %-5s: %s\n", m, rc == 0 ? "ok" : "FAIL");
        bad |= rc;
    }
    printf("%s\n", bad ? "FAIL" : "PASS");
    return bad;
}
