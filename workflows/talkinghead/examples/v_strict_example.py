"""V track step 5: strict filler pass, read by `strict_pass.py apply strict.py ...`.
SYNTHETIC example. Indices come from the `strict_pass.py transcribe` printout (idx:word[t]).

DEL candidates: fillers (就是 这个 然后 像 其实 反正 嘛 的话), stray leftover syllables,
and the FIRST half of a self-repeat (keep the cleaner second take).
"""
DEL = {4, 17, 18, 31, 52}                 # word indices to remove
TEXT = {                                   # subtitle rewrites per sid after the cut (read the printed "kept || subtitle" lines)
    2: "第三句中间有个口误|被两段拼起来",
}
# optional overrides
TH = -45          # dB voiced threshold
MAXGAP = 0.12     # s: pauses up to this stay inside a run
# KEEPGAP = 0.06  # s: 气口 target; default = persona audio.pause_squeeze
