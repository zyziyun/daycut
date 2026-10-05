#!/usr/bin/env python3
"""Build filter.txt + run.sh from config + assets.json.
Hook xfade montage (sped, louder, audio crossfade) -> body (sped) -> brightness grade ->
progress bar (always on) + active highlight + fill/playhead -> callouts/panels -> loudnorm.
Usage: python3 build_filter.py work/config.py && bash work/run.sh
Superseded on the V track by scripts/vertical/compose.py (muted hook pads, sid anchors, all styles)."""
import sys, pathlib; sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[3] / "lib"))
if len(sys.argv) > 1 and sys.argv[1] in ("-h", "--help"): print(__doc__); sys.exit(0)
import json, shlex, os, importlib.util
from vstudio.config import font, persona
_PS = persona(); _BR = _PS.get("brand") or {}; _SP = _PS.get("speed") or {}
def _rgb(h, d): h = (h or d).lstrip("#"); return tuple(int(h[i:i + 2], 16) for i in (0, 2, 4))
LUFS = (_PS.get("audio") or {}).get("loudness_lufs", -14)

cfg = sys.argv[1] if len(sys.argv) > 1 else "config.py"
spec = importlib.util.spec_from_file_location("config", cfg); C = importlib.util.module_from_spec(spec); spec.loader.exec_module(C)
WORK, SRC, OUT = C.WORK, C.SRC, C.OUT
HS = getattr(C, "HOOK_SPEED", _SP.get("hook", 1.3)); BS = getattr(C, "BODY_SPEED", _SP.get("body", 1.1))
X = getattr(C, "XFADE", 0.8); VOL = getattr(C, "HOOK_VOL_DB", 4); MAIN_DUR = C.MAIN_DUR
BAR_X, BAR_W = 80, 1760
HOOKS = C.HOOKS; nH = len(HOOKS)

d = [(e-s)/HS for s, e in HOOKS]
L = [d[0]]
for i in range(1, nH): L.append(L[-1] + d[i] - X)
hook_dur = L[-1]
main_start = hook_dur - X
main_out = MAIN_DUR / BS
def tmap(o): return main_start + o / BS

A = json.load(open(f"{WORK}/assets.json")); callouts, panels, active = A["callouts"], A["panels"], A["active"]
ln = []
for i in range(nH):
    ln.append(f"[{i}:v]setpts=PTS-STARTPTS,fps=30,scale=1920:1080,setsar=1,setpts=PTS/{HS},format=yuv420p[hv{i}]")
    ln.append(f"[{i}:a]asetpts=PTS-STARTPTS,atempo={HS},volume={VOL}dB[ha{i}]")
mi = nH
ln.append(f"[{mi}:v]setpts=PTS-STARTPTS,fps=30,scale=1920:1080,setsar=1,setpts=PTS/{BS},format=yuv420p[mv]")
ln.append(f"[{mi}:a]asetpts=PTS-STARTPTS,atempo={BS}[ma]")
# video xfade chain
prev = "hv0"
for i in range(1, nH):
    ln.append(f"[{prev}][hv{i}]xfade=transition=fade:duration={X}:offset={L[i-1]-X:.3f}[xv{i}]"); prev = f"xv{i}"
ln.append(f"[{prev}][mv]xfade=transition=fade:duration={X}:offset={hook_dur-X:.3f}[cv]")
# audio crossfade chain
prevA = "ha0"
for i in range(1, nH):
    ln.append(f"[{prevA}][ha{i}]acrossfade=d={X}[xa{i}]"); prevA = f"xa{i}"
ln.append(f"[{prevA}][ma]acrossfade=d={X}[ca]")

bar_idx, badge_idx = mi+1, mi+2
active_base = mi+3
call_base = active_base + len(active)
panel_base = call_base + len(callouts)

