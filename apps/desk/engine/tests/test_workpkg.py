"""Multi-platform package of a work folder (workpkg.py): clips x platforms -> per-platform folders with the right
version, cover and adapted copy, structured checks, a manifest whose code the desk's gate recomputes, originals
untouched; and the client label of a project (agency mode)."""
import os
import sys
import unittest
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import _isolate  # noqa: E402,F401

from desk_engine import workpkg as WP  # noqa: E402
from desk_engine.common import BadRequest  # noqa: E402
from desk_engine.real import verify_manifest  # noqa: E402
from test_v04 import Fixture  # noqa: E402


class WorkPackageTest(Fixture):
    def setUp(self):
        super().setUp()
        from desk_engine import outputs as OU
        # the fixture's files are empty: give them the sizes real masters have (3:4 master, 9:16 version)
        self.pp = mock.patch.object(OU, "probe", lambda p: dict(w=1080, h=1920 if "9x16" in p else 1440, duration=42.0)
                                    if p.endswith(".mp4") else {})
        self.pp.start()
        self.addCleanup(self.pp.stop)
        self.p = WP.WorkPackages(os.path.join(self.root, "desk"), self.h, self.o)

    def test_package_platforms_files_checks_and_code(self):
        self.assertTrue(self.p.owns(self.item))
        self.assertEqual(self.p.manifest(self.item)["manifest"], None)
        before = sorted(os.listdir(os.path.join(self.d, "final")))
        r = self.p.package(self.item, dict(clips=["A_换圈子"], platforms=["xiaohongshu", "douyin", "x", "instagram"],
                                           start="2026-10-08", times=["12:00"],
                                           times_by_platform={"x": ["09:00"]}))
        self.assertEqual(r["items"], 4)
        m = self.p.manifest(self.item)
        man = m["manifest"]
        self.assertTrue(m["verify"]["ok"])
        self.assertEqual(verify_manifest(man)["code"], man["confirmation_code"])
        keys = {i["platform"]: i for i in man["items"]}
        self.assertEqual(set(keys), {"xiaohongshu-vertical", "douyin-vertical", "x-vertical", "instagram-reels"})
        self.assertTrue(keys["douyin-vertical"]["files"]["video"].endswith("video.mp4"))
        self.assertEqual(keys["x-vertical"]["time"], "09:00")              # the account's default time
        self.assertEqual(keys["douyin-vertical"]["time"], "12:00")
        for i in man["items"]:
            codes = [c["code"] for c in i["checks"]]
            self.assertIn("ai-label", codes)
            for f in i["files"].values():
                self.assertTrue(os.path.exists(os.path.join(m["dir"], f)))
        self.assertIn("no-title", [c["code"] for c in keys["x-vertical"]["checks"]])
        with open(os.path.join(m["dir"], keys["x-vertical"]["files"]["post"]), encoding="utf-8") as fh:
            post_x = fh.read()
        self.assertTrue(post_x.startswith("同一个行业待越久，思路越窄"))
        # the originals are untouched (the package holds clones / copies, never the files themselves)
        self.assertEqual(sorted(os.listdir(os.path.join(self.d, "final"))), before)
        # any edit of the manifest breaks the code
        man["items"][0]["time"] = "23:00"
        self.assertFalse(verify_manifest(man)["ok"])

    def test_refusals(self):
        for body in (dict(clips=[], platforms=["douyin"]), dict(clips=["A_换圈子"], platforms=["myspace"]),
                     dict(clips=["nope"], platforms=["douyin"]), dict(clips=["A_换圈子"], platforms=["douyin"], times=["7pm"])):
            with self.assertRaises((BadRequest, KeyError)):
                self.p.package(self.item, body)

    def test_version_choice_and_copy_limits(self):
        files = [dict(path="/a.mp4", aspect="原尺寸", w=1080, h=1440), dict(path="/a_9x16.mp4", aspect="9:16", w=1080, h=1920)]
        self.assertEqual(WP.pick_version(files, WP._Prof("xiaohongshu"))[:2], ("vertical", files[0]))
        self.assertEqual(WP.pick_version(files, WP._Prof("douyin"))[:2], ("vertical", files[1]))
        o, f, chk = WP.pick_version(files, WP._Prof("youtube"))
        self.assertEqual((chk["code"], chk["want"]), ("aspect", "16:9"))
        t, b, tags, checks = WP.adapt_copy("instagram", WP._Prof("instagram"),
                                           dict(title="标题", body="正文", tags=[f"t{i}" for i in range(8)]), "")
        self.assertEqual(len(tags), 5)
        self.assertIn("hashtags-over", [c["code"] for c in checks])
        t, b, tags, checks = WP.adapt_copy("xiaohongshu", WP._Prof("xiaohongshu"),
                                           dict(title="这是一个特别特别特别特别特别特别长的标题啊", body="x", tags=[]), "")
        self.assertIn("title-over", [c["code"] for c in checks])
        self.assertIn("标签：a, b", WP.post_md("bilibili", "T", "B", ["a", "b"]))

    def test_new_platforms_youtube_formats_and_copy_rules(self):
        self.assertEqual(WP.PLATFORMS[:3], ("youtube", "youtube-shorts", "tiktok"))
        self.assertEqual(WP.PLATFORMS[-2:], ("dailymotion", "kwai"))
        for n in WP.PLATFORMS:
            pr = WP._Prof(n)
            self.assertIn(pr.default, pr.orient, n)
            self.assertIn(pr.links, ("clickable", "not-clickable", "link-field", "avoid"), n)
        vert = [dict(path="/a_9x16.mp4", aspect="9:16", w=1080, h=1920)]
        horz = [dict(path="/a.mp4", aspect="16:9", w=1920, h=1080)]
        _, _, chk = WP.pick_version(vert, WP._Prof("youtube"))
        self.assertEqual(WP.youtube_check("youtube", chk)["code"], "yt-vertical-only")
        _, _, chk = WP.pick_version(horz, WP._Prof("youtube-shorts"))
        self.assertEqual(WP.youtube_check("youtube-shorts", chk)["code"], "shorts-horizontal")
        self.assertEqual(WP.pick_version(vert, WP._Prof("youtube-shorts"))[2], None)
        # Reddit: title required, no hashtags, subreddit reminder; Pinterest link field; Instagram link not clickable
        t, b, tags, checks = WP.adapt_copy("reddit", WP._Prof("reddit"), dict(body="b #x", tags=["ai"]), "")
        codes = [c["code"] for c in checks]
        self.assertEqual(tags, [])
        self.assertTrue({"title-required", "no-hashtags", "subreddit"} <= set(codes))
        _, _, _, checks = WP.adapt_copy("pinterest", WP._Prof("pinterest"), dict(title="t", body="see example.com"), "")
        self.assertIn("link-field", [c["code"] for c in checks])
        _, _, _, checks = WP.adapt_copy("instagram", WP._Prof("instagram"), dict(body="https://a.co"), "")
        self.assertIn("link-not-clickable", [c["code"] for c in checks])
        _, _, _, checks = WP.adapt_copy("linkedin", WP._Prof("linkedin"), dict(title="T", body="https://a.co"), "")
        self.assertNotIn("link-not-clickable", [c["code"] for c in checks])
        self.assertIn("no-title", [c["code"] for c in checks])
        self.assertTrue(WP.post_md("weibo", "标题标题标题", "正文", ["话题"]).rstrip().endswith("#话题#"))

    def test_package_youtube_long_and_shorts(self):
        r = self.p.package(self.item, dict(clips=["A_换圈子"], platforms=["youtube", "youtube-shorts", "reddit"],
                                           start="2026-10-08"))
        self.assertEqual(r["items"], 3)
        man = self.p.manifest(self.item)["manifest"]
        by = {i["platform"]: i for i in man["items"]}
        self.assertIn("youtube-horizontal", by)
        self.assertIn("yt-vertical-only", [c["code"] for c in by["youtube-horizontal"]["checks"]])
        self.assertIn("youtube-shorts-vertical", by)
        self.assertNotIn("shorts-horizontal", [c["code"] for c in by["youtube-shorts-vertical"]["checks"]])

    def test_client_label_agency_mode(self):
        self.h.set_client(self.d, "Acme")
        row = next(r for r in self.h.list()["items"] if r["dir"] == self.d)
        self.assertEqual(row["client"], "Acme")
        self.h.set_client(self.d, "")
        row = next(r for r in self.h.list()["items"] if r["dir"] == self.d)
        self.assertIsNone(row["client"])


if __name__ == "__main__":
    unittest.main()
