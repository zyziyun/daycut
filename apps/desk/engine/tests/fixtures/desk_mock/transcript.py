"""A deterministic word-level transcript of a made-up Chinese lecture about RAG (no whisper): the test engine's batches,
segment plans and clip words."""


CORPUS = [
    ("RAG 全景", "今天 我们 聊 一下 RAG 到底 解决 什么 问题 很多 人 以为 就是 把 文档 塞进 向量 数据库 其实 远远 不够"),
    ("RAG 全景", "检索 增强 生成 的 核心 是 让 模型 在 回答 之前 先 找到 对的 资料 然后 再 基于 资料 组织 答案"),
    ("切块策略", "第一个 坑 是 切块 切 得 太 碎 上下文 就 断 了 切 得 太 大 召回 就 不准 一般 建议 按 语义 段落 切"),
    ("切块策略", "面试 的 时候 一定 要 讲 清楚 你 为什么 这么 切 有 没有 做过 对比 实验 数据 说话 最 有 说服力"),
    ("召回与重排", "第二个 坑 是 只 用 向量 召回 关键词 检索 和 向量 检索 混合 起来 再 加 一个 重排 模型 效果 会 好 很多"),
    ("召回与重排", "重排 模型 不用 很 大 一个 小 的 交叉 编码器 就 够 了 关键 是 要 评估 召回率 和 准确率"),
    ("评估", "第三个 坑 是 没有 评估 集 你 改 了 半天 也 不知道 变好 还是 变坏 至少 准备 五十 条 真实 问题"),
    ("评估", "评估 指标 可以 看 命中率 忠实度 和 答案 相关性 每次 改动 都 跑 一遍 形成 习惯"),
    ("总结", "最后 总结 一下 切块 要 讲 理由 召回 要 混合 加 重排 评估 要 有 数据 这 三点 讲 清楚 面试 基本 稳 了"),
]


def fake_transcript(duration):
    """[{w, t, te, chapter}] covering ``duration`` seconds; sentences separated by 0.6-1.2 s pauses."""
    words, t, k = [], 0.4, 0
    while t < duration - 1:
        chapter, sent = CORPUS[k % len(CORPUS)]
        for w in sent.split():
            te = t + 0.16 + 0.07 * len(w)
            if te > duration:
                break
            words.append(dict(w=w, t=round(t, 2), te=round(te, 2), chapter=chapter))
            t = te + 0.06
        t += 0.6 + (k % 3) * 0.3
        k += 1
    return words


