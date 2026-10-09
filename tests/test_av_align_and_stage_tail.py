"""loudnorm keeps audio exactly as long as the picture; a failing stage keeps its stderr, not progress bars."""
import shutil
import subprocess
import sys

import pytest

from vstudio import audio, media
from vstudio.project import build

pytestmark = pytest.mark.skipif(shutil.which("ffmpeg") is None, reason="needs ffmpeg")


def _clip(path, vdur=3.0, adur=2.9):
    subprocess.run(["ffmpeg", "-v", "error", "-y", "-f", "lavfi", "-i", f"testsrc=size=320x180:rate=30:d={vdur}",
                    "-f", "lavfi", "-i", f"sine=frequency=440:sample_rate=48000:d={adur}",
                    "-c:v", "mpeg4", "-c:a", "aac", path], check=True)


def test_loudnorm_output_audio_matches_video(tmp_path):
    src, dst = str(tmp_path / "in.mp4"), str(tmp_path / "out.mp4")
    _clip(src)
    audio.loudnorm_2pass(src, dst, lufs=-14)
    vd = media.ffprobe_value(dst, "stream=duration", stream="v:0", cast=float)
    ad = media.ffprobe_value(dst, "stream=duration", stream="a:0", cast=float)
    assert abs(vd - ad) < 0.03, (vd, ad)


def test_stage_error_keeps_stderr_over_progress(tmp_path):
    script = tmp_path / "noisy.py"
    script.write_text(
        "import sys\n"
        "for i in range(5000):\n"
        "    print(f'  ████████░░  {i % 100}%  Encoding frame {i}/5000')\n"
        "    print('@hf-progress {\"code\":\"encode\",\"done\":%d}' % i)\n"
        "sys.stderr.write('Error opening output out/promo.loud.mp4: No such file or directory\\n')\n"
        "sys.exit(1)\n")
    env = build.Env.__new__(build.Env)
    env.item_dir = str(tmp_path)
    env.path = lambda name: str(tmp_path / name)
    with pytest.raises(RuntimeError) as ei:
        build.Env.run(env, [sys.executable, str(script)])
    msg = str(ei.value)
    assert "No such file or directory" in msg
    assert "@hf-progress" not in msg and "Encoding frame" not in msg
