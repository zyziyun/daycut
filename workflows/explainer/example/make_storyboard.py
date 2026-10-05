"""Generate storyboard.html: 14 static 1920x1080 SVG sketches + seam map + tokens."""
import html

BG = "#0B1020"; INK = "#ECEEF2"; DIM = "#6B7488"; FAINT = "#2A3247"
BLUE = "#58C4DD"; YEL = "#F4D35E"; TEAL = "#5CD0B3"; PINK = "#E88CC4"; RED = "#FC6255"
SERIF = "'STIX Two Text', 'Times New Roman', serif"
MONO = "'JetBrains Mono', Menlo, monospace"
SANS = "'Noto Sans SC', 'PingFang SC', sans-serif"


def t(x, y, s, size=40, fill=INK, font=SERIF, anchor="middle", weight=400, italic=False, opacity=1):
    st = "italic" if italic else "normal"
    return (f'<text x="{x}" y="{y}" font-family="{font}" font-size="{size}" fill="{fill}" '
            f'text-anchor="{anchor}" font-weight="{weight}" font-style="{st}" opacity="{opacity}">{s}</text>')


def line(x1, y1, x2, y2, c=INK, w=3, dash=None, op=1):
    d = f' stroke-dasharray="{dash}"' if dash else ""
    return f'<line x1="{x1}" y1="{y1}" x2="{x2}" y2="{y2}" stroke="{c}" stroke-width="{w}"{d} opacity="{op}"/>'


def rect(x, y, w, h, fill="none", stroke=None, sw=3, rx=0, op=1):
    s = f' stroke="{stroke}" stroke-width="{sw}"' if stroke else ""
    return f'<rect x="{x}" y="{y}" width="{w}" height="{h}" rx="{rx}" fill="{fill}"{s} opacity="{op}"/>'


def circ(x, y, r, fill, stroke=None, op=1):
    s = f' stroke="{stroke}" stroke-width="3"' if stroke else ""
    return f'<circle cx="{x}" cy="{y}" r="{r}" fill="{fill}"{s} opacity="{op}"/>'


def title(s):
    return t(120, 110, s, 44, DIM, SERIF, "start", italic=True)


def subs(en, zh):
    return (rect(0, 850, 1920, 230, "#000", op=0.35)
            + t(960, 925, html.escape(en), 38, INK, SANS)
            + t(960, 990, zh, 36, "#C9CED8", SANS))


def ruler(x0, x1, y, n, labels=None, lab_fill=PINK, tick_h=22):
    out = [line(x0 - 30, y, x1 + 30, y, DIM, 3)]
    for i in range(n):
        x = x0 + (x1 - x0) * i / (n - 1)
        out.append(line(x, y - tick_h, x, y + tick_h, INK, 3))
        if labels is not None:
            out.append(t(x, y + 62, labels[i], 26, lab_fill, MONO))
    return "".join(out)


W = [-1.0, -0.43, 0.0, 0.51, 1.37, 2.0]
Q = [0, 3, 5, 8, 12, 15]


def X(v, x0=260, x1=1660, lo=-1.0, hi=2.0):
    return x0 + (v - lo) / (hi - lo) * (x1 - x0)


frames = []

# 1 Hook
f = title("Why can't a laptop run a 70B model?")
f += rect(560, 180, 260, 600, BLUE, op=0.85) + t(870, 220, "140 GB", 56, BLUE, MONO, "start", weight=700)
f += t(690, 830, "70B model · FP16", 30, INK, MONO)
f += rect(1000, 677, 260, 103, "none", TEAL, 4) + t(1130, 650, "24 GB", 56, TEAL, MONO, weight=700)
f += t(1130, 830, "your GPU", 30, INK, MONO)
f += line(980, 677, 1290, 677, RED, 3, "10 8") + t(1310, 690, "won't fit", 34, RED, SERIF, "start", italic=True)
f += t(1580, 470, "3.14159", 70, BLUE, MONO) + t(1580, 560, "↓", 60, DIM) + t(1580, 660, "3", 110, YEL, SERIF, weight=700)
f += subs("The trick is called quantization. At its heart: rounding.", "这个技巧叫做“量化”。它的核心：四舍五入。")
frames.append(("01", "HOOK", "0:00–0:22", f,
               "<b>Bars count up first</b>, 140 GB rises past the GPU outline and the red line flashes; “3.14159 → 3” lands on the word “Rounding.”", "crossfade"))

# NEW Rounding you already know
f = title("You already round things all the time")
f += t(330, 260, "$3.99", 72, BLUE, MONO) + t(330, 330, "↓", 50, DIM) + t(330, 420, "≈ $4", 72, YEL, MONO)
f += t(330, 530, "52.7 km  →  ≈ 50 km", 34, INK, MONO)
for i in range(240):
    v = i / 239
    f += rect(720 + i * 4.5, 200, 4.6, 150, f"rgb({int(40+v*48)},{int(60+v*136)},{int(110+v*111)})")
