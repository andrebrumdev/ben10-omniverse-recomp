#!/usr/bin/env python3
"""Speed + landmark check of the frame-step A/B (60 fps plan, Task 4), windows by EVENT.

usage: fs_an.py <dir> <tag>... [--control tagA,tagB]     reads <dir>/lp_<tag>.log/.meta (run_lp.sh output)

Landmark       = first level '.ls' open (first LoadingScreens/*.ls open at t>55 s of the log), seconds on the log clock.
Gameplay window= level .ls + 20 s -> last [FPS] line; cut in full 30 s sub-windows.
Speed          = game seconds per wall second, per 30 s sub-window.
                 hook arms (PS3_BEN10_FPS set): mean of '[FRAMESTEP] win_speed' (the game's own ticks, measured);
                 OFF arm (no [FRAMESTEP] line): INFERRED = fps * 20 / 600 from '[FPS]' (20 ticks per frame at
                 mode 0, verified in every frame of every run by the T1 tick log) -- labelled speed_src=inferred20.
Pass (plan Task 4): speed 1.00 +- 0.02 in EVERY 30 s window; landmark within 1 s of the OFF control;
                 fps avg >= the OFF control's; no crash / hang / early exit.
Regime: fps and speed numbers depend on the machine; the .meta of each run records loadavg and the top non-game processes.
Speed 1.00 needs the machine to hold the limiter period (29.97 fps at mode 0, 59.94 at mode 1): below that the game runs
in slow motion in BOTH arms, so the control's own speed is the reference for what the machine allows.
"""
import re, sys, os, statistics as st

WIN_S = 30.0
SPEED_TOL = 0.02
LANDMARK_TOL_S = 1.0
GAME_START_S = 20.0


def _mean(xs):
    xs = list(xs)
    return sum(xs) / len(xs) if xs else None


def an(P, tag):
    fps = []        # (t, fps, draws)
    fsl = []        # (t, mode_word or None, win_speed)
    ls = []
    crash = 0
    with open(os.path.join(P, "lp_%s.log" % tag), errors="replace") as fh:
        lines = fh.readlines()
    for l in lines:
        m = re.match(r"\s*([\d.]+) (.*)", l)
        if not m or l.startswith("T0 "):
            continue
        t = float(m.group(1)); r = m.group(2)
        if r.startswith("[FPS]"):
            f = re.search(r"fps=(\d+) draws=(\d+)", r)
            if f:
                fps.append((t, int(f.group(1)), int(f.group(2))))
        elif r.startswith("[FRAMESTEP] policy"):
            s = re.search(r"win_speed=([\d.]+)", r)
            mw = re.search(r"mode_word=(-?\d+|\?)", r)
            if s:
                fsl.append((t, int(mw.group(1)) if mw and mw.group(1) not in ("?",) else None, float(s.group(1))))
        elif "[CRASH]" in r:
            crash += 1
        elif "LoadingScreens/" in r and ".ls'" in r and "open" in r:
            ls.append(t)
    res = {"tag": tag, "crash": crash, "valid": False, "windows": []}
    meta = os.path.join(P, "lp_%s.meta" % tag)
    res["alive_at_stop"] = None
    if os.path.exists(meta):
        with open(meta, errors="replace") as fh:
            mt = fh.read()
        res["alive_at_stop"] = "alive_at_stop=1" in mt
        mm = re.search(r"level_ls_seen_at_harness_s=\d+ load=(\{[^}]*\}) top: (.*)", mt)
        if mm:
            res["regime"] = "load=%s top: %s" % (mm.group(1), mm.group(2).strip())
    lv = [x for x in ls if x > 55]
    res["speed_src"] = "framestep" if fsl else "inferred20"
    if not lv or not fps:
        return res
    L = lv[0]
    G = L + GAME_START_S
    end = max(t for t, _, _ in fps)
    res["level_ls"] = L
    res["last_t"] = end
    gp = [(t, f) for t, f, _ in fps if t >= G]
    res["fps_avg"] = _mean(f for _, f in gp)
    k = 0
    while G + WIN_S * (k + 1) <= end + 1.0:
        a, b = G + WIN_S * k, G + WIN_S * (k + 1)
        wf = [f for t, f, _ in fps if a <= t < b]
        if fsl:
            ws = [s for t, _, s in fsl if a <= t < b]
        else:
            ws = [f * 20.0 / 600.0 for f in wf]
        if wf and ws:
            res["windows"].append({"t0": a, "fps": _mean(wf), "speed": _mean(ws)})
        k += 1
    res["valid"] = bool(res["windows"])
    sp = [w["speed"] for w in res["windows"]]
    res["speed_min"] = min(sp) if sp else None
    res["speed_max"] = max(sp) if sp else None
    res["speed_avg"] = _mean(sp)
    res["all_speed_ok"] = bool(sp) and all(abs(s - 1.0) <= SPEED_TOL + 1e-9 for s in sp)
    res["mode_words"] = sorted({m for t, m, _ in fsl if t >= G and m is not None})
    return res


