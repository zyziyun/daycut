# SCRIPT — quantization-explained (v2, ~10 min)

**Voice:** cedar (OpenAI gpt-4o-mini-tts)
**Voice settings:** model gpt-4o-mini-tts · speed 1.0 · format wav
**Voice direction:** Calm, curious, unhurried. A teacher thinking out loud at a whiteboard. Small pause before every "aha".

Each line: indented block = spoken English (fed to TTS). `ZH:` = 中文 subtitle source.

Worked example used throughout (4-bit, asymmetric):
weights `[-1.0, -0.43, 0.0, 0.51, 1.37, 2.0]`, s = 3/15 = 0.2, z = 5
q = `[0, 3, 5, 8, 12, 15]`, x̂ = `[-1.0, -0.4, 0.0, 0.6, 1.4, 2.0]`, max error ≤ s/2 = 0.1
Dot-product check (Frame 11): inputs `[1, 2, 1, -1, 1, 1]` → exact 1.00, rounded 1.00 (errors +0.06, −0.09, +0.03 cancel)
Outlier (Frame 13): range −1…10 → s = 11/15 ≈ 0.73, every weight in [−1, 1] lands on 3 ticks
Symmetric (Frame 12): INT4 −7…7, max |x| = 2 → s = 2/7 ≈ 0.29

---

## Line 1 — Hook (Frame 1)

**Delivery:** Quiet wonder, then a small smile on "rounding".

    Here's a strange fact. A language model with seventy billion parameters needs about a hundred and forty gigabytes of memory, just to sit there. A good graphics card has twenty-four. And yet, people run models like this on laptops. The trick is called quantization. And at its heart, it's something you learned in primary school. Rounding.

ZH: 一个奇怪的事实：一个有 700 亿参数的语言模型，光是放着就需要大约 140GB 内存。而一块好显卡只有 24GB。可人们却能在笔记本上运行这样的模型。这个技巧叫做"量化"。它的核心，其实是你小学就学过的东西——四舍五入。

## Line 2 — Rounding you already know (Frame 2)

    Before any math, notice that you round things all the time. A price of three ninety-nine is basically four dollars. A drive of fifty-two point seven kilometres is about fifty. You lose a little detail, and you keep the meaning. Computers do this too. A smooth colour gradient can use millions of shades. Squeeze it down to just sixteen, and you see a few steps, but it's clearly the same picture. Rougher, yes, and much, much smaller. Quantization does exactly this, to the numbers inside an A I model.

ZH: 先不谈数学。你其实一直在四舍五入：3.99 元基本就是 4 元；52.7 公里大约就是 50 公里。丢掉一点细节，意思却保留了。计算机也这样做：一段平滑的颜色渐变可以有几百万种颜色，压缩到只剩 16 种，你会看到几道台阶，但显然还是同一张图。更粗糙，但小得多。量化做的就是这件事——只不过对象是 AI 模型里的数字。

## Line 3 — What a weight is (Frame 3)

    So, what numbers are we talking about? Underneath, a neural network is a giant pile of numbers called weights. Each one is a decimal, like zero point three one, or minus one point two. When the model thinks, it mostly multiplies its inputs by these weights and adds them up. Billions of times. So the size of a model is simply the number of weights, times the space each one takes.

ZH: 那么，是哪些数字？神经网络的底层，是一大堆叫做"权重"的数字。每个都是小数，比如 0.31 或 −1.2。模型"思考"时，主要就是把输入乘以这些权重再加起来，重复几十亿次。所以模型的大小就是：权重的个数 × 每个权重占的空间。

## Line 4 — Bits are switches (Frame 4)

    And space is measured in bits. Think of a bit as a light switch. One switch has two positions, off or on, so it can name two different values. Add a second switch, and you get four combinations. Three switches, eight. Every new switch doubles the count. So with b bits, you can name two to the power b different values. Four bits gives sixteen. Eight bits, two hundred and fifty-six. Sixteen bits, about sixty-five thousand. Keep this doubling in mind. Every bit you remove halves your choices.

ZH: 空间用"比特"来衡量。把一个比特想象成一个电灯开关：一个开关有开、关两种状态，能表示 2 个不同的值。再加一个开关，就有 4 种组合；三个开关，8 种。每多一个开关，数量翻倍。所以 b 个比特能表示 2 的 b 次方个值：4 位是 16，8 位是 256，16 位大约 65000。记住这个翻倍规律：每去掉一位，可选的值就少一半。