for i in range(16):
    v = i / 15
    f += rect(720 + i * 67.5, 420, 67.6, 150, f"rgb({int(40+v*48)},{int(60+v*136)},{int(110+v*111)})")
f += t(720, 180, "millions of shades", 30, INK, MONO, "start") + t(720, 400, "just 16 shades", 30, YEL, MONO, "start")
f += t(1260, 680, "rougher · same picture · much smaller", 40, INK, SERIF, italic=True)
f += subs("Squeeze it down to just sixteen, and it's clearly the same picture.", "压缩到只剩 16 种颜色，显然还是同一张图。")
frames.append(("xx", "ROUNDING", "", f,
               "<b>The price rounds first</b> ($3.99 ticks to $4), then the smooth gradient posterizes into 16 bands in one wipe, left→right.", "crossfade"))

# 2 Weights
f = title("A neural network is a pile of numbers")
ins = [250, 420, 590]; labs = ["0.31", "−1.2", "0.87"]
for y, l in zip(ins, labs):
    f += line(300, y, 760, 420, BLUE, 3) + circ(300, y, 34, BG, INK)
    f += t(530, (y + 420) / 2 - 14, l, 30, YEL, MONO)
f += circ(790, 420, 44, BG, INK) + t(790, 432, "Σ", 40, INK)
for r in range(7):
    for c in range(8):
        v = ((r * 37 + c * 53) % 200 - 100) / 83
        col = BLUE if (r + c) % 9 == 0 else DIM
        f += t(1060 + c * 100, 180 + r * 70, f"{v:+.2f}", 26, col, MONO)
f += t(960, 770, 'model size&#160;=&#160;<tspan fill="#58C4DD"># weights</tspan>&#160;×&#160;<tspan fill="#F4D35E">bits per weight</tspan>', 52, INK, SERIF)
f += subs("So the size of a model is the number of weights, times the space each one takes.", "模型大小 = 权重个数 × 每个权重占的空间。")
frames.append(("02", "WEIGHTS", "0:22–0:49", f,
               "<b>Connections draw on</b> with their decimal labels, then the camera pulls back to the grid; the size equation writes left→right.", "crossfade"))

# NEW Bits are switches
f = title("A bit is a light switch")
rows = [(1, "2"), (2, "4"), (3, "8"), (4, "16"), (8, "256")]
for k, (n, cnt) in enumerate(rows):
    y = 180 + k * 115
    f += t(250, y + 48, f"{n} bit" + ("s" if n > 1 else ""), 34, INK, MONO, "end")
    for j in range(n):
        on = (j * 7 + n) % 3 == 0
        f += rect(300 + j * 72, y, 56, 80, YEL if on else "#1b2440", INK, 2, 10)
        f += circ(328 + j * 72, y + (24 if on else 56), 12, BG if on else DIM)
    f += t(1000, y + 52, "→", 40, DIM) + t(1080, y + 54, f"{cnt} values", 40, PINK, MONO, "start", 700)
f += t(1560, 420, '2<tspan dy="-30" font-size="56">b</tspan>', 120, YEL, SERIF, italic=True)
f += t(1560, 520, "values", 36, INK, SERIF, italic=True)
f += t(1560, 640, "each switch doubles it", 30, DIM, MONO)
f += subs("So with b bits, you can name two to the power b different values.", "所以 b 个比特能表示 2 的 b 次方个不同的值。")
frames.append(("xx", "BITS = SWITCHES", "", f,
               "<b>Switches flip on one row at a time</b>; each count doubles with a pop; 2ᵇ writes in on “two to the power b”.", "crossfade"))

# 3 Bits
f = title("How many bits per number?")
cell = 46
def strip(y, n, cols, label, size, right_col=INK):
    s = t(150, y + 34, label, 32, INK, MONO, "end")
    for i in range(n):
        s += rect(180 + i * cell, y, cell - 6, 46, cols(i), rx=4)
    s += t(1660, y + 34, size, 34, right_col, MONO, "start", weight=700)
    return s
