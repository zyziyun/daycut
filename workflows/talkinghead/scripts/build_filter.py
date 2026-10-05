#!/usr/bin/env python3
"""Build filter.txt + run.sh from config + assets.json.
Hook montage (sped, louder, muted-pad dissolves) -> body (sped) -> brightness grade ->
progress bar (always on) + active highlight + fill/playhead -> callouts/panels -> two-pass loudnorm.
The montage is vstudio.cut.xfade_assemble via montage.py: every dissolve runs over muted pads on BOTH
sides, so no hook loses its first or last syllable, and the body opens on a cloned first frame.
Usage: python3 build_filter.py work/config.py [--platform youtube] && bash work/run.sh
Platform (--platform, else config PLATFORM, else persona platforms.default, horizontal): bar / badge / callout /
panel positions from the profile safe box (layout.h_track_geo), loudness from the profile.
Superseded on the V track by scripts/vertical/compose.py (sid anchors, all styles)."""
import sys, pathlib; sys.path[:0] = [str(pathlib.Path(__file__).resolve().parents[3] / "lib"), str(pathlib.Path(__file__).resolve().parent),
                                     str(pathlib.Path(__file__).resolve().parent / "vertical")]
if len(sys.argv) > 1 and sys.argv[1] in ("-h", "--help"): print(__doc__); sys.exit(0)
import json, shlex, os, importlib.util
from vstudio import media
from vstudio.config import persona
from vstudio.draw import brand
from montage import Montage
from layout import resolve_profile, pop_platform_arg, h_track_geo
_PLAT, _ = pop_platform_arg(sys.argv)
_PS = persona(); _SP = _PS.get("speed") or {}
LIB = str(pathlib.Path(__file__).resolve().parents[3] / "lib")

cfg = sys.argv[1] if len(sys.argv) > 1 else "config.py"
spec = importlib.util.spec_from_file_location("config", cfg); C = importlib.util.module_from_spec(spec); spec.loader.exec_module(C)
WORK, SRC, OUT = C.WORK, C.SRC, C.OUT
PROF = resolve_profile(_PLAT or getattr(C, "PLATFORM", None), natural="horizontal"); GEO = h_track_geo(PROF)
LUFS, TP = PROF.loudness.get("lufs", (_PS.get("audio") or {}).get("loudness_lufs", -14)), PROF.loudness.get("tp", -1.5)
HS = getattr(C, "HOOK_SPEED", _SP.get("hook", 1.3)); BS = getattr(C, "BODY_SPEED", _SP.get("body", 1.1))
X = getattr(C, "XFADE", 0.8); VOL = getattr(C, "HOOK_VOL_DB", 4); MAIN_DUR = C.MAIN_DUR
BAR_X, BAR_W, BAR_Y = GEO["bar_x"], GEO["bar_w"], GEO["bar_y"]
M = Montage(SRC, C.HOOKS, (0.0, MAIN_DUR), HS, BS, X, hook_gain_db=VOL, size=f"{GEO['W']}:{GEO['H']}")
main_start = M.body_dst0                 # dissolve into the body starts (badge goes away)
body0 = M.body_start                     # body second 0 plays here (bar fill starts)
main_out = MAIN_DUR / BS
tmap = M.b2f

A = json.load(open(f"{WORK}/assets.json")); callouts, panels, active = A["callouts"], A["panels"], A["active"]
bar_idx, badge_idx = M.n_inputs, M.n_inputs + 1
active_base = M.n_inputs + 2
call_base = active_base + len(active)
panel_base = call_base + len(callouts)

ln = [M.graph]
# brightness grade only (footage usually too bright; blur was tried and dropped, see gotchas)
GRADE = getattr(C, "GRADE", "eq=brightness=-0.06:contrast=1.08:saturation=1.05:gamma=0.96")
ln.append(f"{M.vout}{GRADE}[bg]")
# progress bar always on (even during hooks); fill/playhead/active only in body
acc = "%02X%02X%02X" % brand()["accent"]
ln.append(f"[bg][{bar_idx}:v]overlay=x=0:y={BAR_Y}[v_bar]")
ln.append(f"[v_bar][{badge_idx}:v]overlay=x={GEO['badge'][0]}:y={GEO['badge'][1]}:enable='lt(t,{main_start:.3f})'[v_badge]")
# fill + playhead: drawbox evaluates its expressions once (and its `t` is the box THICKNESS), so the moving
# parts are colour sources overlaid with per-frame x expressions instead
P = f"min(1,max(0,(t-{body0:.3f})/{main_out:.3f}))"
ln.append(f"color=c=black@0:s={BAR_W}x5:r=30,format=rgba[fcv];color=c=0x{acc}:s={BAR_W}x5:r=30,format=rgba[fred];"
          f"[fcv][fred]overlay=x='-{BAR_W}+{P}*{BAR_W}':eof_action=pass[fill];color=c=white:s=12x15:r=30,format=rgba[head]")