## Line 5 — Number formats (Frame 5)

    The standard way to store a weight, called F P thirty-two, uses thirty-two bits: one for the sign, eight for the size, and twenty-three for the fine detail. That's far more precision than a model really needs. F P sixteen uses half as many bits, and it's what most models ship in today. But what if we went further, and stored each weight as a small whole number? Int eight uses eight bits, so two hundred and fifty-six possible values. Int four uses four bits, just sixteen. Seventy billion weights at four bits each is about thirty-five gigabytes. Suddenly, it fits.

ZH: 存储权重的标准格式叫 FP32，用 32 位：1 位符号、8 位表示大小、23 位表示精细部分。这比模型真正需要的精度多得多。FP16 只用一半的位数，也是如今大多数模型发布时用的格式。但如果更进一步，把每个权重存成一个小整数呢？INT8 用 8 位，有 256 种取值；INT4 用 4 位，只有 16 种。700 亿个权重 × 4 位 ≈ 35GB。一下子就装得下了。

## Line 6 — The core idea (Frame 6)

**Delivery:** Slow down. This is the thesis.

    So here's the core idea. Picture all your weights as dots on a number line. They can sit anywhere. Now lay down a ruler with only a few tick marks, say sixteen, evenly spaced across the range. Quantization means snapping every dot to its nearest tick. Instead of storing the exact value, you store which tick it landed on, a small integer from zero to fifteen. That's it. That's the whole principle. Everything else is about choosing the ruler well.

ZH: 核心思想是这样的：把所有权重想象成数轴上的点，它们可以落在任何位置。现在放一把只有少数刻度的尺子，比如 16 个刻度，均匀分布在整个范围上。量化就是：把每个点"吸"到离它最近的刻度上。我们不再存精确值，只存它落在第几个刻度——一个 0 到 15 的小整数。就这么简单，这就是全部原理。剩下的一切，都是在研究怎么把尺子选好。

## Line 7 — The scale (Frame 7)

    Let's do one by hand. Here are six weights. The smallest is minus one, the largest is two. We have four bits, so sixteen ticks, numbered zero to fifteen. Between the first tick and the last, there are fifteen gaps. The full range is two minus minus one, which is three. Three, shared across fifteen gaps, gives a step of zero point two. That step is called the scale, written s. It answers one question: how much real value does one integer step stand for?

ZH: 我们手算一遍。这里有 6 个权重，最小是 −1，最大是 2。我们有 4 位，所以 16 个刻度，编号 0 到 15。第一个刻度和最后一个之间有 15 个间隔。整个范围是 2 −（−1）= 3。3 分成 15 份，每一步是 0.2。这一步的大小叫做"缩放因子" s。它回答的是：整数每走一步，代表多少真实数值？

## Line 8 — The zero-point (Frame 8)

    Next, where does zero go? Our ruler starts at minus one, so real zero sits five steps up. Minus one, divided by zero point two, is minus five. Flip the sign, and you get five. That number is the zero-point, z. It's the integer that stands for the real value zero. Keeping zero exact matters, because networks are full of zeros, and we never want nothing to quietly turn into something.

ZH: 接下来，零放在哪里？尺子从 −1 开始，所以真实的 0 在往上 5 步的位置。−1 ÷ 0.2 = −5，取反得 5。这个数叫"零点" z，它是代表真实数值 0 的那个整数。让 0 保持精确很重要，因为网络里到处都是 0，我们不希望"没有"悄悄变成"有"。

## Line 9 — Quantize (Frame 9)

    Now the recipe. To quantize a weight x, divide by the scale, round to the nearest whole number, then add the zero-point. q equals round of x over s, plus z. Take zero point five one. Divided by zero point two, that's two point five five. Round it, three. Add five, eight. So zero point five one is stored as the integer eight. Let's check two more. Minus zero point four three, divided by zero point two, is minus two point one five. Round it, minus two. Add five, three. And one point three seven, divided by zero point two, is six point eight five. Round it, seven. Add five, twelve. Do this for every weight, and our six decimals become zero, three, five, eight, twelve, and fifteen. Each fits in just four bits.

ZH: 现在是公式。量化一个权重 x：除以缩放因子，四舍五入到整数，再加上零点。q = round(x / s) + z。以 0.51 为例：0.51 ÷ 0.2 = 2.55，四舍五入得 3，加 5 得 8。所以 0.51 被存成整数 8。再验算两个：−0.43 ÷ 0.2 = −2.15，取整得 −2，加 5 得 3。1.37 ÷ 0.2 = 6.85，取整得 7，加 5 得 12。每个权重都这样算，6 个小数就变成了 0、3、5、8、12、15，每个只占 4 位。