f += strip(170, 32, lambda i: RED if i == 0 else (YEL if i < 9 else BLUE), "FP32", "280 GB")
f += t(180, 250, "sign", 22, RED, MONO, "start") + t(250, 250, "exponent (8)", 22, YEL, MONO, "start") + t(600, 250, "mantissa / fine detail (23)", 22, BLUE, MONO, "start")
f += strip(310, 16, lambda i: RED if i == 0 else (YEL if i < 6 else BLUE), "FP16", "140 GB")
f += strip(430, 8, lambda i: PINK, "INT8", "70 GB")
f += t(600, 464, "256 values", 30, PINK, MONO, "start")
f += strip(550, 4, lambda i: PINK, "INT4", "35 GB ✓", TEAL)
f += t(420, 584, "16 values", 30, PINK, MONO, "start")
f += t(960, 740, "70 billion × 4 bits ≈ 35 GB", 48, INK, SERIF, italic=True)
f += subs("Seventy billion weights at four bits each is about thirty-five gigabytes.", "700 亿个权重 × 4 位 ≈ 35GB。一下子就装得下了。")
frames.append(("03", "BITS", "0:49–1:29", f,
               "<b>The 32-cell strip builds cell by cell</b>, then each lower row is the strip collapsing; sizes count down 280→35 and the INT4 row turns teal.", "cut"))

# 4 Core idea
f = title("Snap every dot to its nearest tick")
x0, x1 = 160, 1760
ticks = [x0 + (x1 - x0) * i / 15 for i in range(16)]
f += ruler(x0, x1, 480, 16, [str(i) for i in range(16)])
raw = [175 + ((i * 0.6180339887) % 1.0) * 1570 for i in range(34)]
stack = {}
for i, rx_ in enumerate(raw):
    near = min(ticks, key=lambda tx: abs(tx - rx_))
    k = stack.get(near, 0); stack[near] = k + 1
    yy = 250 + (i % 5) * 26
    f += circ(rx_, yy, 9, BLUE, op=0.28)
    f += line(rx_, yy, near, 446 - k * 24, BLUE, 1.5, "4 6", 0.3)
    f += circ(near, 446 - k * 24, 10, BLUE)
f += t(960, 680, "store the tick number, not the exact value", 46, INK, SERIF, italic=True)
f += t(960, 750, '<tspan fill="#58C4DD">0.4817…</tspan>  →  <tspan fill="#E88CC4">tick 7</tspan>', 44, INK, MONO)
f += subs("Quantization means snapping every dot to its nearest tick.", "量化就是：把每个点“吸”到离它最近的刻度上。")
frames.append(("04", "CORE IDEA", "1:29–2:00", f,
               "<b>The signature shot.</b> Dots scatter in, 16 ticks drop from above, then every dot slides down to its nearest tick (staggered ~0.4s); indices pop in pink.", "cut"))

# 5 Scale
f = title("Step 1 · the scale s")
f += ruler(260, 1660, 470, 16)
for v in W:
    f += circ(X(v), 420, 13, BLUE) + t(X(v), 385, f"{v:g}", 28, BLUE, MONO)
f += f'<path d="M260 300 Q260 270 300 270 L920 270 Q960 270 960 240 Q960 270 1000 270 L1620 270 Q1660 270 1660 300" fill="none" stroke="{INK}" stroke-width="3"/>'
f += t(960, 215, "range = 2 − (−1) = 3", 40, INK, SERIF, italic=True)
g0 = X(-1.0); g1 = X(-1.0) + 1400 / 15
f += rect(g0, 500, g1 - g0, 24, YEL, op=0.8) + t((g0 + g1) / 2, 560, "one step", 24, YEL, MONO)
f += t(960, 720, '<tspan fill="#F4D35E" font-style="italic">s</tspan> = 3 ÷ 15 gaps = <tspan fill="#F4D35E">0.2</tspan>', 64, INK, SERIF)
f += subs("Three, shared across fifteen gaps, gives a step of zero point two.", "3 分成 15 份，每一步是 0.2。这叫“缩放因子” s。")
frames.append(("05", "SCALE", "2:00–2:33", f,
               "<b>Six labelled dots land</b>, the range brace draws over them, then one gap flashes yellow and the s equation builds term by term.", "cut"))

# 6 Zero-point
f = title("Step 2 · the zero-point z")
f += ruler(260, 1660, 470, 16, [str(i) for i in range(16)])
for k in range(5):
    a = X(-1.0) + k * 1400 / 15; b = a + 1400 / 15
    f += f'<path d="M{a} 440 Q{(a+b)/2} 360 {b} 440" fill="none" stroke="{TEAL}" stroke-width="4"/>'
    f += t((a + b) / 2, 370, f"{k+1}", 26, TEAL, MONO)
f += line(X(0), 300, X(0), 445, TEAL, 4) + t(X(0), 280, "real 0", 34, TEAL, SERIF, italic=True)
f += t(960, 700, '<tspan fill="#5CD0B3" font-style="italic">z</tspan> = −(−1.0 ÷ 0.2) = <tspan fill="#5CD0B3">5</tspan>', 64, INK, SERIF)
f += rect(1440, 620, 340, 70, "none", TEAL, 3, 35) + t(1610, 667, "0 stays exactly 0", 28, TEAL, MONO)
f += subs("That number is the zero-point, z. The integer that stands for zero.", "这个数叫“零点” z，它是代表真实数值 0 的那个整数。")
frames.append(("06", "ZERO-POINT", "2:33–3:00", f,
               "<b>Five teal hops</b> count up from tick 0 to real zero, one per spoken step; then z resolves to 5.", "crossfade"))

