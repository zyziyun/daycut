"""Settings › Watermark: the engine's own watermark settings (``vstudio.watermark``: ``$VSTUDIO_HOME/watermark.json``,
shared with the CLI skill), the logo she drops, and previews drawn by the same code the exports use.

    GET  /api/watermark[?previews=0]    {settings, configured, default_on, logo, previews {"9:16", "16:9"}}
    POST /api/watermark                 {patch}  any of kind, text, style, color, position, size, opacity, margin,
                                        default, platforms -> the same document
    POST /api/watermark/logo            {path}  a PNG / JPG she picked or dropped: copied in, kind image

Nothing here is a stand-in: the previews are ``vstudio.watermark.preview`` over a sample frame of the platform
profile, placed exactly as an export places it.
"""
import os

from .common import BadRequest, need

PREVIEW_ASPECTS = ("9:16", "16:9")
PREVIEW_HEIGHT = 480


def _wm():
    try:
        from vstudio import watermark as WM
    except ImportError as e:                             # an engine older than the watermark module
        raise BadRequest(f"this engine has no watermark support ({e})") from None
    return WM


class Watermark:
    def doc(self, previews=True):
        WM = _wm()
        cfg = WM.load()
        out = dict(settings={k: v for k, v in cfg.items() if k != "image"}, configured=WM.configured(cfg),
                   default_on=WM.wants(cfg), logo=os.path.basename(cfg.get("image") or "") or None)
        if previews:
            out["previews"] = {a: WM.preview_data_url(cfg, a, PREVIEW_HEIGHT) for a in PREVIEW_ASPECTS}
        return out

    def update(self, body):
        WM = _wm()
        need(isinstance(body, dict) and isinstance(body.get("patch"), dict), "patch: an object of settings")
        patch = dict(body["patch"])
        need("image" not in patch, "image: send the logo to /api/watermark/logo")
        try:
            WM.save(patch)
        except ValueError as e:
            raise BadRequest(str(e)) from None
        return self.doc()

    def logo(self, body):
        WM = _wm()
        p = (body or {}).get("path") if isinstance(body, dict) else None
        need(isinstance(p, str) and os.path.isabs(p) and "\0" not in p and len(p) < 4096, "path: an absolute path")
        need(p.lower().endswith(WM.IMAGE_EXT), "logo: a .png / .jpg / .webp image")
        try:
            stored = WM.import_logo(p)
            WM.save(dict(kind="image", image=stored))
        except ValueError as e:
            raise BadRequest(str(e)) from None
        return self.doc()

    def route(self, method, parts, body, query=None):
        """None = not mine. ``?previews=0``: the settings without the preview images (the export card)."""
        if parts == ["watermark"]:
            if method == "GET":
                return self.doc(previews=((query or {}).get("previews") or ["1"])[0] != "0")
            if method == "POST":
                return self.update(body)
        if parts == ["watermark", "logo"] and method == "POST":
            return self.logo(body)
        return None