## Line 10 — Dequantize and error (Frame 10)

    When the model runs, we go backwards. Subtract the zero-point, and multiply by the scale. Eight minus five is three. Three times zero point two is zero point six. We stored zero point five one, and we got back zero point six. A small error. Do it for the whole list, and we get back minus one, minus zero point four, zero, zero point six, one point four, and two. And here's the guarantee. Because we always round to the nearest tick, the error can never be more than half a step. Here, that's zero point one. Every single weight lands within zero point one of where it started.

ZH: 模型运行时，我们反过来算：减去零点，再乘以缩放因子。8 − 5 = 3，3 × 0.2 = 0.6。存进去的是 0.51，取回来的是 0.6，有一点误差。整个列表都这样算，得到 −1、−0.4、0、0.6、1.4、2。这里有个保证：因为总是取最近的刻度，误差永远不会超过半步——这里就是 0.1。每一个权重，都落在原值 0.1 的范围之内。

## Line 11 — Why small errors don't add up (Frame 11)

    But a model has billions of weights. Why don't all these little errors pile up into a big one? Remember what the model does: it multiplies each input by a weight, and adds everything up. Let's try it with our six weights and six inputs. With the exact weights, the total is one. With the rounded weights, the total is also one. Look at the errors. Two of the products came out a little too high, one came out a little too low, and they cancelled out. Here they cancel perfectly. In a real model they cancel most of the time, not always. But the model doesn't need every weight to be perfect. It needs the sums to be about right. That's why it barely notices.

ZH: 但模型有几十亿个权重，这些小误差为什么不会累积成大误差？还记得模型做什么吗：每个输入乘以一个权重，再全部加起来。我们用这 6 个权重和 6 个输入试试：用精确权重，总和是 1；用取整后的权重，总和也是 1。看看误差：有两个乘积偏大了一点，一个偏小了一点，它们互相抵消了。这里恰好完全抵消；在真实模型里，大多数时候会抵消，但不是每次。模型不需要每个权重都完美，只需要"和"大致正确。所以它几乎察觉不到。

## Line 12 — Symmetric vs asymmetric (Frame 12)

    What we just did is called asymmetric quantization. The range can be lopsided, minus one to two, and the zero-point shifts to match. Its simpler cousin is symmetric quantization. Balance the range around zero, from minus the biggest value to plus the biggest value, and pin the zero-point at zero. With four bits, we'd use the integers minus seven to seven. Our biggest value is two, so the scale is two divided by seven, about zero point two nine. Now the formula is just q equals round of x over s. Less bookkeeping, faster math, but the ticks below minus one are wasted, because no weight lives there. Weights are usually balanced, so they tend to go symmetric. Activations, the values flowing through the network, are often lopsided, so they often go asymmetric.

ZH: 刚才这种叫"非对称量化"：范围可以不对称（−1 到 2），零点随之移动。它更简单的兄弟是"对称量化"：让范围以 0 为中心，从 −最大绝对值 到 +最大绝对值，零点固定为 0。用 4 位的话，整数取 −7 到 7。最大值是 2，所以缩放因子是 2 ÷ 7 ≈ 0.29。公式就变成 q = round(x / s)。记账更少、计算更快，但 −1 以下的刻度被浪费了，因为没有权重落在那里。权重通常比较对称，所以常用对称量化；激活值（网络中流动的数值）往往偏向一边，所以常用非对称量化。

## Line 13 — The outlier problem (Frame 13)

**Delivery:** A little drama on "the real enemy".

    Now, the real enemy: outliers. Imagine most weights live between minus one and one, but one strange weight is ten. Our ruler now has to stretch from minus one all the way to ten. That's a range of eleven, split into fifteen steps, so each step is about zero point seven three. Every ordinary weight between minus one and one now lands on one of just three ticks. Zero point one, zero point two, and zero point three all become exactly the same number. One outlier, and almost all the precision is gone. And large language models really do have outliers like this.

ZH: 现在说说真正的敌人：离群值。假设大部分权重在 −1 到 1 之间，但有一个奇怪的权重是 10。尺子现在必须从 −1 一直拉到 10。范围是 11，分成 15 步，每一步大约 0.73。所有在 −1 到 1 之间的普通权重，现在只能落在 3 个刻度上。0.1、0.2、0.3 全都变成了同一个数。一个离群值，几乎所有精度都没了。而大语言模型里，真的有这样的离群值。

## Line 14 — More rulers: granularity (Frame 14)

    The fix is to use more rulers. Per-tensor quantization uses one scale for an entire layer, so one outlier hurts everybody. Per-channel gives every row of the weight matrix its own scale, so the outlier only hurts its own row. Per-group goes further, with a fresh scale for every small block, often a hundred and twenty-eight weights. Now an outlier only ruins its own little neighbourhood, and everyone else keeps a fine ruler. The price is storing those extra scales. For groups of a hundred and twenty-eight, that's only about an eighth of a bit more per weight. A tiny cost, and a big part of what makes four-bit models actually work.

