/*
 * Ben 10 Omniverse (BLUS31017) - macOS/arm64 boot host
 *
 * Derived from games/gow2/boot_macos.cpp with the GoW2-only pieces removed
 * (movie-player sampler, GoW2 overlay provider). Brings up guest memory, loads
 * the decrypted EBOOT, wires the HLE registries and enters the guest.
 *
 * Mirrors ps3recomp/runtime/ppu/tests/boot_main.cpp, the reference host, which
 * is the authority on the init contract. Diverging from it silently is how the
 * first version of this file ended up hanging on stubbed timer syscalls: it
 * skipped lv2_init_syscalls(), left ppu_vm_size at 0 (OOB guard off, so a
 * stray guest pointer took the process down instead of being logged), and
 * installed neither of the two hooks the runtime needs to re-enter guest code.
 *
 * Graphics backend is chosen with PS3_RSX_BACKEND (metal | sdl | vulkan).
 * Default is metal (M10). PS3_NO_RSX=1 skips the window for headless CPU/SPURS.
 *
 * Build: ./build_macos.sh
 */

#include <cstdio>
#include <cstdlib>
#include <cstring>
#include <cstdint>
#include <atomic>
#include <pthread.h>
#include <unistd.h>

#include "ppu_recomp.h"

extern "C" {

/*
 * Guest address space. ppu_loader.cpp declares this and expects the host to
 * own it; vm_init() in vm.h fills it in.
 *
 * Note for anyone porting further: the guest's window is mapped with
 * mmap(NULL, ...) and every guest address is an offset from vm_base, so macOS
 * reserving the low 4 GB as __PAGEZERO never comes into it. No -pagezero_size
 * link flag is needed.
 */
uint8_t* vm_base = nullptr;

/* g_trampoline_fn (the cross-fragment branch trampoline) is defined by
 * ppu_loader.cpp, which also drains it in its run loop. Do not define it here
 * as well -- the lifted chunks only declare it extern. */

/* Guest address-space size. Setting this arms the runtime's bounds check, so a
 * stray guest pointer is logged and reads back 0 rather than faulting the
 * host: a first boot then reveals the next wall instead of dying at the first
 * one. */
extern uint32_t ppu_vm_size;

uint32_t ppu_load_elf(const char* path);
void     ppu_recomp_register(void);
/* Lifted SPU job-chain binaries (tools/lift_spu_jobs.py, spu_jobs.toml). A weak
 * no-op DEFINITION, not a weak declaration: on Darwin a weak declaration with
 * no definition in a static link is "Undefined symbols" (see the LLE note
 * below; measured 2026-09-26 with a fingerprint-mismatch build, where step 3c
 * links no job object). The strong definition in the generated
 * spu_jobs_register.c wins when the jobs are linked; otherwise every job-chain
 * binary runs in the interpreter. */
extern "C" __attribute__((weak)) void ben10_register_spu_jobs(void) {}
int      ppu_run(uint32_t entry_opd, uint32_t stack_top);
int      ppu_opd_resolve(uint32_t opd, uint32_t* code, uint32_t* toc);
void     ps3_indirect_call(ppu_context* ctx);
uint32_t ppu_function_count(void);

/* HLE registries. These have to be populated before ppu_resolve_imports runs,
 * otherwise the guest's PRX import stubs have nothing to bind to and the first
 * indirect call through one jumps into whatever the slot happened to hold. */
void     ppu_hle_init(void);
void     ppu_sysprx_register(void);
void     ppu_fs_register(void);
void     lv2_init_syscalls(void);
uint32_t ppu_resolve_imports(void);

extern thread_local void (*g_trampoline_fn)(void*);
extern const char* ppu_vfs_root;

typedef void (*ps3_guest_caller_fn)(uint32_t opd, uint64_t, uint64_t, uint64_t, uint64_t);
extern ps3_guest_caller_fn g_ps3_guest_caller;

typedef void (*ppu_thread_entry_fn)(ppu_context*);
extern ppu_thread_entry_fn g_ppu_thread_entry_trampoline;

int  rsx_null_backend_init(uint32_t w, uint32_t h, const char* title);
void rsx_null_backend_shutdown(void);
int  rsx_null_backend_pump_messages(void);

int  rsx_metal_backend_init(uint32_t w, uint32_t h, const char* title);
void rsx_metal_backend_shutdown(void);
int  rsx_metal_backend_pump_messages(void);

int  rsx_vulkan_backend_init(uint32_t w, uint32_t h, const char* title);
void rsx_vulkan_backend_shutdown(void);
int  rsx_vulkan_backend_pump_messages(void);

/*
 * Mapa de commits do runtime (ppu_loader.cpp). O guard dos acessos vm_read e
 * vm_write nao consulta as tabelas de paginas do SO: consulta esta lista, que o host
 * tem de preencher, uma entrada por regiao que commita. Com a lista vazia o
 * guard fica intencionalmente ABERTO (tudo "commitado"), que era o estado
 * deste host -- ver commit_guest_regions().
 */
void ppu_register_committed_range(uint32_t lo, uint32_t hi);
int  ppu_guest_range_committed(uint32_t addr, uint32_t n);

} /* extern "C" */

