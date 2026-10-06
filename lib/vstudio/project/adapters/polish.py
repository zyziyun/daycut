"""polish: the speed question of workflows/polish (propose 1.2x for shorts, ask before applying)."""
from vstudio.batch.util import sha1_json

SHORT_PLATFORMS = ("douyin", "tiktok", "youtube-shorts", "xiaohongshu")


def probe(env):
    from vstudio import media
    src = env.params.get("source")
    info = media.probe(src)
    w, h, dur = info.get("width") or 0, info.get("height") or 0, float(info.get("duration") or 0)
    plats = [p.split(":")[0] for p in env.params.get("platforms") or []]
    short = (h > w and dur < 180) or any(p in SHORT_PLATFORMS for p in plats)
    try:
        from vstudio.config import persona
        body = float((persona().get("speed") or {}).get("body") or 1.2)
    except Exception:  # noqa: BLE001
        body = 1.2
    return dict(width=w, height=h, duration=round(dur, 3), short=short, suggest=body if short else 1.0, files=[])


def speed_payload(env, cp):
    pr = env.inputs.get(cp["after"]) or {}
    given = env.params.get("speed")
    opts = [dict(speed=s, duration=round((pr.get("duration") or 0) / s, 1)) for s in (1.0, 1.1, 1.2, 1.3)]
    return dict(options=opts, probe=pr, digest=sha1_json(opts)[:16],
                default=dict(speed=pr.get("suggest", 1.0)), skip=given is not None,
                skip_reason="speed set in the params", previews=[dict(kind="video", path=env.params.get("source"))])


def speed_apply(a):
    s = float((a.value or {}).get("speed") or 1.0)
    if s > 1.4:
        a.payload.setdefault("warnings", []).append("above 1.4x dense Chinese speech gets hard to follow")
    return dict(params=dict(speed=s))