# brightness grade only (footage usually too bright; blur was tried and dropped, see gotchas)
GRADE = getattr(C, "GRADE", "eq=brightness=-0.06:contrast=1.08:saturation=1.05:gamma=0.96")
ln.append(f"[cv]{GRADE}[bg]")
# progress bar always on (even during hooks); fill/playhead/active only in body
ln.append(f"[bg][{bar_idx}:v]overlay=x=0:y=1000[v_bar]")
ln.append(f"[v_bar][{badge_idx}:v]overlay=x=70:y=44:enable='lt(t,{main_start:.3f})'[v_badge]")
ln.append(f"[v_badge]drawbox=x={BAR_X}:y=1022:w='if(gte(t,{main_start:.3f}),(t-{main_start:.3f})/{main_out:.3f}*{BAR_W},0)':h=5:color=0x{(_BR.get('accent') or '#FF2442').lstrip('#')}:t=fill:enable='gte(t,{main_start:.3f})'[v_fill]")
ln.append(f"[v_fill]drawbox=x='{BAR_X}+(t-{main_start:.3f})/{main_out:.3f}*{BAR_W}-6':y=1017:w=12:h=15:color=white:t=fill:enable='gte(t,{main_start:.3f})'[v_play]")
prev = "v_play"
for j, a in enumerate(active):
    idx = active_base + a["k"]
    ln.append(f"[{prev}][{idx}:v]overlay=x={a['x']}:y={a['y']}:enable='between(t,{tmap(a['s']):.3f},{tmap(a['e']):.3f})'[act{j}]"); prev = f"act{j}"
CX, CY, SL, FD = 70, 70, 50, 0.25
for n, c in enumerate(callouts):
    idx = call_base + n; T0 = tmap(c["anchor"]); T1 = T0 + c["dur"]; cin = f"c{c['i']}"
    ln.append(f"[{idx}:v]format=yuva420p,setpts=PTS-STARTPTS+{T0:.3f}/TB,fade=t=in:st={T0:.3f}:d={FD}:alpha=1,fade=t=out:st={T1-FD:.3f}:d={FD}:alpha=1[{cin}]")
    ln.append(f"[{prev}][{cin}]overlay=x={CX}:y='{CY}+(1-min(1,(t-{T0:.3f})/{FD}))*{SL}':enable='between(t,{T0:.3f},{T1:.3f})'[o{c['i']}]"); prev = f"o{c['i']}"
PX, PY, PSL, PFD = 66, 86, 40, 0.35
for n, p in enumerate(panels):
    idx = panel_base + n; T0 = tmap(p["anchor"]); T1 = T0 + p["dur"]; pin = f"p{p['p']}"
    ln.append(f"[{idx}:v]format=yuva420p,setpts=PTS-STARTPTS+{T0:.3f}/TB,fade=t=in:st={T0:.3f}:d={PFD}:alpha=1,fade=t=out:st={T1-PFD:.3f}:d={PFD}:alpha=1[{pin}]")
    last = (n == len(panels)-1); ytag = "outv" if last else f"po{p['p']}"
    ln.append(f"[{prev}][{pin}]overlay=x={PX}:y='{PY}+(1-min(1,(t-{T0:.3f})/{PFD}))*{PSL}':enable='between(t,{T0:.3f},{T1:.3f})'[{ytag}]"); prev = f"po{p['p']}"
if not panels:  # if no panels, last callout (or bar) must produce outv
    ln.append(f"[{prev}]null[outv]")
ln.append(f"[ca]loudnorm=I={LUFS}:TP=-1.5:LRA=11[outa]")
open(f"{WORK}/filter.txt","w").write(";\n".join(ln)+"\n")

cmd = ["ffmpeg","-y"]
for s, e in HOOKS: cmd += ["-ss", f"{s}", "-to", f"{e}", "-i", SRC]
cmd += ["-t", f"{MAIN_DUR}", "-i", SRC, "-i", f"{WORK}/bar_overlay.png", "-i", f"{WORK}/hook_badge.png"]
for a in active: cmd += ["-i", f"{WORK}/active_{a['k']}.png"]
for c in callouts: cmd += ["-loop","1","-t", f"{c['dur']}", "-i", f"{WORK}/callout_{c['i']}.png"]
for p in panels: cmd += ["-loop","1","-t", f"{p['dur']}", "-i", f"{WORK}/panel_{p['p']}.png"]
cmd += ["-filter_complex", open(f"{WORK}/filter.txt").read(),   # inline: -/filter_complex needs ffmpeg >= 7.1
        "-map","[outv]","-map","[outa]",
        "-c:v","libx264","-crf","20","-preset","medium","-pix_fmt","yuv420p",
        "-c:a","aac","-b:a","192k","-ar","48000","-movflags","+faststart","-progress","pipe:1", OUT]
open(f"{WORK}/run.sh","w").write("#!/usr/bin/env bash\nset -e\n" + " ".join(shlex.quote(x) for x in cmd) + "\n")
os.chmod(f"{WORK}/run.sh", 0o755)
print(f"hooks {nH} | hook_dur {hook_dur:.1f}s | main_start {main_start:.1f}s | total ~{hook_dur+main_out-X:.1f}s")
print(f"wrote {WORK}/filter.txt + run.sh  (run: bash {WORK}/run.sh)")
