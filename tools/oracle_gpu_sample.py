#!/usr/bin/env python3
"""oracle_gpu_sample.py -- sample Ben 10 Omniverse's GPU/job-chain state under RPCS3.

Uses the ps3recomp RPCS3 oracle tooling (tools/rpcs3_probe: RSP client + launcher).
RPCS3 must have `GDB Server: 127.0.0.1:2345` in config.yml; the title waits for the
debugger, this script resumes it (vCont;c), and every `--interval` seconds interrupts
it (0x03), reads guest memory and resumes. Works with the LLVM PPU decoder (no
breakpoints needed).

Reads, per sample: the stopped PPU thread's pc/lr, the default GCM context
(*0x00AB9238 -> begin/end/current/callback), the ring-offset globals at 0x009F8760,
and the job parameter/guard block at 0x00A96780..0x00A96880.

    python3 tools/oracle_gpu_sample.py --title <path>/PS3_GAME/USRDIR/EBOOT.BIN \
        [--interval 5] [--samples 6]
"""
import argparse
import os
import sys
import time

PROBE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", "ps3recomp",
                     "tools", "rpcs3_probe")
sys.path.insert(0, os.path.abspath(PROBE))
from rsp import RSPClient  # noqa: E402
import probe  # noqa: E402
import rpcs3_host  # noqa: E402


def words(b):
    return " ".join(b[i:i + 4].hex() for i in range(0, len(b), 4))


DUMPS = []


def sample(rsp, t):
    print(f"=== t={t:.1f}s", flush=True)
    try:
        regs = rsp.read_registers()
        pc = probe._pc(regs)
        print(f"  stopped thread: pc={hex(pc) if pc is not None else None}"
              f" lr=0x{regs.get('lr', 0) & 0xFFFFFFFF:08X}", flush=True)
    except Exception as e:  # noqa: BLE001 -- memory reads still work
        print(f"  stopped thread: <{e}>", flush=True)
    ctx = rsp.read_u32(0x00AB9238)
    print(f"  gcm ctx ptr=0x{ctx:08X}", flush=True)
    if 0x10000 <= ctx < 0xF0000000:
        c = rsp.read_mem(ctx, 0x18)
        print(f"  gcm ctx: {words(c)}", flush=True)
        begin, cur = int.from_bytes(c[0:4], "big"), int.from_bytes(c[8:12], "big")
        ctrl, io = int.from_bytes(c[16:20], "big"), int.from_bytes(c[20:24], "big")
        if 0x10000 <= ctrl < 0xF0000000:
            print(f"  ctrl @0x{ctrl:08X} put/get/ref: {words(rsp.read_mem(ctrl, 12))}", flush=True)
        if 0x10000 <= io < 0xF0000000:
            print(f"  io+0      : {words(rsp.read_mem(io, 0x20))}", flush=True)
            print(f"  io+0x10000: {words(rsp.read_mem(io + 0x10000, 0x40))}", flush=True)
        if 0x10000 <= begin < cur < begin + 0x10000:
            print(f"  ctx cmds [0x{begin:08X}..0x{cur:08X}): {words(rsp.read_mem(begin, min(cur - begin, 0x400)))}",
                  flush=True)
    print(f"  ring globals @0x009F8740: {words(rsp.read_mem(0x009F8740, 0x40))}", flush=True)
    for base in (0x00A96780, 0x00A96800):
        print(f"  @0x{base:08X}: {words(rsp.read_mem(base, 0x80))}", flush=True)
    for ea, n in DUMPS:
        print(f"  dump @0x{ea:08X}: {words(rsp.read_mem(ea, n))}", flush=True)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--title", required=True)
    ap.add_argument("--interval", type=float, default=5.0)
    ap.add_argument("--samples", type=int, default=6)
    ap.add_argument("--dump", action="append", default=[], metavar="EA:LEN",
                    help="extra guest range to dump each sample (hex EA, hex/dec length)")
    ap.add_argument("--rpcs3-config", help="config.yml override (e.g. interpreters + GDB stub)")
    a = ap.parse_args()
    for d in a.dump:
        ea, n = d.split(":")
        DUMPS.append((int(ea, 16), int(n, 0)))
    extra = ["--config", a.rpcs3_config] if a.rpcs3_config else None
    proc = probe.launch_rpcs3(None, a.title, headless=True, extra=extra)
    rsp = RSPClient(port=rpcs3_host.stub_port(), timeout=60.0)
    t0 = time.time()
    try:
        time.sleep(3)
        rsp.connect(retries=120, delay=0.5)
        rsp.handshake()
        for _ in range(a.samples):
            rsp.cont()
            time.sleep(a.interval)
            rsp.interrupt()
            rsp.wait_stop(deadline=time.time() + 20)
            sample(rsp, time.time() - t0)
    finally:
        try:
            rsp.close()
        except Exception:  # noqa: BLE001
            pass
        proc.kill()


if __name__ == "__main__":
    main()