ZH: 解决办法是：多用几把尺子。逐张量（per-tensor）量化整层共用一个缩放因子，一个离群值会伤到所有人；逐通道（per-channel）让权重矩阵的每一行有自己的缩放因子，离群值只伤到自己那一行；分组（per-group）更进一步，每一小块（常见是 128 个权重）用一个新的缩放因子。这样离群值只会毁掉它自己那一小片，其他人都保留精细的尺子。代价是要多存这些缩放因子：每 128 个一组，每个权重只多大约 1/8 位。代价很小，却是 4 位模型真正可用的关键之一。

## Line 15 — When and what: PTQ vs QAT (Frame 15)

    There's also the question of when to quantize. Post-training quantization, or P T Q, takes a finished model and converts it. For the weights that's easy, because we can just look at them. Activations change with every input, so we run a few hundred sample sentences through the model and record their typical ranges. That's called calibration. P T Q is quick, and needs no retraining. Quantization-aware training, or Q A T, fakes the rounding during training itself, so the model learns to live with it. More work, but better accuracy at very low bits. You also choose what to quantize. Just the weights, which saves memory. Or weights and activations together, which also lets the hardware use fast integer math.

ZH: 还有一个问题：什么时候量化？训练后量化（PTQ）拿一个训练好的模型直接转换。权重很简单，直接看就行；激活值随每个输入而变，所以我们让几百个样本句子跑过模型，记录它们的典型范围——这叫"校准"。PTQ 速度快，不需要重新训练。量化感知训练（QAT）在训练过程中就模拟四舍五入，让模型学会适应它。工作量更大，但在极低位数下精度更好。你还要选择量化什么：只量化权重，省内存；或者权重和激活值一起量化，还能让硬件用更快的整数运算。

## Line 16 — Real methods (Frame 16)

    You'll find these ideas inside popular tools. G P T Q quantizes one column at a time, and nudges the remaining weights to cancel out the error it just made. A W Q notices that a few weights matter far more, because they meet large activations, and protects them before rounding. G G U F, the format used by llama dot c p p, stores per-group, four and five bit weights, so models run on ordinary laptops. And bits and bytes lets you load a model in eight or four bits with a single line of code.

ZH: 这些思想就藏在常用工具里。GPTQ 一次量化一列，并微调剩下的权重来抵消刚产生的误差。AWQ 发现少数权重格外重要（因为它们会遇到很大的激活值），在取整前先保护它们。GGUF 是 llama.cpp 使用的格式，按组存储 4 位和 5 位权重，让模型能在普通笔记本上运行。bitsandbytes 则让你一行代码就能以 8 位或 4 位加载模型。

## Line 17 — Trade-offs (Frame 17)

    So what do you actually gain? Going from sixteen bits to eight halves the memory, with almost no loss in quality. Four bits cuts it to a quarter, usually with a small drop. Below that, at three or two bits, quality falls off fast, unless you use special tricks. Smaller weights also mean faster answers, because the bottleneck is often just moving numbers out of memory. And that means lower cost, less energy, and models that run on your own phone, offline and private.

ZH: 那到底能得到什么？从 16 位降到 8 位，内存减半，质量几乎不变。4 位只要四分之一，通常只有一点下降。再往下到 3 位、2 位，质量会迅速下滑，除非用特殊技巧。权重更小，回答也更快，因为瓶颈往往只是把数字从内存里搬出来。这意味着更低的成本、更少的能耗，以及能在你自己手机上离线、私密运行的模型。

## Line 18 — Recap (Frame 18)

**Delivery:** Warm, conclusive. Let the last line breathe.

    Let's put it all together. Pick a range, and split it into steps. That's your scale. Mark where zero lives. That's your zero-point. Divide, round, shift, and store small integers. Multiply back when you need them. The error is at most half a step, the errors mostly cancel, and with smart choices about ranges, groups, and outliers, the model hardly feels it. Quantization is rounding, done cleverly. A little precision, traded for a model you can actually run.

ZH: 我们把它串起来：选一个范围，分成若干步——这是缩放因子。标出 0 在哪里——这是零点。除、取整、平移，存成小整数；需要时再乘回来。误差最多半步，而且大多会互相抵消；只要在范围、分组和离群值上选得聪明，模型几乎感觉不到。量化，就是聪明的四舍五入。用一点点精度，换来一个你真正跑得动的模型。
