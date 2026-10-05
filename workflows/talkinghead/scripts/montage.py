"""Hook montage + body on one dissolve chain, shared by both tracks (vertical/compose.py, build_filter.py).

Built on ``vstudio.cut.xfade_assemble(mute_pad="both")``: at every dissolve the outgoing clip runs on
for xf*speed source seconds and the incoming clip starts xf*speed source seconds early, both MUTED, so
the dissolve plays over silence and never swallows the last syllable of the outgoing hook or the first
syllable of the incoming one. Sub-ranges of one hook are hard-joined (no dissolve, no pad).

The body starts at 0 of its file, where xfade_assemble has nothing earlier to pad with (it clamps the
pad at 0 and the dissolve would fade the body's first syllable in). So the body gets its own input
with a cloned first frame + silence of xf*body_speed source seconds in front (tpad/adelay), the way
the original compose.py did it; its piece is then authored in that padded clock.

Each hook range gets its own input with a fast pre-seek (``-ss``), so a hook from minute 9 does not
make ffmpeg decode and buffer minutes 0-9 for the body chain.
"""
import sys, pathlib; sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[3] / "lib"))
from vstudio import cut, media


class Montage:
    """hooks: [[(a, b), ...], ...] (a hook = one or more hard-joined source ranges; a bare (a, b) is one
    range); body: (b0, b1) source seconds. All times are seconds of ``src`` (the H source / V body).

    Attributes: input_args (ffmpeg -ss/-i list; n_inputs of them), graph, vout, aout, asm (vstudio Assembly), total,
    body_dst0 (final second where the dissolve into the body starts), body_start (final second where
    body time b0 plays), join_starts (final seconds where each dissolve starts, hooks then body)."""

    def __init__(self, src, hooks, body, hook_speed, body_speed, xf, hook_gain_db=0.0, fps=30, size=None,
                 seek_margin=3.0, src_duration=None):
        self.fps = fps
        self.xf = xf = round(xf * fps) / fps                  # xfade_assemble quantises it the same way
        self.bs = body_speed
        dur = src_duration if src_duration is not None else media.duration(src)
        pieces, xfs, self.input_args, self.off, sdur = [], [], [], [], {}
        for k, hook in enumerate(hooks):
            spans = [hook] if not isinstance(hook[0], (list, tuple)) else hook
            for i, (a, b) in enumerate(spans):
                inp = len(self.input_args) // 4
                ss = max(0.0, a - seek_margin)
                self.input_args += ["-ss", f"{ss:.3f}", "-i", src]
                pieces.append(dict(input=inp, start=a - ss, end=b - ss, speed=hook_speed, gain_db=hook_gain_db, tag="hook"))
                xfs.append(xf if (i == 0 and k > 0) else 0.0)
                self.off.append(ss); sdur[inp] = dur - ss
        nb = len(self.input_args) // 4
        self.input_args += ["-i", src]
        self.n_inputs = nb + 1
        P = xf * body_speed                                    # source seconds of padding in front of the body
        b0, b1 = body
        pieces.append(dict(input=nb, start=b0 + P, end=b1 + P, speed=body_speed, tag="body"))
        xfs.append(xf if hooks else 0.0); self.off.append(-P); sdur[nb] = dur + P
        self.asm = cut.xfade_assemble(pieces, xfade=xfs, mute_pad="both", fps=fps, size=size, src_durations=sdur)
        pad = (f"[{nb}:v]tpad=start_duration={P:.4f}:start_mode=clone[bodyv];"
               f"[{nb}:a]aresample={media.SR},adelay=delays={int(round(P * 1000))}:all=1[bodya];")
        self.graph = pad + self.asm.graph.replace(f"[{nb}:v]", "[bodyv]").replace(f"[{nb}:a]", "[bodya]")
        self.vout, self.aout = self.asm.vout, self.asm.aout
        self.tm = self.asm.timemap
        self.total = self.asm.total
        body_it = self.tm.items[-1]
        self.body_dst0 = body_it["dst0"]
        self.body_start = self.body_dst0 + (b0 + P - body_it["src0"]) / body_speed
        self.join_starts = [o for o, x in zip(self.asm.offsets, self.asm.xfades) if x > 0]

    def b2f(self, b):
        """Body second -> final second."""
        return self.body_start + b / self.bs

    def is_hook(self, t):
        it = self.tm.owner(t)
        return it is None or it.get("tag") != "body"

    def f2b(self, t, default=None):
        """Final second -> source/body second of the frame shown (hooks map to the range they show).
        Inside a muted pad the time is clamped to the spoken range, so a pad never shows the subtitle
        of a neighbouring sentence."""
        it = self.tm.owner(t)
        if it is None or it["kind"] != "clip":
            return default
        i = self.tm.items.index(it)
        s = it["src0"] + (t - it["dst0"]) * it["speed"]
        s = min(max(s, it["src0"] + it.get("mute_head", 0.0)), it["src1"] - it.get("mute_tail", 0.0) - 1e-3)
        return s + self.off[i]

    def timeline(self):
        return dict(HOOK_DUR=self.body_start, BODY_START=self.body_start, BODY_SPEED=self.bs, TOTAL=self.total,
                    XF=self.xf)