ln.append(f"[v_badge][fill]overlay=x={BAR_X}:y={BAR_Y + 22}:shortest=1:enable='gte(t,{body0:.3f})'[v_fill]")
ln.append(f"[v_fill][head]overlay=x='{BAR_X}+{P}*{BAR_W}-6':y={BAR_Y + 17}:shortest=1:enable='gte(t,{body0:.3f})'[v_play]")
prev = "v_play"
for j, a in enumerate(active):
    idx = active_base + a["k"]
    ln.append(f"[{prev}][{idx}:v]overlay=x={a['x']}:y={a['y']}:enable='between(t,{tmap(a['s']):.3f},{tmap(a['e']):.3f})'[act{j}]"); prev = f"act{j}"
(CX, CY), SL, FD = GEO["callout"], 50, 0.25
for n, c in enumerate(callouts):
    idx = call_base + n; T0 = tmap(c["anchor"]); T1 = T0 + c["dur"]; cin = f"c{c['i']}"
    ln.append(f"[{idx}:v]format=yuva420p,setpts=PTS-STARTPTS+{T0:.3f}/TB,fade=t=in:st={T0:.3f}:d={FD}:alpha=1,fade=t=out:st={T1-FD:.3f}:d={FD}:alpha=1[{cin}]")
    ln.append(f"[{prev}][{cin}]overlay=x={CX}:y='{CY}+(1-min(1,(t-{T0:.3f})/{FD}))*{SL}':enable='between(t,{T0:.3f},{T1:.3f})'[o{c['i']}]"); prev = f"o{c['i']}"
(PX, PY), PSL, PFD = GEO["panel"], 40, 0.35
for n, p in enumerate(panels):
    idx = panel_base + n; T0 = tmap(p["anchor"]); T1 = T0 + p["dur"]; pin = f"p{p['p']}"
    ln.append(f"[{idx}:v]format=yuva420p,setpts=PTS-STARTPTS+{T0:.3f}/TB,fade=t=in:st={T0:.3f}:d={PFD}:alpha=1,fade=t=out:st={T1-PFD:.3f}:d={PFD}:alpha=1[{pin}]")
    ln.append(f"[{prev}][{pin}]overlay=x={PX}:y='{PY}+(1-min(1,(t-{T0:.3f})/{PFD}))*{PSL}':enable='between(t,{T0:.3f},{T1:.3f})'[po{p['p']}]"); prev = f"po{p['p']}"
ln.append(f"[{prev}]format=yuv420p[outv]")
graph = ";\n".join(ln) + "\n"
open(f"{WORK}/filter.txt", "w").write(graph)

pre = f"{WORK}/_premix.mov"              # picture final, audio PCM: loudness is set by the 2-pass step after
cmd = [media.ffmpeg_bin(), "-y", *M.input_args, "-i", f"{WORK}/bar_overlay.png", "-i", f"{WORK}/hook_badge.png"]
for a in active: cmd += ["-i", f"{WORK}/active_{a['k']}.png"]
for c in callouts: cmd += ["-loop", "1", "-t", f"{c['dur']}", "-i", f"{WORK}/callout_{c['i']}.png"]
for p in panels: cmd += ["-loop", "1", "-t", f"{p['dur']}", "-i", f"{WORK}/panel_{p['p']}.png"]
venc = [a for a in media.delivery_args(crf=20, audio=False, faststart=False) if a != "-an"]
cmd += ["-filter_complex", graph.replace("\n", ""), "-map", "[outv]", "-map", M.aout, *venc, "-c:a", "pcm_s16le",
        "-progress", "pipe:1", pre]
norm = (f"import sys; sys.path.insert(0, {LIB!r}); from vstudio import audio; "
        f"audio.loudnorm_2pass({pre!r}, {OUT!r}, lufs={LUFS}, tp={TP})")
open(f"{WORK}/run.sh", "w").write("#!/usr/bin/env bash\nset -e\n" + " ".join(shlex.quote(x) for x in cmd) + "\n"
                                   + "python3 -c " + shlex.quote(norm) + "\n" + f"rm -f {shlex.quote(pre)}\n")
os.chmod(f"{WORK}/run.sh", 0o755)
json.dump(dict(M.timeline(), PLATFORM=PROF.key, W=GEO["W"], H=GEO["H"]), open(f"{WORK}/timeline.json", "w"))
print(f"hooks {len(C.HOOKS)} | body starts {body0:.1f}s | total {M.total:.1f}s | {PROF.key}")
from vstudio import platform as _P
for _w in _P.check_length(PROF, M.total): print("WARN", _w)
print(f"wrote {WORK}/filter.txt + run.sh + timeline.json  (run: bash {WORK}/run.sh)")
