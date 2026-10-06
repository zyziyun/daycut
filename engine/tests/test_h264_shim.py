"""The libx264 -> platform encoder rewrite used with the bundled LGPL ffmpeg (engine/runtime_shim)."""
import os
import shutil
import subprocess
import sys
import tempfile
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
SHIM = os.path.join(os.path.dirname(HERE), "runtime_shim")
sys.path.insert(0, SHIM)

import sitecustomize as shim  # noqa: E402

CMD = ["ffmpeg", "-y", "-i", "in.mp4", "-c:v", "libx264", "-profile:v", "high", "-pix_fmt", "yuv420p",
       "-preset", "medium", "-crf", "18", "-tune", "film", "-c:a", "aac", "out.mp4"]


class RewriteTest(unittest.TestCase):
    def test_noop_without_encoder(self):
        self.assertIs(shim.rewrite(CMD, encoder=""), CMD)
        self.assertIs(shim.rewrite(CMD, encoder="libx264"), CMD)

    def test_noop_for_other_commands(self):
        cmd = ["ffprobe", "-c:v", "libx264"]
        self.assertIs(shim.rewrite(cmd, encoder="h264_videotoolbox"), cmd)
        cmd = ["ffmpeg", "-i", "a", "-c:v", "libvpx-vp9", "-crf", "30", "b.webm"]
        self.assertIs(shim.rewrite(cmd, encoder="h264_videotoolbox"), cmd)
        self.assertEqual(shim.rewrite("ffmpeg -c:v libx264", encoder="h264_mf"), "ffmpeg -c:v libx264")

    def test_videotoolbox_arm64(self):
        out = shim.rewrite(CMD, encoder="h264_videotoolbox", machine="arm64")
        self.assertNotIn("libx264", out)
        for gone in ("-preset", "-tune", "-crf"):
            self.assertNotIn(gone, out)
        i = out.index("h264_videotoolbox")
        self.assertEqual(out[i + 1:i + 5], ["-allow_sw", "1", "-q:v", "65"])
        self.assertIn("-profile:v", out)
        self.assertEqual(out[-1], "out.mp4")

    def test_videotoolbox_intel_uses_bitrate(self):
        out = shim.rewrite(CMD, encoder="h264_videotoolbox", machine="x86_64")
        self.assertIn("-b:v", out)
        self.assertNotIn("-q:v", out)

    def test_media_foundation(self):
        out = shim.rewrite(["/x/ffmpeg.exe", *CMD[1:]], encoder="h264_mf", machine="")
        self.assertIn("h264_mf", out)
        self.assertNotIn("-profile:v", out)
        self.assertEqual(out[out.index("-pix_fmt") + 1], "nv12")
        self.assertEqual(out[out.index("-b:v") + 1], "14M")

    def test_vcodec_alias_and_crf_mapping(self):
        out = shim.rewrite(["ffmpeg", "-i", "a", "-vcodec", "libx264", "-crf", "34", "b.mp4"], encoder="h264_videotoolbox", machine="arm64")
        self.assertEqual(out[out.index("-q:v") + 1], "30")


@unittest.skipUnless(shutil.which("ffmpeg") and sys.platform == "darwin", "needs ffmpeg with VideoToolbox (macOS)")
class LiveTest(unittest.TestCase):
    def test_subprocess_is_patched(self):
        """A libx264 command run via subprocess in a fresh interpreter succeeds with VideoToolbox."""
        tmp = tempfile.mkdtemp()
        out = os.path.join(tmp, "o.mp4")
        code = ("import subprocess; subprocess.run(['ffmpeg','-v','error','-y','-f','lavfi','-i','testsrc=size=320x240:rate=10',"
                f"'-t','1','-c:v','libx264','-preset','veryfast','-crf','20','-pix_fmt','yuv420p',{out!r}], check=True)")
        env = dict(os.environ, PYTHONPATH=SHIM, DESK_H264_ENCODER="h264_videotoolbox")
        subprocess.run([sys.executable, "-c", code], env=env, check=True)
        probe = subprocess.run(["ffprobe", "-v", "error", "-select_streams", "v:0", "-show_entries", "stream=codec_name",
                                "-of", "csv=p=0", out], capture_output=True, text=True).stdout.strip()
        self.assertEqual(probe, "h264")


if __name__ == "__main__":
    unittest.main()