#include "rsx_overlay.h"
#include "ppu_lle.h"

/* Lifted firmware modules (firmware/, gitignored; built only when present --
 * see build_macos.sh). A module that is absent stays HLE.
 *
 * PS3_LLE_HAVE_<M> comes from build_macos.sh step 3b (-D, one per module
 * actually present in this link). It has to gate the *declaration*, not just
 * the ppu_lle_add() call below: on Darwin a `__attribute__((weak))`
 * declaration with no definition ANYWHERE in a statically linked executable
 * is a hard "Undefined symbols" link error, not a null pointer at runtime --
 * that weak_import null-fallback is a dyld (dynamic library) feature and does
 * not apply here (same finding as the PGO writer's weak-declaration note in
 * ppu_loader.cpp). Measured 2026-09-24: the link failed exactly this way for
 * g_lle_avcdec/g_lle_apostsrc when their lift was still blocked by an upstream
 * ppu_lifter.py bug (fixed same day in ps3recomp 8699c475); both now lift and
 * link fine like every other module here (see notes/2026-09-24-survey.md). */
#ifdef PS3_LLE_HAVE_SAIL
extern "C++" const ppu_lle_module g_lle_sail;
#endif
#ifdef PS3_LLE_HAVE_PAMF
extern "C++" const ppu_lle_module g_lle_pamf;
#endif
#ifdef PS3_LLE_HAVE_DMUX
extern "C++" const ppu_lle_module g_lle_dmux;
#endif
#ifdef PS3_LLE_HAVE_DMUXPAMF
extern "C++" const ppu_lle_module g_lle_dmuxpamf;
#endif
#ifdef PS3_LLE_HAVE_ADEC
extern "C++" const ppu_lle_module g_lle_adec;
#endif
#ifdef PS3_LLE_HAVE_ATXDEC
extern "C++" const ppu_lle_module g_lle_atxdec;
#endif
#ifdef PS3_LLE_HAVE_VDEC
extern "C++" const ppu_lle_module g_lle_vdec;
#endif
#ifdef PS3_LLE_HAVE_AVCDEC
extern "C++" const ppu_lle_module g_lle_avcdec;
#endif
#ifdef PS3_LLE_HAVE_VPOST
extern "C++" const ppu_lle_module g_lle_vpost;
#endif
#ifdef PS3_LLE_HAVE_APOSTSRC
extern "C++" const ppu_lle_module g_lle_apostsrc;
#endif

#include "vm.h"

/*
 * Guest memory layout, matching the reference host.
 *
 * VM_SIZE has to cover every region the address map uses, including the PPU
 * thread-stack region at 0xD0000000 -- a smaller window leaves spawned thread
 * stacks outside the VM, where the OOB guard silently drops their writes and
 * the threads die.
 *
 * The main thread's stack goes in the free area below the image rather than in
 * the 0xD0000000 band, which is reserved for threads the guest spawns.
 */
#define GUEST_VM_SIZE   0xE0000000u
#define GUEST_LOW_MB    0x51000000u   /* image + heap + main stack + TLS + mmapper */
#define GUEST_STACK_TOP 0x0FF00000u
#define CB_STACK_TOP    0x0D000000u
#define RSX_LOCAL_BASE  0xC0000000u   /* memoria local do RSX (cellGcmGetConfiguration) */