# 7 Quantize
f = title("Step 3 · quantize")
f += t(960, 250, '<tspan fill="#E88CC4" font-style="italic">q</tspan> = round( <tspan fill="#58C4DD" font-style="italic">x</tspan> / <tspan fill="#F4D35E" font-style="italic">s</tspan> ) + <tspan fill="#5CD0B3" font-style="italic">z</tspan>', 92, INK, SERIF)
chain = [("0.51", BLUE), ("÷ 0.2", YEL), ("2.55", INK), ("round", DIM), ("3", INK), ("+ 5", TEAL), ("8", PINK)]
for i, (s_, c) in enumerate(chain):
    x = 250 + i * 236
    f += t(x, 440, s_, 50, c, MONO, weight=700 if c == PINK else 400)
    if i < len(chain) - 1:
        f += t(x + 118, 440, "→", 40, DIM)
f += t(160, 610, "x", 40, BLUE, SERIF, "end", italic=True) + t(160, 700, "q", 40, PINK, SERIF, "end", italic=True)
for i, (v, q) in enumerate(zip(W, Q)):
    x = 300 + i * 260
    f += t(x, 610, f"{v:g}", 40, BLUE, MONO) + t(x, 700, str(q), 44, PINK, MONO, weight=700)
f += line(200, 640, 1700, 640, FAINT, 2) + t(1700, 760, "each q fits in 4 bits", 26, DIM, MONO, "end")
f += subs("Zero point five one is stored as the integer eight.", "所以 0.51 被存成整数 8。")
frames.append(("07", "QUANTIZE", "3:00–3:33", f,
               "<b>Formula writes in, colour by colour</b>; the 0.51 chain steps right one token per spoken beat; table rows waterfall in.", "crossfade"))

# 8 Dequantize + error
f = title("Step 4 · back again, and the error")
f += t(560, 230, '<tspan fill="#58C4DD" font-style="italic">x̂</tspan> = <tspan fill="#F4D35E" font-style="italic">s</tspan> · ( <tspan fill="#E88CC4" font-style="italic">q</tspan> − <tspan fill="#5CD0B3" font-style="italic">z</tspan> )', 76, INK, SERIF)
f += t(560, 340, "0.2 × (8 − 5) = 0.6", 44, INK, MONO)
zx0, zx1 = 160, 960  # zoomed ruler 0.4..0.8
def ZX(v): return zx0 + (v - 0.4) / 0.4 * (zx1 - zx0)
f += rect(ZX(0.5), 470, ZX(0.7) - ZX(0.5), 120, RED, op=0.12)
f += ruler(ZX(0.4), ZX(0.8), 560, 3, ["0.4", "0.6", "0.8"], DIM)
f += circ(ZX(0.51), 520, 12, BLUE) + t(ZX(0.51), 495, "0.51", 28, BLUE, MONO)
f += line(ZX(0.51), 600, ZX(0.6), 600, RED, 6) + t(ZX(0.555), 650, "error 0.09", 28, RED, MONO)
f += t(560, 750, "error ≤ s/2 = 0.1", 46, RED, SERIF, italic=True)
f += t(1180, 300, "q", 34, PINK, SERIF, "end", italic=True) + t(1180, 380, "x̂", 34, BLUE, SERIF, "end", italic=True) + t(1180, 460, "x", 34, DIM, SERIF, "end", italic=True)
for i, (v, q, xh) in enumerate(zip(W, Q, [-1.0, -0.4, 0.0, 0.6, 1.4, 2.0])):
    x = 1250 + i * 105
    f += t(x, 300, str(q), 34, PINK, MONO, weight=700) + t(x, 380, f"{xh:g}", 32, BLUE, MONO) + t(x, 460, f"{v:g}", 26, DIM, MONO)
f += line(1140, 330, 1820, 330, FAINT, 2)
f += t(1510, 560, "every weight within 0.1", 34, RED, SERIF, italic=True)
f += subs("The error can never be more than half a step.", "误差永远不会超过半步——这里就是 0.1。")
frames.append(("08", "DEQUANT + ERROR", "3:33–4:09", f,
               "<b>Formula first, then zoom into the ruler</b> around 0.6; the red error bar draws; then the full table fills: q → x̂, original x greyed below.", "cut"))

