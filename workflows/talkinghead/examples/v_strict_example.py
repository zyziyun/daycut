"""V track step 5: the creator's decisions on the speech cleanup, read by `strict_pass.py apply strict.py ...`.
SYNTHETIC example. Edit ids come from cleanup_review.md (written by cut_pass1, re-printed by `strict_pass.py review`).

Start from the `strict_draft.py` that `review` writes (REPLY = "": only the AUTO rows are cut). AUTO rows
(standalone 嗯/呃/um/uh, stutters, clear repeats) are cut unless the creator says 保留 N; CONFIRM rows (semantic
fillers 就是 那个 然后, interjections, restarts, re-takes, merged fillers) are cut only after the creator says 确认 N.
After `apply`, run `strict_pass.py verify strict.py body2_a.wav` and fix every missing-word flag (保留 N, re-apply).
"""
REPLY = "确认 3,5,9 / 保留 7"             # the creator's answer, verbatim (also: "全部确认", "approve 3,5 keep 7")
CUT = [(1, 12.30, 12.90)]                 # optional extra editor cuts: (clip, raw t0, raw t1)
TEXT = {                                   # subtitle rewrites per sid after the cut (read the printed "kept || subtitle" lines)
    2: "第三句中间有个口误|被两段拼起来",
}
# optional: APPROVE = {3, 5}; KEEP = {7}; ALL_CONFIRM = False   (same as REPLY)
# legacy: DEL = {4, 17} (bw.json word indices on the pass-1 body) is still cut