#define GAME_TITLE "Ben 10 Omniverse"

namespace {

enum class Backend { None, Sdl, Metal, Vulkan };

Backend g_backend = Backend::None;
char    s_vfs_root[1024];

/*
 * Re-enter guest code from an HLE bridge (callbacks: cellSysutil, cellGcm
 * flip handlers, and so on). Each nested call gets its own stack slice so a
 * callback issued from inside a callback cannot land on its caller's frame.
 */
void boot_guest_caller(uint32_t opd_addr, uint64_t a0, uint64_t a1,
                       uint64_t a2, uint64_t a3)
{
    if (!opd_addr) {
        return;
    }
    uint32_t code = 0, toc = 0;
    ppu_opd_resolve(opd_addr, &code, &toc);
    if (!code) {
        return;
    }

    static uint32_t cb_depth = 0;
    ++cb_depth;

    ppu_context ctx;
    memset(&ctx, 0, sizeof(ctx));
    ctx.gpr[1] = CB_STACK_TOP - 0x10000u * cb_depth;
    ctx.gpr[2] = toc;
    ctx.gpr[3] = a0;
    ctx.gpr[4] = a1;
    ctx.gpr[5] = a2;
    ctx.gpr[6] = a3;
    ctx.ctr    = code;

    ps3_indirect_call(&ctx);
    while (g_trampoline_fn) { void (*tf)(void*) = g_trampoline_fn; g_trampoline_fn = 0; tf(&ctx); }

    --cb_depth;
}

/* Entry thunk for guest-spawned PPU threads: resolve the OPD the guest handed
 * sys_ppu_thread_create and run the lifted code behind it. */
void boot_thread_trampoline(ppu_context* ctx)
{
    uint32_t code = 0, toc = 0;
    if (ppu_opd_resolve((uint32_t)ctx->cia, &code, &toc) && code) {
        ctx->ctr = code;
        if (toc) {
            ctx->gpr[2] = toc;
        }
    } else {
        ctx->ctr = ctx->cia;   /* already a raw code address */
    }
    /* PS3_TRACE_THRSTACK: r2 (TOC) is the base for every TOC-relative global
     * access in lifted code; if it stays 0 the thread reads globals at small
     * negative addresses and the failure only surfaces later as [vm] OOB. */
    { static int ts = -1; if (ts < 0) ts = getenv("PS3_TRACE_THRSTACK") ? 1 : 0;
      if (ts) { fprintf(stderr, "[THRTOC] cia=0x%08X code=0x%08X toc=0x%08X -> r2=0x%08llX\n",
                        (unsigned)ctx->cia, code, toc,
                        (unsigned long long)ctx->gpr[2]); fflush(stderr); } }
    ps3_indirect_call(ctx);
    while (g_trampoline_fn) { void (*tf)(void*) = g_trampoline_fn; g_trampoline_fn = 0; tf(ctx); }
}

/* PS3 mount points resolve under this host directory. PS3_VFS_ROOT wins;
 * otherwise strip EBOOT.ELF / USRDIR / PS3_GAME off the ELF path. */
void derive_vfs_root(const char* eboot)
{
    const char* env = getenv("PS3_VFS_ROOT");
    if (env && *env) {
        ppu_vfs_root = env;
        return;
    }
    strncpy(s_vfs_root, eboot, sizeof s_vfs_root - 1);
    s_vfs_root[sizeof s_vfs_root - 1] = 0;
    for (int i = 0; i < 3; i++) {
        char* s = strrchr(s_vfs_root, '/');
        if (s) *s = 0;
    }
    if (!s_vfs_root[0]) {
        strcpy(s_vfs_root, ".");
    }
    ppu_vfs_root = s_vfs_root;
}

Backend pick_backend()
{
    if (getenv("PS3_NO_RSX")) {
        fprintf(stderr, "[boot] RSX backend=none (PS3_NO_RSX)\n");
        return Backend::None;
    }

    const char* want = getenv("PS3_RSX_BACKEND");
    if (!want || !*want) {
        /* M10: native Metal is the windowed default on macOS. */
        want = "metal";
    }
    Backend b = Backend::Sdl;
    if (strcmp(want, "metal")  == 0) b = Backend::Metal;
    else if (strcmp(want, "vulkan") == 0) b = Backend::Vulkan;
    else if (strcmp(want, "sdl")    == 0) b = Backend::Sdl;
    else {
        fprintf(stderr, "[boot] unknown PS3_RSX_BACKEND '%s', falling back to metal\n", want);
        b = Backend::Metal;
    }
    const char* name = "sdl";
    if (b == Backend::Metal)  name = "metal";
    if (b == Backend::Vulkan) name = "vulkan";
    /* cellGcmSys's rsx_bridge_mode reads PS3_RSX_BACKEND: without it (the default above,
     * or an unknown value) the GCM never presented to the backend picked here and every
     * frame stayed black. Publish the choice, as the Vulkan fallback below already does. */
    setenv("PS3_RSX_BACKEND", name, 1);
    fprintf(stderr, "[boot] RSX backend=%s\n", name);
    fflush(stderr);
    return b;
}

int backend_init(Backend b)
{
    switch (b) {
    case Backend::Sdl:    return rsx_null_backend_init(1280, 720, GAME_TITLE);
    case Backend::Metal:  return rsx_metal_backend_init(1280, 720, GAME_TITLE);
    case Backend::Vulkan: return rsx_vulkan_backend_init(1280, 720, GAME_TITLE);
    case Backend::None:   return 0;
    }
    return -1;
}

void backend_shutdown(Backend b)
{
    switch (b) {
    case Backend::Sdl:    rsx_null_backend_shutdown();   break;
    case Backend::Metal:  rsx_metal_backend_shutdown();  break;
    case Backend::Vulkan: rsx_vulkan_backend_shutdown(); break;
    case Backend::None:   break;
    }
}

/*
 * Back the regions the boot actually touches.
 *
 * vm_init only makes main memory and the stack band accessible, but the
 * reference host commits from guest address 0 upward -- which matters: the
 * GoW2 CRT (the title this layout was measured on) reads through a null
 * pointer during early init, and with the low page unbacked that read is a SIGBUS rather than the zero the reference host
 * returns. The gap between the low region and the thread-stack band stays
 * reserved, as on Windows.
 *
 * Cada vm_commit e' seguido de ppu_register_committed_range com o MESMO span.
 * Faltava: o boot_main.cpp do Windows regista as suas regioes e este host nao
 * registava nenhuma, portanto g_committed_count ficava 0 e o guard do runtime
 * ficava aberto -- todo o espaco de 3,5 GB contava como commitado. Consequencia
 * pratica: ppu_guest_range_committed() devolvia 1 para QUALQUER endereco, e
 * quem depende dele (o guard dos vm_read*, o DMA do SPU em spu_dma.h, e agora
 * o amostrador do movie player) nao tinha como distinguir memoria com paginas
 * por tras de espaco meramente reservado. As paginas fora destas regioes estao
 * PROT_NONE, logo o que o guard passava a deixar passar acabava em SIGBUS.
 *
 * Medido (boot headless de 25 s, 2026-07-20): o guest aloca no maximo ate
 * 0x4B100000 (sys_memory bump de 0x40000000 para cima) e a imagem TLS fica em
 * 0x10F00000 -- tudo dentro de 0..GUEST_LOW_MB. Nota para quem vier a seguir:
 * o sys_memory.c pode ir ate SYS_MEM_ALLOC_END (0x60000000) e faz vm_commit
 * SEM registar; se um boot mais longo passar de 0x51000000 aparecem linhas
 * "[vm] UNCOMMITTED" e o sitio certo de corrigir e' o registo na origem, em
 * sys_memory.c -- nao alargar estas regioes a espaco que nao esta commitado.
 */
int commit_guest_regions()
{
    if (vm_commit(0, GUEST_LOW_MB) != CELL_OK) {
        fprintf(stderr, "[boot] FATAL: could not commit guest low memory\n");
        return -1;
    }
    memset(vm_base, 0, GUEST_LOW_MB);
    ppu_register_committed_range(0, GUEST_LOW_MB);

    if (vm_commit(VM_STACK_BASE, VM_STACK_REGION) != CELL_OK) {
        fprintf(stderr, "[boot] FATAL: could not commit guest thread-stack band\n");
        return -1;
    }
    ppu_register_committed_range(VM_STACK_BASE, VM_STACK_BASE + VM_STACK_REGION);

    /* Memoria local do RSX (0xC0000000, o localAddress/localSize de 256 MB que o
     * cellGcmGetConfiguration anuncia). O alocador da GPU poe a sua arena aqui e
     * o caminho de render escreve framebuffers e labels dentro dela. Faltava: o
     * boot_main.cpp ja a commitava e este host nao, entao o titulo passava o
     * wall SPURS, entrava no cellGcmSys e morria com SIGBUS no primeiro
     * vm_write32 para 0xC0F40000 (guest), logo a seguir aos SetTile/
     * SetDisplayBuffer de 1280x720. Regulavel por PS3_VM_RSX_MB. */
    {
        const char* e = getenv("PS3_VM_RSX_MB");
        uint64_t rsx = e ? ((uint64_t)strtoul(e, nullptr, 10) << 20) : 0x10000000ull;
        if (rsx && vm_commit(RSX_LOCAL_BASE, (uint32_t)rsx) != CELL_OK) {
            fprintf(stderr, "[boot] FATAL: could not commit RSX local memory\n");
            return -1;
        }
        if (rsx) {
            ppu_register_committed_range(RSX_LOCAL_BASE, RSX_LOCAL_BASE + (uint32_t)rsx);
            fprintf(stderr, "[boot] committed RSX local 0x%X..0x%llX\n",
                    RSX_LOCAL_BASE, (unsigned long long)RSX_LOCAL_BASE + rsx);
        }
    }

    fprintf(stderr, "[boot] committed guest 0x0..0x%X and 0x%X..0x%X\n",
            GUEST_LOW_MB, VM_STACK_BASE, VM_STACK_BASE + VM_STACK_REGION);

    /*
     * PS3_TRACE_COMMITMAP: prova de que o registo acima chegou de facto ao
     * guard, e nao so ao log. Interroga o ppu_guest_range_committed com um
     * endereco DENTRO e outro FORA de cada regiao -- se a lista nao tivesse
     * sido preenchida, todas as respostas seriam "sim" (guard aberto), o que
     * torna o probe capaz de distinguir os dois estados. Off por default.
     */
    if (getenv("PS3_TRACE_COMMITMAP")) {
        static const struct { const char* name; uint32_t ea; int expect; } probes[] = {
            { "baixa (imagem/heap)",   0x00540054u, 1 },
            { "baixa (limite-1)",      GUEST_LOW_MB - 4u, 1 },
            { "buraco acima da baixa", GUEST_LOW_MB,      0 },
            { "buraco (0x80000000)",   0x80000000u,       0 },
            { "RSX local",             RSX_LOCAL_BASE,    1 },
            { "banda de stacks",       VM_STACK_BASE,     1 },
            { "acima da VM",           0xE0000000u,       0 },
        };
        int bad = 0;
        for (unsigned i = 0; i < sizeof probes / sizeof probes[0]; i++) {
            int got = ppu_guest_range_committed(probes[i].ea, 4) ? 1 : 0;
            if (got != probes[i].expect) bad++;
            fprintf(stderr, "[commitmap] 0x%08X %-24s commitado=%d esperado=%d%s\n",
                    probes[i].ea, probes[i].name, got, probes[i].expect,
                    got == probes[i].expect ? "" : "  <-- DIVERGE");
        }
        fprintf(stderr, "[commitmap] divergencias=%d\n", bad);
        fflush(stderr);
    }
    return 0;
}

} /* namespace */