# NEW Why errors cancel
f = title("Why small errors don't pile up")
AIN = [1, 2, 1, -1, 1, 1]; XH = [-1.0, -0.4, 0.0, 0.6, 1.4, 2.0]
f += t(330, 200, "input", 28, DIM, MONO) + t(560, 200, "exact w", 28, BLUE, MONO) + t(800, 200, "rounded ŵ", 28, PINK, MONO) + t(1060, 200, "error in product", 28, RED, MONO)
for i, (a_, w_, h_) in enumerate(zip(AIN, W, XH)):
    y = 260 + i * 62
    e = round(a_ * (h_ - w_), 2)
    f += t(330, y, f"{a_:g}", 34, INK, MONO) + t(560, y, f"{w_:g}", 34, BLUE, MONO) + t(800, y, f"{h_:g}", 34, PINK, MONO)
    f += t(1060, y, ("+" if e > 0 else "") + f"{e:g}" if e else "0", 34, RED if e else DIM, MONO)
f += line(240, 640, 1200, 640, FAINT, 2)
f += t(560, 700, "Σ = 1.00", 40, BLUE, MONO, weight=700) + t(800, 700, "Σ = 1.00", 40, PINK, MONO, weight=700) + t(1060, 770, "+0.06 − 0.09 + 0.03 = 0", 30, RED, MONO)
f += t(1560, 380, "the sum", 50, INK, SERIF, italic=True) + t(1560, 450, "is what matters", 50, INK, SERIF, italic=True)
f += t(1560, 560, "errors mostly cancel", 32, DIM, MONO)
f += subs("With the exact weights, the total is one. With the rounded weights, also one.", "用精确权重，总和是 1；用取整后的权重，总和也是 1。")
frames.append(("xx", "ERRORS CANCEL", "", f,
               "<b>Rows multiply one by one</b>, the two Σ count up side by side and land on the same 1.00; the red errors then slide together and cancel to 0.", "crossfade"))

# 9 Sym vs asym
f = line(960, 140, 960, 800, FAINT, 2)
f += t(480, 120, "Asymmetric", 46, INK, SERIF, italic=True) + t(1440, 120, "Symmetric", 46, INK, SERIF, italic=True)
f += ruler(120, 840, 360, 16)
f += t(120, 440, "−1", 28, BLUE, MONO) + t(840, 440, "2", 28, BLUE, MONO)
zx = 120 + 5 * 720 / 15
f += line(zx, 300, zx, 400, TEAL, 5) + t(zx, 285, "z = 5", 30, TEAL, MONO)
f += t(480, 560, '<tspan fill="#E88CC4" font-style="italic">q</tspan> = round(<tspan fill="#58C4DD" font-style="italic">x</tspan>/<tspan fill="#F4D35E" font-style="italic">s</tspan>) + <tspan fill="#5CD0B3" font-style="italic">z</tspan>', 52, INK, SERIF)
for i in range(16):
    x = 1080 + i * 720 / 15
    f += line(x, 338, x, 382, INK if x >= 1080 + 720 / 4 else DIM, 3, op=1 if x >= 1080 + 720 / 4 else 0.35)
f += line(1050, 360, 1830, 360, DIM, 3)
f += t(1080, 440, "−2", 28, BLUE, MONO) + t(1800, 440, "2", 28, BLUE, MONO) + t(1260, 470, "wasted", 24, RED, MONO)
f += line(1440, 300, 1440, 400, TEAL, 5) + t(1440, 285, "z = 0", 30, TEAL, MONO)
f += t(1440, 560, '<tspan fill="#E88CC4" font-style="italic">q</tspan> = round(<tspan fill="#58C4DD" font-style="italic">x</tspan>/<tspan fill="#F4D35E" font-style="italic">s</tspan>)', 52, INK, SERIF)
f += t(1440, 630, "INT4: −7…7 · s = 2/7 ≈ 0.29", 28, YEL, MONO)
f += t(480, 700, "activations → often", 34, DIM, SERIF, italic=True) + t(1440, 700, "weights → usually", 34, DIM, SERIF, italic=True)
f += subs("Its simpler cousin is symmetric quantization.", "它更简单的兄弟是“对称量化”。")
frames.append(("09", "SYM vs ASYM", "4:09–4:48", f,
               "<b>Left ruler slides in from the previous frame</b> (same ruler, callback to 05), right ruler mirrors it; dimmed ticks fade on “wasted”.", "crossfade"))

# Outliers
f = title("The real enemy: one outlier")
def OX(v): return 200 + (v + 1) / 11 * 1500
f += line(170, 420, 1730, 420, DIM, 3)
for k in range(16):
    x = 200 + k * 100
    f += line(x, 398, x, 442, INK, 3)
for i in range(22):
    v = -0.95 + i * 0.09
    f += circ(OX(v), 370 - (i % 4) * 22, 9, BLUE)
