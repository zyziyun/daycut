"""V track step 2: hand-written keep list, read by scripts/vertical/cut_pass1.py.
SYNTHETIC example: placeholder sentences and times, showing every knob.

Each entry = one spoken sentence = one sid (its list index), used by every later step:
    (clip_no, [(t0, t1), ...], "subtitle|with|manual line breaks")
- clip_no: 1..N in the order the clips were given to prep_sources.sh
- ranges: whisper word bounds in that clip's timeline (a[N].json). Word STARTS swallow the pause
  before them, word ENDS are reliable. Two ranges = the words between them are cut out.
- text must match the audio word for word; '|' forces a line break (~14 CJK chars per line max).
"""
# optional overrides of the cut_pass1 defaults
TH = -45.0       # dB: voiced-audio threshold for snapping ranges
MAXGAP = 0.20    # s: internal pauses up to this are kept inside a run
KEEPGAP = 0.10   # s: what a longer pause is squeezed to in pass 1 (strict_pass later squeezes to persona audio.pause_squeeze)

E = [
    (1, [(3.10, 5.42)], "第一句是开场白|先说今天聊什么"),                          # sid 0
    (1, [(5.80, 7.95)], "第二句交代一下背景"),                                     # sid 1
    (1, [(8.40, 10.02), (10.60, 12.30)], "第三句中间有个口误 被两段拼起来"),        # sid 2: restart cut out
    (2, [(0.50, 3.20)], "第四句来自第二段素材|片段编号从一开始"),                   # sid 3
    (2, [(3.20, 5.10)], "第五句列举第一点"),                                       # sid 4
    (2, [(5.10, 6.90)], "第六句列举第二点"),                                       # sid 5
    (2, [(6.90, 8.80)], "第七句列举第三点"),                                       # sid 6
    (2, [(9.40, 13.60)], "第八句是核心观点|值得做成卡片"),                          # sid 7
    (2, [(13.60, 15.20)], "第九句是一个可以删掉的旁白"),                            # sid 8 -> drop_pass candidate
    (3, [(1.00, 4.50)], "第十句收尾|给出一个结论"),                                 # sid 9
]