/*
 * The guest's main thread blocks for long stretches: at the title screen Ben 10
 * sits in cellSpursEventFlagWait -> sys_event_queue_receive_host. On the process
 * main thread that stops AppKit's event loop (spinning cursor, no keyboard, no
 * START) because SDL events are only pumped by a flip on the main thread.
 * With Metal the guest runs on its own thread (same 32 MB stack the linker gives
 * the main thread) and the main thread only pumps the window, like the iOS host.
 * PS3_GUEST_ON_MAIN=1 restores the old layout.
 */
static std::atomic<int> g_guest_done{0};
static int g_guest_rc;

struct GuestArgs { uint32_t entry; };

static void* guest_thread_main(void* p)
{
    const GuestArgs* a = static_cast<const GuestArgs*>(p);
    pthread_setname_np("guest-main");
    g_guest_rc = ppu_run(a->entry, GUEST_STACK_TOP);
    g_guest_done.store(1);
    return nullptr;
}

static int run_guest(uint32_t entry)
{
    const char* on_main = getenv("PS3_GUEST_ON_MAIN");
    if (g_backend != Backend::Metal || (on_main && on_main[0] == '1'))
        return ppu_run(entry, GUEST_STACK_TOP);

    static GuestArgs args;
    args.entry = entry;
    pthread_attr_t attr;
    pthread_attr_init(&attr);
    pthread_attr_setstacksize(&attr, 0x2000000);   /* = -Wl,-stack_size in build_macos.sh */
    pthread_t th;
    if (pthread_create(&th, &attr, guest_thread_main, &args) != 0) {
        pthread_attr_destroy(&attr);
        fprintf(stderr, "[boot] guest thread create failed -> guest on the main thread\n");
        return ppu_run(entry, GUEST_STACK_TOP);
    }
    pthread_attr_destroy(&attr);
    fprintf(stderr, "[boot] guest on its own thread; main thread pumps the window\n");
    while (!g_guest_done.load()) {
        rsx_metal_backend_pump_messages();   /* quit paths leave via _exit inside */
        usleep(4000);
    }
    pthread_join(th, nullptr);
    return g_guest_rc;
}