f += circ(OX(10), 370, 16, RED) + t(OX(10), 330, "10", 40, RED, MONO, weight=700)
f += rect(185, 300, 230, 160, "none", RED, 2, 10, op=0.8) + t(300, 500, "only 3 ticks", 28, RED, MONO)
f += t(960, 230, '<tspan fill="#F4D35E" font-style="italic">s</tspan> = (10 − (−1)) ÷ 15 ≈ <tspan fill="#F4D35E">0.73</tspan>', 56, INK, SERIF)
f += t(960, 660, "0.1 → 0&#160;&#160;&#160;&#160;&#160;0.2 → 0&#160;&#160;&#160;&#160;&#160;0.3 → 0", 44, INK, MONO)
f += t(960, 740, "same integer — the detail is gone", 34, RED, SERIF, italic=True)
f += subs("Zero point one, zero point two, and zero point three all become exactly the same number.", "0.1、0.2、0.3 全都变成了同一个数。")
frames.append(("xx", "OUTLIER", "", f,
               "<b>The red dot slides right and drags the ruler</b> with it: ticks spread out, blue dots collapse onto 3 ticks; the s value counts up 0.2 → 0.73.", "cut"))

# Granularity
f = title("The fix: more rulers")
labels = [("per-tensor", 1), ("per-channel", 6), ("per-group", 12)]
for k, (lab, n) in enumerate(labels):
    ox = 150 + k * 570; oy = 180
    f += rect(ox, oy, 480, 360, "none", DIM, 2)
    for r in range(6):
        for c in range(8):
            red = (r == 2 and c == 5)
            f += rect(ox + 14 + c * 57, oy + 14 + r * 56, 48, 46, RED if red else BLUE, op=0.9 if red else 0.18)
    if n == 1:
        f += rect(ox, oy, 480, 360, RED, op=0.10) + rect(ox, oy, 480, 360, "none", YEL, 4)
    elif n == 6:
        f += rect(ox + 6, oy + 6 + 2 * 56, 468, 56, RED, op=0.15)
        for r in range(6):
            f += rect(ox + 6, oy + 6 + r * 56, 468, 56, "none", YEL, 2)
    else:
        f += rect(ox + 6 + 2 * 117, oy + 6 + 1 * 116, 115, 114, RED, op=0.15)
        for r in range(3):
            for c in range(4):
                f += rect(ox + 6 + c * 117, oy + 6 + r * 116, 115, 114, "none", YEL, 2)
    f += t(ox + 240, oy + 420, lab, 40, INK, SERIF, italic=True)
    f += t(ox + 240, oy + 465, ["1 scale · outlier hurts all", "1 scale / row", "1 scale / 128 weights"][k], 26, YEL, MONO)
f += t(960, 770, "cost: ≈ 1/8 bit per weight", 34, DIM, MONO)
f += subs("Now an outlier only ruins its own little neighbourhood.", "这样离群值只会毁掉它自己那一小片。")
frames.append(("xx", "GRANULARITY", "", f,
               "<b>One matrix, three treatments</b>: the red-tinted damage zone shrinks from the whole box → one row → one block as each name is spoken.", "crossfade"))

# 11 PTQ / QAT
f = title("When do you quantize?")
def box(x, y, w, s, c):
    return rect(x, y, w, 90, "none", c, 3, 14) + t(x + w / 2, y + 57, s, 32, c, MONO)
f += t(110, 255, "PTQ", 44, YEL, SERIF, "start", 700)
f += box(300, 200, 240, "train ✓", INK) + t(575, 255, "→", 40, DIM) + box(610, 200, 460, "calibrate (samples)", BLUE) + t(1115, 255, "→", 40, DIM) + box(1160, 200, 300, "quantize", PINK)
f += t(1520, 255, "fast · no retraining", 28, DIM, SERIF, "start", italic=True)
f += t(110, 455, "QAT", 44, TEAL, SERIF, "start", 700)
f += box(300, 400, 770, "train with fake rounding ↺", TEAL) + t(1110, 455, "→", 40, DIM) + box(1160, 400, 300, "quantize", PINK)
f += t(1520, 455, "more work · better at low bits", 28, DIM, SERIF, "start", italic=True)
f += rect(260, 610, 620, 110, "none", BLUE, 3, 55) + t(570, 677, "weights only → less memory", 32, BLUE, MONO)
f += rect(1000, 610, 680, 110, "none", YEL, 3, 55) + t(1340, 677, "+ activations → integer math", 32, YEL, MONO)
f += subs("Quantization-aware training fakes the rounding during training itself.", "量化感知训练（QAT）在训练过程中就模拟四舍五入。")
frames.append(("11", "PTQ vs QAT", "5:32–6:08", f,
               "<b>PTQ pipeline draws left→right</b>, then QAT draws underneath with its loop arrow spinning once; the two chips pop last.", "crossfade"))

