#!/usr/bin/env python3
"""survey_imports.py -- list a decrypted PS3 EBOOT's PRX imports and embedded SPU ELFs.

Usage: python3 tools/survey_imports.py EBOOT.ELF out_imports.json

Imports are read from the .lib.stub table that sys_process_prx_info (the
PT 0x60000002 segment) points at, so it works on ELFs whose section headers
are stripped. Each stub entry is 0x2C bytes: counts at +6/+8, then name,
fnid, fstub, vnid and vstub pointers from +0x10.
"""
import json
import re
import struct
import sys

PT_LOAD, PT_PRX_PARAM = 1, 0x60000002


def main():
    path, out_path = sys.argv[1], sys.argv[2]
    d = open(path, 'rb').read()
    phoff, = struct.unpack('>Q', d[0x20:0x28])
    phnum, = struct.unpack('>H', d[0x38:0x3A])
    segs = []
    for i in range(phnum):
        t, _, off, va, _, fs, _, _ = struct.unpack('>IIQQQQQQ', d[phoff + i * 56:phoff + i * 56 + 56])
        segs.append((t, off, va, fs))

    def rd(va, n):
        for t, off, sva, fs in segs:
            if t == PT_LOAD and sva <= va < sva + fs:
                o = off + va - sva
                return d[o:o + n]
        return None

    def cstr(va):
        b = rd(va, 256)
        return b[:b.index(b'\0')].decode() if b else '?'

    prx = next(s for s in segs if s[0] == PT_PRX_PARAM)
    stub_start, stub_end = struct.unpack('>II', d[prx[1] + 0x18:prx[1] + 0x20])

    mods = {}
    for va in range(stub_start, stub_end, 0x2C):
        ent = rd(va, 0x2C)
        nfunc, nvar = struct.unpack('>HH', ent[6:10])
        name_p, fnid_p, _, vnid_p, _ = struct.unpack('>5I', ent[16:36])
        funcs = [struct.unpack('>I', rd(fnid_p + 4 * k, 4))[0] for k in range(nfunc)]
        vars_ = [struct.unpack('>I', rd(vnid_p + 4 * k, 4))[0] for k in range(nvar)]
        mods[cstr(name_p)] = {'funcs': [hex(x) for x in funcs], 'vars': [hex(x) for x in vars_]}

    with open(out_path, 'w') as f:
        json.dump(mods, f, indent=1)
    print('modules', len(mods), 'funcs', sum(len(v['funcs']) for v in mods.values()))
    for m, v in sorted(mods.items()):
        print(f"  {m:28s} {len(v['funcs'])}")

    elfs = [m.start() for m in re.finditer(rb'\x7fELF\x01\x02\x01', d)]
    spu = [o for o in elfs if struct.unpack('>H', d[o + 18:o + 20])[0] == 0x17]
    print('embedded SPU ELFs:', len(spu))


if __name__ == '__main__':
    main()