int main(int argc, char** argv)
{
    const char* elf_path = (argc > 1) ? argv[1] : "EBOOT.ELF";

    /*
     * Line-buffer stdout.
     *
     * The runtime logs through both printf and fprintf(stderr): stderr is
     * unbuffered, stdout is block-buffered as soon as it is redirected to a
     * file. Every smoke and trace run here ends in kill, which discards
     * whatever is still sitting in the stdout buffer -- so a captured log
     * silently loses most of the boot and reads as if the guest stopped much
     * earlier than it did. That cost real debugging time: the guest was
     * reaching cellSpursInitializeWithAttribute while the log appeared to stop
     * at the printf-server thread.
     */
    setvbuf(stdout, nullptr, _IOLBF, 0);

    fprintf(stderr, "[boot] " GAME_TITLE " -- macOS/arm64 host\n");
    fprintf(stderr, "[boot] ELF: %s\n", elf_path);

    if (vm_init() != CELL_OK) {
        fprintf(stderr, "[boot] FATAL: vm_init failed\n");
        return 1;
    }
    fprintf(stderr, "[boot] guest memory mapped at host %p\n", (void*)vm_base);

    if (commit_guest_regions() != 0) {
        vm_shutdown();
        return 1;
    }
    ppu_vm_size = GUEST_VM_SIZE;

    uint32_t entry = ppu_load_elf(elf_path);
    if (!entry) {
        fprintf(stderr, "[boot] FATAL: could not load %s\n", elf_path);
        vm_shutdown();
        return 1;
    }
    fprintf(stderr, "[boot] entry OPD 0x%08X\n", entry);

    derive_vfs_root(elf_path);
    fprintf(stderr, "[boot] VFS root: %s\n", ppu_vfs_root);

    /* Without these two the runtime has no way back into guest code: HLE
     * callbacks become no-ops and every thread the guest spawns runs nothing. */
    g_ps3_guest_caller            = boot_guest_caller;
    g_ppu_thread_entry_trampoline = boot_thread_trampoline;

    /* Order matters, and matches the reference host. */
    ppu_recomp_register();   /* lifted function table -> address map          */
    ben10_register_spu_jobs();                                /* lifted SPU job-chain binaries (no-op if none) */
    ppu_hle_init();          /* firmware import NID -> HLE handlers           */
    ppu_sysprx_register();   /* boot-critical CRT (sys_initialize_tls, ...)   */
    ppu_fs_register();       /* cellFs VFS over the real game directory       */
    lv2_init_syscalls();     /* real lv2 table (timer/event/spu/mutex/fs/...) */
#ifdef PS3_LLE_HAVE_SAIL
    ppu_lle_add(&g_lle_sail);   /* libsail.sprx, LLE */
#endif
#ifdef PS3_LLE_HAVE_PAMF
    ppu_lle_add(&g_lle_pamf);   /* libpamf.sprx (libsail's dependency) */
#endif
#ifdef PS3_LLE_HAVE_DMUX
    ppu_lle_add(&g_lle_dmux);   /* libdmux.sprx (demuxer core) */
#endif
#ifdef PS3_LLE_HAVE_DMUXPAMF
    ppu_lle_add(&g_lle_dmuxpamf);   /* libdmuxpamf.sprx (PAMF demux plugin) */
#endif
#ifdef PS3_LLE_HAVE_ADEC
    ppu_lle_add(&g_lle_adec);   /* libadec.sprx (audio decoder core) */
#endif
#ifdef PS3_LLE_HAVE_ATXDEC
    ppu_lle_add(&g_lle_atxdec);   /* libatxdec.sprx (ATRAC3plus decoder plugin) */
#endif
#ifdef PS3_LLE_HAVE_VDEC
    ppu_lle_add(&g_lle_vdec);   /* libvdec.sprx (video decoder core) */
#endif
#ifdef PS3_LLE_HAVE_AVCDEC
    ppu_lle_add(&g_lle_avcdec);   /* libavcdec.sprx (AVC decoder plugin) */
#endif
#ifdef PS3_LLE_HAVE_VPOST
    ppu_lle_add(&g_lle_vpost);   /* libvpost.sprx (post-processing) */
#endif
#ifdef PS3_LLE_HAVE_APOSTSRC
    ppu_lle_add(&g_lle_apostsrc);   /* libapostsrc_mini.sprx (audio post source) */
#endif
    ppu_resolve_imports();   /* patch .lib.stub slots -> HLE / LLE modules    */
    fprintf(stderr, "[boot] %u lifted functions registered, HLE wired\n",
            ppu_function_count());

    g_backend = pick_backend();
    /* Runtime overlay: settings (window size, fullscreen, VSync, pad mapping)
     * load BEFORE the backend reads them. The launcher hands its path over in
     * PS3_OVERLAY_SETTINGS; started without the launcher, the per-user default
     * path is used. The overlay stays closed until F1/Start.
     * Only the Metal backend draws it: with sdl/vulkan/none it stays
     * uninitialized, so Start and the pad reach the game exactly as before
     * instead of toggling a menu nobody can see. */
    auto overlay_init_for_metal = []() {
        if (g_backend != Backend::Metal) return;
        if (!rsx_overlay_init(rsx_overlay_settings_path_from_env()))
            fprintf(stderr, "[boot] runtime overlay unavailable\n");
        rsx_overlay_set_title(GAME_TITLE);
    };
    overlay_init_for_metal();
    int brc = backend_init(g_backend);
    if (brc != 0 && g_backend == Backend::Vulkan) {
        /* Spec (ps3recomp docs/superpowers/specs/2026-09-23-vulkan-backend-a-design.md §5):
         * Vulkan unavailable -> platform default with one log line, never abort. The env is
         * updated so cellGcmSys's rsx_bridge_mode keeps the Metal backend registered here.
         * The overlay was skipped for Vulkan; it comes up now, before the Metal backend. */
        fprintf(stderr, "[boot] vulkan init failed -> metal (platform default)\n");
        setenv("PS3_RSX_BACKEND", "metal", 1);
        g_backend = Backend::Metal;
        overlay_init_for_metal();
        brc = backend_init(g_backend);
    }
    if (brc != 0) {
        fprintf(stderr, "[boot] FATAL: RSX backend failed to initialise\n");
        vm_shutdown();
        return 1;
    }

    fprintf(stderr, "[boot] entering guest (stack top 0x%08X)\n", GUEST_STACK_TOP);
    fflush(stderr);

    int rc = run_guest(entry);

    fprintf(stderr, "[boot] guest returned rc=%d\n", rc);

    /* Orderly exit only: the overlay saves pending settings and frees its core
     * before the backend (its only renderer) tears down. A no-op when it was
     * never initialized (non-Metal backends). The window-close / Cmd+Q /
     * shell "Sair" paths leave through metal_quit_now's _exit by design and
     * never get here (see rsx_metal_backend.m). */
    rsx_overlay_shutdown();
    backend_shutdown(g_backend);
    vm_shutdown();
    return rc == 0 ? 0 : 1;
}