# 12 Methods
cards = [("GPTQ", YEL, ["one column at a time", "push the error onto", "the remaining weights"]),
         ("AWQ", TEAL, ["protect the few weights", "that meet big", "activations"]),
         ("GGUF", BLUE, ["llama.cpp format", "per-group 4/5-bit", "runs on a laptop"]),
         ("bitsandbytes", PINK, ["load_in_4bit=True", "one line of code", "8-bit or 4-bit"])]
f = title("The same ideas, inside real tools")
for i, (n, c, ls) in enumerate(cards):
    x = 110 + i * 435
    f += rect(x, 170, 395, 560, "#121a30", c, 3, 20)
    f += t(x + 197, 260, n, 52, c, SERIF, weight=700)
    f += line(x + 40, 300, x + 355, 300, FAINT, 2)
    for j, l in enumerate(ls):
        f += t(x + 197, 380 + j * 60, l, 27, INK, MONO)
f += subs("GPTQ quantizes one column at a time, and nudges the remaining weights.", "GPTQ 一次量化一列，并微调剩下的权重来抵消误差。")
frames.append(("12", "REAL TOOLS", "6:08–6:45", f,
               "<b>Cards rise one per name as it is spoken</b> (no stagger dump); the active card stays lit, the others dim to 50%.", "crossfade"))

# 13 Trade-offs
f = title("What do you gain, and lose?")
bits = [16, 8, 4, 3, 2]; qual = [100, 99, 96, 85, 55]
f += line(240, 720, 1500, 720, DIM, 2)
pts = []
for i, (b, qv) in enumerate(zip(bits, qual)):
    x = 340 + i * 260; h = b / 16 * 480
    f += rect(x - 60, 720 - h, 120, h, BLUE, op=0.75)
    f += t(x, 770, f"{b}-bit", 30, INK, MONO) + t(x, 760 - h if h > 120 else 700 - h, f"{b/16*140:.0f} GB", 26, BG if h > 120 else BLUE, MONO, weight=700)
    pts.append((x, 720 - qv * 5.2))
f += '<polyline points="' + " ".join(f"{x},{y}" for x, y in pts) + f'" fill="none" stroke="{YEL}" stroke-width="5"/>'
for x, y in pts:
    f += circ(x, y, 9, YEL)
f += t(1560, 190, "quality", 30, YEL, SERIF, "start", italic=True) + t(1560, 240, "memory", 30, BLUE, SERIF, "start", italic=True)
for j, s_ in enumerate(["faster", "cheaper", "less energy", "on your phone"]):
    f += t(1600, 380 + j * 80, s_, 34, INK, SANS, "start")
f += subs("Four bits cuts the memory to a quarter, usually with a small drop.", "4 位只要四分之一内存，通常只有一点下降。")
frames.append(("13", "TRADE-OFFS", "6:45–7:17", f,
               "<b>Bars shrink right→left on each bit-width</b>, then the yellow quality line draws and visibly drops off a cliff after 4-bit. Illustrative values, labelled as such.", "crossfade"))

# 14 Recap
f = ruler(260, 1660, 200, 16)
for v in W:
    f += circ(X(v), 160, 11, BLUE)
steps = [("pick a range, split it into steps", "s", YEL), ("mark where zero lives", "z", TEAL),
         ("divide · round · shift → store", "q", PINK), ("multiply back when needed", "x̂", BLUE)]
for i, (s_, sym, c) in enumerate(steps):
    y = 340 + i * 80
    f += t(560, y, sym, 50, c, SERIF, "end", italic=True) + t(620, y, s_, 40, INK, SERIF, "start")
f += t(960, 760, "Quantization is rounding, done cleverly.", 64, YEL, SERIF, italic=True)
f += subs("A little precision, traded for a model you can actually run.", "用一点点精度，换来一个你真正跑得动的模型。")
frames.append(("14", "RECAP", "7:17–7:45", f,
               "<b>The ruler from 04 returns</b> (callback); the four recipe lines stack one per sentence; the closing line holds still for 3s — the film's one held frame.", "fade out"))


import re as _re
frames = [(f"{i+1:02d}",) + fr[1:] for i, fr in enumerate(frames)]
_scr = open("SCRIPT.md").read()
_wc = [sum(len(l.split()) for l in b.split("\n") if l.startswith("    ")) for b in _re.split(r"\n## Line ", _scr)[1:]]
_t = 0.0
for _i, _w in enumerate(_wc):
    _d = _w / 2.92
    _a = f"{int(_t//60)}:{int(_t%60):02d}"; _t += _d
    _b = f"{int(_t//60)}:{int(_t%60):02d}"
    _f = frames[_i]; frames[_i] = (_f[0], _f[1], f"{_a}–{_b}", _f[3], _f[4], _f[5])
TOTAL = f"{int(_t//60)}:{int(_t%60):02d}"


def svg(body):
    return (f'<svg viewBox="0 0 1920 1080" xmlns="http://www.w3.org/2000/svg">'
            f'<rect width="1920" height="1080" fill="{BG}"/>{body}</svg>')


