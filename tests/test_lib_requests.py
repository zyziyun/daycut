"""Regression tests for the Phase 2c shared-library requests (bugs + features collected in each
workflow's PORT_NOTES "Lib requests"). Synthetic media only (ffmpeg lavfi); no network, ASR or TTS."""
import json
import os
import pathlib
import subprocess
import sys

import numpy as np
import pytest
from PIL import Image

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1] / "lib"))

from vstudio import asr, audio, cover, cut, draw, face, media, overlays, subs, tts  # noqa: E402

pytestmark = pytest.mark.skipif(not __import__("shutil").which("ffmpeg"), reason="ffmpeg not installed")


def ff(*args):
    media.run(["ffmpeg", "-y", *map(str, args)])


def nframes(p):
    r = media.run(["ffprobe", "-v", "error", "-count_frames", "-select_streams", "v", "-show_entries",
                   "stream=nb_read_frames", "-of", "csv=p=0", p], capture=True)
    return int(r.stdout_text.strip())


def frame_ids(p, side=64):
    """Frame index encoded as luma 16 + 2*(N mod 100) (TV range, read straight from the Y plane)."""
    r = subprocess.run([media.ffmpeg_bin(), "-v", "error", "-i", p, "-f", "rawvideo", "-pix_fmt", "yuv420p", "-"],
                       capture_output=True, check=True).stdout
    y = np.frombuffer(r, np.uint8).reshape(-1, side * side * 3 // 2)[:, :side * side].mean(1)
    return np.round((y - 16) / 2).astype(int)


def rgb_at(p, t, w, h):
    r = subprocess.run([media.ffmpeg_bin(), "-v", "error", "-ss", str(t), "-i", p, "-frames:v", "1", "-f", "rawvideo",
                        "-pix_fmt", "rgb24", "-"], capture_output=True, check=True).stdout
    return np.frombuffer(r, np.uint8).reshape(h, w, 3).astype(int)


@pytest.fixture(scope="session")
def tmp(tmp_path_factory):
    return tmp_path_factory.mktemp("req")


@pytest.fixture(scope="session")
def av(tmp):
    p = tmp / "av.mp4"
    ff("-f", "lavfi", "-i", "testsrc2=s=320x180:r=30", "-f", "lavfi", "-i", "sine=f=300:r=48000", "-t", "6",
       "-c:v", "libx264", "-preset", "ultrafast", "-pix_fmt", "yuv420p", "-c:a", "aac", "-shortest", p)
    return str(p)


@pytest.fixture(scope="session")
def silent_portrait(tmp):
    p = tmp / "silent.mp4"
    ff("-f", "lavfi", "-i", "testsrc2=s=180x320:r=30", "-t", "3", "-c:v", "libx264", "-preset", "ultrafast",
       "-pix_fmt", "yuv420p", p)
    return str(p)


# =========================================================================== bugs
def test_progress_fill_animates(tmp):
    """overlays.progress_static: the fill grows with t (the old drawbox `w='..t..'` never moved)."""
    pb = overlays.progress_static([(0, 2, "A"), (2, 4, "B")], 4.0, width=640, y=300, x0=40, bar_w=560)
    out = str(tmp / "pb.mp4")
    media.run(["ffmpeg", "-y", "-f", "lavfi", "-i", "color=c=black:s=640x360:r=30:d=4", "-vf", pb["fill"],
               "-c:v", "libx264", "-crf", "0", "-preset", "ultrafast", out])
    ends = []
    for t in (0.5, 2.0, 3.5):
        band = rgb_at(out, t, 640, 360)[296:316]
        red = np.nonzero(((band[..., 0] - band[..., 1]) > 40).any(0))[0]
        assert len(red) and red.min() <= 42
        ends.append(red.max())
    exp = [40 + 560 * t / 4 for t in (0.5, 2.0, 3.5)]
    assert all(abs(e - x) < 8 for e, x in zip(ends, exp)), ends
    g = pb["fill_graph"]("[0:v]", "[vbar]", t0=3.0, speed=1.25)
    assert g.startswith("color=") and g.endswith("[vbar]") and "(t-3.000)/3.200" in g


def test_cut_segments_survives_timestamp_jitter(tmp):
    """cut.cut_segments: ~2 ms pts jitter (concat joins) must not drop/shift a frame."""
    clean, jit = str(tmp / "ids.mp4"), str(tmp / "ids_jit.mp4")
    ff("-f", "lavfi", "-i", r"nullsrc=s=64x64:r=30,geq=lum='16+mod(N\,100)*2':cb=128:cr=128", "-t", "6",
       "-c:v", "libx264", "-crf", "0", "-preset", "ultrafast", "-pix_fmt", "yuv420p", "-video_track_timescale", "1000",
       clean)
    ff("-i", clean, "-c", "copy", "-bsf:v", r"setts=pts=PTS-2*mod(N\,2):dts=DTS-2*mod(N\,2)",
       "-video_track_timescale", "1000", jit)
    out = str(tmp / "ids_cut.mp4")
    cut.cut_segments(jit, [(61 / 30, 90 / 30), (121 / 30, 150 / 30)], out, fps=30)
    ids = frame_ids(out)
    assert len(ids) == 58
    assert list(ids[:3]) == [61, 62, 63] and list(ids[28:31]) == [89, 21, 22] and ids[-1] == 49


def test_balanced_wrap_keeps_punctuation_outside_highlight():
    lines = subs.balanced_wrap("我们就在**这里**，开始今天的第一段旅程吧朋友们", 10)
    assert lines[0].endswith("**这里**，") and "**这里，**" not in "".join(lines)
    lines = subs.balanced_wrap("在【这里】，开始今天的第一段旅程吧朋友们大家好", 10)
    assert "【这里】，" in lines[0]
    assert "“**你好**”" in "".join(subs.balanced_wrap("他说“**你好**”然后走了很远很远的路才到家门口", 10))
    # a highlight that really contains the punctuation keeps it
    assert "**好，**" in "".join(subs.balanced_wrap("大家**好，**今天我们来聊一聊视频剪辑的那些事情吧", 10))


def test_chapter_card_scales_and_centres():
    for W, H in ((1920, 1080), (1080, 1920), (3840, 2160)):
        im = overlays.chapter_card(2, 5, "核心方法：三步剪出短视频", size=(W, H), accent="#2DD4BF")
        a = np.asarray(im.convert("RGB")).astype(int)
        ink = (np.abs(a - a[0, 0]).sum(2) > 60)
        rows, cols = np.nonzero(ink.any(1))[0], np.nonzero(ink.any(0))[0]
        top, bot = rows.min(), rows.max()
        assert abs((top + bot) / 2 - H / 2) < 0.08 * H                   # block centred vertically
        assert abs((cols.min() + cols.max()) / 2 - W / 2) < 0.1 * W      # ... and horizontally
        assert (bot - top) > 0.17 * H                                    # big type, not a tiny block
    teal = np.asarray(overlays.chapter_card(1, 3, "X", accent="#2DD4BF").convert("RGB")).reshape(-1, 3)
    assert ((np.abs(teal - (45, 212, 191)).sum(1)) < 30).any()


# =========================================================================== cut.xfade_assemble
def test_xfade_assemble_video_only_fit_transition(tmp, av, silent_portrait):
    asm = cut.xfade_assemble([dict(input=0, start=0, end=2), dict(input=1, start=0, end=2, fit="blur"),
                              dict(input=0, start=3, end=5, vf="eq=saturation=0")],
                             xfade=0.5, size="320:180", audio=False, transition=["wipeleft", "dissolve"],
                             mute_pad=False)
    assert asm.aout is None and ":a]" not in asm.graph and "transition=wipeleft" in asm.graph
    assert "transition=dissolve" in asm.graph and "gblur" in asm.graph
    out = str(tmp / "vo.mp4")
    cut.render_assembly(asm, [av, silent_portrait], out, post_video=f"fade=t=out:st={asm.total - 0.5}:d=0.5")
    info = media.probe(out)
    assert not info["has_audio"] and (info["w"], info["h"]) == (320, 180)
    assert nframes(out) == round(asm.total * 30)
    assert rgb_at(out, asm.total - 0.04, 320, 180).mean() < 20          # post_video fade to black


def test_xfade_assemble_clone_pads(tmp, av):
    pcs = [(4.5, 6.0), (0.0, 3.0), (5.2, 6.0)]
    both = cut.xfade_assemble(pcs, xfade=0.4, mute_pad="both", src_durations=[6.0], speeds=1.2)
    cl = cut.xfade_assemble(pcs, xfade=0.4, mute_pad="clone", src_durations=[6.0], speeds=1.2)
    # clamped pads vs full pads: the body at 0 and the hook at the source end get clone frames
    assert both.pieces[1]["s0"] == 0.0 and cl.pieces[1]["s0"] < 0
    assert cl.pieces[0]["s1"] > 6.0 and "tpad=start=12:start_mode=clone" in cl.graph
    assert "adelay=delays=19200S" in cl.graph
    assert cl.total > both.total
    out = str(tmp / "clone.mp4")
    cut.render_assembly(cl, [av], out)
    assert abs(nframes(out) - round(cl.total * 30)) <= 1
    # body time 0 maps to where its first real frame plays (after the cloned pre-roll)
    assert cl.timemap.to_final(0.0, tag=None) == pytest.approx(cl.offsets[1] + 0.4, abs=1 / 30)


def test_xfade_assemble_seek_and_chunks_match_plan(tmp, av):
    pcs = [(0.2 * k, 0.2 * k + 0.6) for k in range(9)]
    plain = cut.xfade_assemble(pcs, xfade=0.1, mute_pad=False)
    sk = cut.xfade_assemble(pcs, xfade=0.1, mute_pad=False, seek=True)
    assert len(sk.input_specs) == 9 and sk.offsets == plain.offsets and sk.total == plain.total
    lossless = ["-c:v", "libx264", "-crf", "0", "-preset", "ultrafast", "-an"]
    a, b = str(tmp / "plain.mp4"), str(tmp / "seek.mp4")
    cut.render_assembly(plain, [av], a, args=lossless)
    cut.render_assembly(sk, [av], b, args=lossless)
    r = media.run(["ffmpeg", "-i", a, "-i", b, "-lavfi", "psnr", "-f", "null", "-"], capture=True, quiet=False)
    assert "average:inf" in r.stderr_text
    both = cut.xfade_assemble(pcs, xfade=0.1, mute_pad="both")
    c = str(tmp / "chunk.mp4")
    cut.render_assembly(both, [av], c, chunk=3, post_audio="volume=0.5")
    assert nframes(c) == round(both.total * 30)
    assert media.probe(c)["has_audio"]


def test_timemap_with_item():
    tm = cut.TimeMap.from_segments([(1, 3), (5, 8)])
    assert tm.to_final(6.0, with_item=True) == (pytest.approx(3.0), 1)
    assert tm.to_final(4.0, "fwd", with_item=True) == (pytest.approx(2.0), 1)
    assert tm.to_final(4.0, with_item=True) == (None, None)


# =========================================================================== audio
def test_loop_bed_and_place_clips(tmp):
    src = str(tmp / "mus.wav")
    ff("-f", "lavfi", "-i", "sine=f=220:r=44100", "-t", "10", "-ac", "1", src)
    bed = audio.loop_bed(src, str(tmp / "bed.wav"), 25, xfade=3)
    i = media.probe(bed)
    assert abs(i["duration"] - 25) < 0.01 and i["channels"] == 2 and i["sample_rate"] == 48000
    assert abs(audio.measure_loudness(bed)["input_i"] + 30) < 1.0
    x, _ = audio.read_wav(bed)
    seam = np.abs(x[int(7.5 * 48000):int(8.5 * 48000)]).max()
    assert seam > 0.5 * np.abs(x[int(4 * 48000):int(5 * 48000)]).max()   # no dip/hole at the loop seam
    with pytest.raises(ValueError):
        audio.loop_bed(src, str(tmp / "x.wav"), 25, xfade=12)
    out = audio.place_clips([(src, 1.0), (src, -9.5, -6), {"path": src, "start": 12, "trim": 1}], 15,
                            str(tmp / "pl.wav"))
    y, _ = audio.read_wav(out)
    assert len(y) == 15 * 48000
    lvl = lambda a, b: np.abs(y[int(a * 48000):int(b * 48000)]).max()
    assert lvl(0.1, 0.4) > 0 and lvl(0.6, 0.9) == 0 and lvl(12.2, 12.8) > 0 and lvl(13.2, 14.8) == 0


def test_rms_envelope_smooth_db():
    x = np.zeros(48000, np.float32); x[20000:28000] = 0.3
    lin, _ = audio.rms_envelope(x, 48000)
    dbs, _ = audio.rms_envelope(x, 48000, smooth_db=True)
    assert lin.shape == dbs.shape and not np.allclose(lin, dbs)
    assert (dbs > -45).sum() < (lin > -45).sum()                       # dB smoothing widens runs less


# =========================================================================== subs / asr / tts
def test_ass_extra_styles_and_srt_trailing_newline(tmp):
    cues = [subs.Cue(0.5, 2.0, "你好【世界】"), subs.Cue(2.0, 3.0, "第二句")]
    p = str(tmp / "s.ass")
    note = subs.ass_style("Note", font_name="X", size=38, back_alpha=0xB0, border_style=3, alignment=8)
    n = subs.ass_write(cues, p, font_name="X", extra_styles=[note, {"name": "Big", "size": 80}],
                       extra_events=[(1.0, 2.5, "勘误：**更正**", "Note")])
    t = open(p, encoding="utf-8").read()
    assert n == 3 and "Style: Note,X,38," in t and "Style: Big,X,80," in t and "&HB0000000" in t
    assert t.index("Style: Note") < t.index("[Events]") and "Dialogue: 1,0:00:01.00,0:00:02.50,Note" in t
    a, b = str(tmp / "a.srt"), str(tmp / "b.srt")
    subs.srt_write(cues, a); subs.srt_write(cues, b, trailing_newline=True)
    assert open(b).read() == open(a).read() + "\n" and open(b).read().endswith("第二句\n\n")


def test_hyperframes_transcript_and_backend(tmp):
    tr = {"words": [{"w": "Hello", "t": 0.1, "te": 0.4}, {"w": "world", "t": 0.5, "te": 0.9}]}
    p = str(tmp / "transcript.json")
    out = asr.to_hyperframes_transcript(tr, p)
    assert out == json.load(open(p)) and out[1] == {"text": "world", "start": 0.5, "end": 0.9, "id": "w1"}
    assert asr.resolve_backend("faster") == "faster"
    assert tts.default_voice("edge") and tts.default_voice("kokoro") and tts.default_voice("openai")


# =========================================================================== media
def test_delivery_args_modes():
    base = media.delivery_args()
    assert "-crf" in base and "-c:a" in base
    vb = media.delivery_args(vbitrate="28M")
    assert "-crf" not in vb and vb[vb.index("-b:v") + 1] == "28000000"
    assert vb[vb.index("-maxrate") + 1] == str(int(28e6 * 1.15)) and "-bufsize" in vb
    none = media.delivery_args(audio=None)
    assert "-an" not in none and "-c:a" not in none
    assert "-an" in media.delivery_args(audio=False)
    vt = media.delivery_args(encoder="videotoolbox", quality=60)
    assert "h264_videotoolbox" in vt and vt[vt.index("-q:v") + 1] == "60" and "-crf" not in vt
    with pytest.raises(ValueError):
        media.delivery_args(encoder="nope")


def test_grab_frame_probe_link(tmp, av):
    j = str(tmp / "f.jpg")
    assert media.grab_frame(av, 1.0, j, quality=2) == j and os.path.getsize(j) > 0
    rot = str(tmp / "rot.mp4")
    media.run(["ffmpeg", "-y", "-display_rotation", "90", "-i", av, "-c", "copy", rot])   # ffmpeg >= 7
    i = media.probe(rot)
    assert abs(i["rotation"]) == 90 and (i["display_w"], i["display_h"]) == (i["h"], i["w"])
    assert (media.probe(av)["display_w"], media.probe(av)["display_h"]) == (320, 180)
    d = str(tmp / "sub" / "linked.mp4")
    assert media.link_or_copy(av, d) == d and os.path.getsize(d) == os.path.getsize(av)
    assert media.link_or_copy(av, d) == d                               # replaces an existing dst


# =========================================================================== cover / draw / overlays
def test_split_cover_keys_and_redpen():
    photo = Image.fromarray(np.tile(np.linspace(0, 255, 800, dtype=np.uint8)[None, :, None], (600, 1, 3)))
    th = np.zeros((200, 400, 3), np.uint8); th[50:150, 100:300] = 200
    base = {"photo": photo, "retouched": True, "face_box": [500, 100, 700, 300], "aspect": "4:3",
            "title": ["标题"], "thumbnail": {"image": th, "crop_px": [100, 50, 300, 150]}}
    a = np.asarray(cover.split_cover(dict(base)))
    b = np.asarray(cover.split_cover(dict(base, fade=60, overlap=120)))
    assert a.shape == (1080, 1440, 3) and not np.array_equal(a, b)
    c = np.asarray(cover.split_cover(dict(base, thumbnail={"image": th, "crop": [100, 50, 300, 150]})))
    assert np.array_equal(a, c)                                         # crop > 1 = pixels
    im = Image.new("RGB", (300, 200), "white")
    out = cover.redpen_ellipse(im, (0.5, 0.5, 0.3, 0.2))
    arr = np.asarray(out).astype(int)
    assert out.size == im.size and ((arr[..., 0] > 180) & (arr[..., 1] < 90)).sum() > 200


def test_draw_star_markup_chip_bilingual():
    assert draw.runs("普通**重点**文本") == [("普通", False), ("重点", True), ("文本", False)]
    assert draw.plain("a**b**c") == "abc"
    f = draw.load_font("cjk-bold", 40)
    assert "".join(draw.wrap("这是**重点**内容，我们一起来看看这个很长的句子", f, 300)).count("重点") == 1
    assert draw.wrap("这是**重点**内容", f, 900) == ["这是【重点】内容"]
    c0 = overlays.chip("标签", "tag")
    c1 = overlays.chip("标签", "tag", radius=0, min_width=400)
    assert c1.width == 400 and c0.width == 230
    assert np.asarray(c1)[0, 0, 3] > 0 and np.asarray(c0)[0, 0, 3] == 0   # square vs rounded corner
    strip = draw.bilingual_layer("你好世界", "Hello world", f, max_w=600)
    one = draw.bilingual_layer("你好世界", "", f)
    assert strip.mode == "RGBA" and strip.height > one.height and strip.width >= one.width


# =========================================================================== face
def test_face_track_helpers():
    assert face.fill_gaps([None, 1, None, 3, None]) == [1, 1, 2.0, 3, 3] and face.fill_gaps([None]) is None
    assert face.ema([0, 1, 1], 0.5) == [0, 0.5, 0.75]
    tr = face.smooth_track([None, 10, 12, None], [5, 5, None, 5], [40, None, 20, 40], [40, 40, 40, 40])
    assert len(tr["cx"]) == 4 and min(tr["w"]) >= 0.9 * np.median(tr["w"]) - 1e-9
    assert face.smooth_track([None], [None], [None], [None]) is None
    pts = np.zeros((478, 2), np.float32); pts[10, 1], pts[152, 1], pts[13, 1], pts[14, 1] = 0, 100, 50, 60
    assert face.mouth_gap(pts) == pytest.approx(0.1)
    t = np.arange(60) * 0.1
    talk = lambda on: list(np.where(on, 0.05 + 0.04 * np.sin(t * 20), 0.05))
    s = {"a": talk(t < 3), "b": talk(t >= 3)}
    s["a"][5] = None
    r = face.talk_labels(s, 0.1)
    assert r["labels"][10] == "a" and r["labels"][50] == "b" and len(r["energy"]["a"]) == 60