def compare(P, tags, ctrls):
    """Each tag against the mean of the control runs (same pad, OFF)."""
    cr = [an(P, c) for c in ctrls]
    cr = [c for c in cr if c["valid"]]
    out = {}
    if not cr:
        return out
    c_ls = [c["level_ls"] for c in cr]
    c_fps = _mean(c["fps_avg"] for c in cr)
    c_sp = _mean(c["speed_avg"] for c in cr)
    out["control_level_ls"] = _mean(c_ls)
    out["control_fps_avg"] = c_fps
    out["control_speed_avg"] = c_sp
    out["noise_floor_s"] = (max(c_ls) - min(c_ls)) if len(c_ls) > 1 else None
    for t in tags:
        r = an(P, t)
        if not r["valid"]:
            out[t] = {"valid": False}
            continue
        d = r["level_ls"] - out["control_level_ls"]
        out[t] = {"valid": True, "landmark_delta_s": d, "landmark_ok": abs(d) <= LANDMARK_TOL_S,
                  "fps_vs_control": r["fps_avg"] - c_fps, "fps_ok": r["fps_avg"] - c_fps >= 0.0,
                  "speed_ratio": (r["speed_avg"] / c_sp) if c_sp else None}
    return out


def fmt(r):
    if not r.get("valid"):
        return "%s INVALID (no level .ls or no full 30 s window) crash=%d alive_at_stop=%s" % (r["tag"], r["crash"], r["alive_at_stop"])
    ws = " ".join("%.2f" % w["speed"] for w in r["windows"])
    wf = " ".join("%.0f" % w["fps"] for w in r["windows"])
    return ("%s level_ls=%.1f gp_fps_avg=%.1f speed[%s]=%s fps/30s=%s speed_min=%.3f speed_max=%.3f all_speed_ok=%s "
            "mode_words=%s crash=%d alive_at_stop=%s last_t=%.0f\n    %s" %
            (r["tag"], r["level_ls"], r["fps_avg"], r["speed_src"], ws, wf, r["speed_min"], r["speed_max"],
             r["all_speed_ok"], r.get("mode_words"), r["crash"], r["alive_at_stop"], r["last_t"], r.get("regime", "")))


if __name__ == "__main__":
    args = sys.argv[1:]
    ctrl = []
    if "--control" in args:
        i = args.index("--control"); ctrl = args[i + 1].split(","); del args[i:i + 2]
    P, tags = args[0], args[1:]
    for t in tags + [c for c in ctrl if c not in tags]:
        print(fmt(an(P, t)))
    if ctrl:
        c = compare(P, [t for t in tags if t not in ctrl], ctrl)
        print("control: level_ls=%.1f fps_avg=%.1f speed_avg=%.3f noise_floor_s=%s" %
              (c["control_level_ls"], c["control_fps_avg"], c["control_speed_avg"], c["noise_floor_s"]))
        for t in tags:
            if t in c:
                print("  %s %s" % (t, c[t]))