cells = []
for num, name, tc, body, note, seam in frames:
    cells.append(f'''<figure class="cell" id="frame-{num}">
  <div class="frame">{svg(body)}</div>
  <figcaption><div class="lab"><span>{num} · {name}</span><span>f{num} · {tc}</span></div>
  <p>{note}</p><span class="chip">seam → {seam}</span></figcaption></figure>''')

seams = "".join(f'<div class="seam"><b>{n}</b><span>{s}</span></div>' for n, _, _, _, _, s in frames)
cells.append(f'''<figure class="cell"><div class="frame meta"><h3>Seam map</h3><div class="seams">{seams}</div>
<p>Direction rule: content enters from the left / below, exits right. Math frames 07→10 share one ruler that never leaves the screen (cuts, not fades) so the worked example reads as one continuous board.</p></div>
<figcaption><div class="lab"><span>SEAMS</span><span>{len(frames)} frames · ~{TOTAL}</span></div></figcaption></figure>''')
sw = "".join(f'<div class="sw"><i style="background:{c}"></i>{n}<br><code>{c}</code></div>' for n, c in
             [("bg", BG), ("ink", INK), ("x · value", BLUE), ("s · scale", YEL), ("z · zero-point", TEAL), ("q · integer", PINK), ("error", RED)])
cells.append(f'''<figure class="cell"><div class="frame meta"><h3>Tokens</h3><div class="sws">{sw}</div>
<p><b>Type:</b> STIX Two Text (titles, math, italic variables) · JetBrains Mono (numbers) · Noto Sans SC (bilingual subtitles: EN 38px / 中文 36px).</p>
<p><b>Safe zone:</b> math in y 80–800; subtitles band y 850–1040.</p>
<p><b>Bans:</b> no glow, no stock icons, no slideshow card-swaps — the ruler persists and transforms; no motion that doesn't follow the narration.</p></div>
<figcaption><div class="lab"><span>TOKENS</span><span>3b1b-inspired</span></div></figcaption></figure>''')

page = f'''<!doctype html><html lang="en"><head><meta charset="utf-8"><title>Quantization, explained — storyboard v2</title>
<style>
body{{margin:0;background:#05070d;color:#dfe3ea;font-family:-apple-system,'PingFang SC',sans-serif;padding:40px 48px}}
header h1{{font-family:{SERIF};font-weight:400;font-size:44px;margin:0}} header p{{color:#9aa3b5;margin:6px 0 0}}
.tag{{display:inline-block;margin-top:12px;border:1px solid #2a3247;border-radius:20px;padding:4px 14px;font:13px Menlo,monospace;color:#9aa3b5}}
.grid{{display:grid;grid-template-columns:repeat(3,1fr);gap:28px;margin-top:32px}}
.cell{{margin:0}} .frame{{aspect-ratio:16/9;container-type:inline-size;border-radius:8px;overflow:hidden;border:1px solid #1d2438}}
.frame svg{{width:100%;height:100%;display:block}}
.lab{{display:flex;justify-content:space-between;font:12px Menlo,monospace;color:#9aa3b5;margin-top:10px;letter-spacing:.04em}}
figcaption p{{font-size:13.5px;line-height:1.5;margin:6px 0}} .chip{{font:11px Menlo,monospace;border:1px solid #2a3247;border-radius:10px;padding:2px 8px;color:#5CD0B3}}
.meta{{background:{BG};padding:3cqw;box-sizing:border-box;font-size:2.4cqw}} .meta h3{{font-family:{SERIF};font-weight:400;font-size:4cqw;margin:0 0 2cqw}}
.meta p{{margin:1.4cqw 0;color:#c9ced8}} .seams{{display:grid;grid-template-columns:repeat(7,1fr);gap:1cqw}}
.seam{{border:1px solid #2a3247;border-radius:6px;padding:.8cqw;font:2cqw Menlo,monospace;display:flex;flex-direction:column}} .seam span{{color:#5CD0B3}}
.sws{{display:grid;grid-template-columns:repeat(7,1fr);gap:1cqw;font:1.8cqw Menlo,monospace}} .sw i{{display:block;height:5cqw;border-radius:4px;border:1px solid #2a3247;margin-bottom:.6cqw}}
.sw code{{color:#6B7488}}
</style></head><body>
<header><h1>Quantization, explained — storyboard v2</h1>
<p>A 3Blue1Brown-style explainer: why, the principle, the math by hand, the types, the tools.</p>
<span class="tag">1920×1080 · ~{TOTAL} (voice at 1.0×) · {len(frames)} frames · EN voice + EN/中文 subtitles</span></header>
<main class="grid">{"".join(cells)}</main></body></html>'''

open("storyboard.html", "w").write(page)
print("wrote storyboard.html", len(page))
