"""One caption line-breaker for every script (vstudio.subs.caption_chunks / balanced_wrap / split_two / join_caption):
English never splits inside a word ("anywa / y", "Every index mak / es writes slower" in the English demo batch),
CJK splits by character with no line starting on closing punctuation, mixed text keeps latin runs whole."""
import re
import sys
from pathlib import Path

from vstudio import draw
from vstudio import subs as S
from vstudio.batch import lfsplit as LS

ROOT = Path(__file__).resolve().parents[1]

EN = ("I think that's the interviewer question for anyway, if you query the user anyway on every request "
      "then why are you using a JWT at all instead of a session cookie with Redis behind it")
ZH = "我们用这个模型做了一个非常长的测试，然后把结果发到了小红书上面，大家觉得效果怎么样呢？我觉得还挺好的。"
MIX = "今天我们用Claude Code和HyperFrames做了一个讲解视频，整个流程只用了十分钟，而且export也很快"


def _words(s):
    return re.findall(r"[A-Za-z0-9'’]+", s)


def test_english_chunks_never_split_a_word():
    for width in (6, 9, 12, 16, 22, 30):
        chunks = S.caption_chunks(EN, width, max_lines=2)
        assert len(chunks) > 1 or S.text_width(EN) <= 2 * width
        assert S.join_caption(chunks) == EN                      # nothing lost, spaces kept at the seams
        for c in chunks:
            assert all(w in _words(EN) for w in _words(c)), (width, c)
            assert "anywa" not in c.replace("anyway", "")
            assert not c.startswith((",", ".", "?"))


def test_chinese_chunks_by_character_with_no_break_punctuation():
    for width in (5, 8, 10, 14):
        chunks = S.caption_chunks(ZH, width, max_lines=2)
        assert "".join(chunks) == ZH
        for c in chunks:
            for ln in S.balanced_wrap(c, width):
                assert ln[0] not in "，。、！？；：”’）》」』】,.!?;:)"
                assert S.text_width(ln) <= width + 1                  # a glued closing mark may hang


def test_mixed_text_keeps_latin_runs_whole():
    for width in (6, 8, 10, 12):
        lines = S.balanced_wrap(MIX, width)
        assert S.join_caption(lines).replace(" ", "") == MIX.replace(" ", "")
        flat = " ".join(lines)
        for w in ("Claude", "HyperFrames", "export"):
            assert w in flat, (width, lines)
        chunks = S.caption_chunks(MIX, width, max_lines=2)
        assert "Claude Code" in S.join_caption(chunks)


def test_accented_and_long_words_stay_whole():
    assert S.split_two("café crème brûlée au chocolat") == ["café crème brûlée", "au chocolat"]
    assert S.caption_chunks("Supercalifragilisticexpialidocious", 4) == ["Supercalifragilisticexpialidocious"]
    f = draw.load_font("cjk-bold", 80)
    assert draw.wrap("Authentication everywhere", f, 200) == ["Authentication", "everywhere"]   # overflow, no "Authenticati / on"
    assert not draw.fits(["Authentication"], f, 200)


def test_join_caption_seams():
    assert S.join_caption(["any", "way"]) == "any way"
    assert S.join_caption([" anyway", "so we ", "", "start."]) == "anyway so we start."
    assert S.join_caption(["我们用", "Claude Code", "做了视频"]) == "我们用Claude Code做了视频"
    assert S.join_caption(["Claude", "Code做了"]) == "Claude Code做了"
    assert S.join_caption(["hello", ", world"]) == "hello, world"


def test_cover_title_uses_the_shared_breaker():
    assert LS._title_parts("Every index makes writes slower") == ("Every index makes", "writes slower")
    assert LS._title_parts("JWT payloads are encoded not encrypted") == ("JWT payloads are", "encoded not encrypted")
    assert LS._title_parts("一行代码搞定Postgres全文搜索") == ("一行代码搞定", "Postgres全文搜索")
    assert LS._title_parts("If you query the user anyway, why JWT?") == ("If you query the user anyway", "why JWT?")
    for t in ("Ask AI to fix a slow query then verify with EXPLAIN", "The honest interview answer about MySQL 8"):
        a, b = LS._title_parts(t)
        assert f"{a} {b}" == t and all(w in t.split() for w in (a + " " + b).split())


def test_spoken_hook_lines_join_english_with_spaces():
    tl = [dict(kind="clip", hook=True, final_t0=0.0, t0=0.0, t1=4.0, speed=1.0)]
    cues = [dict(start=0.0, end=2.0, text="Every index you add"), dict(start=2.0, end=4.0, text="makes writes slower")]
    out = LS.spoken_hook_lines(tl, cues)
    assert out[0] == ["Every index you add", "makes writes slower"]
    tl[0].pop("hook_lines")
    one = [dict(start=0.0, end=4.0, text="Every index you add makes writes slower")]
    assert LS.spoken_hook_lines(tl, one)[0] == ["Every index you add", "makes writes slower"]


def _vertical():
    d = str(ROOT / "workflows" / "longform-to-short" / "scripts")
    sys.path.insert(0, d)
    try:
        import _vertical as V
        return V
    finally:
        sys.path.remove(d)


def test_vertical_relayout_splits_english_on_words_only():
    from vstudio import platform as PF
    V = _vertical()
    prof = PF.parse_targets(["tiktok"])[0]
    cue = S.Cue(0.0, 9.0, EN)
    out = V.relayout_cues([cue], prof)
    assert len(out) > 1
    assert S.join_caption([c.text for c in out]) == EN
    for c in out:
        assert all(w in _words(EN) for w in _words(c.text)), c.text
        assert len(c.text) <= 2 * prof.caption["max_chars_en"] + 2
    assert abs(out[-1].end - 9.0) < 1e-6
