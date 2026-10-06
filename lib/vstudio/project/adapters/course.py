"""longform-course: payloads over the workflow's own review files (cleanup_review.ep<N>.md, qa mosaics)."""
import glob
import os
import re

from vstudio.batch.util import sha1_json

from ..build import file_sha


def filler_payload(env, cp):
    sheets = sorted(glob.glob(os.path.join(env.item_dir, "work", "cleanup_review.ep*.md")))
    opts = []
    for s in sheets:
        mo = re.search(r"ep(\d+)", os.path.basename(s))
        with open(s, encoding="utf-8") as f:
            txt = f.read()
        n_confirm = len(re.findall(r"CONFIRM", txt))
        opts.append(dict(episode=mo.group(1) if mo else "1", sheet=s, confirm_rows=n_confirm, sha=file_sha(s)))
    pending = [o for o in opts if o["confirm_rows"]]
    return dict(options=opts, default=dict(reply={}), skip=not pending,
                skip_reason="no CONFIRM rows in the review sheets", digest=sha1_json(opts)[:16],
                previews=[dict(kind="markdown", path=o["sheet"]) for o in opts])


def filler_apply(a):
    return dict(params=dict(cleanup_reply_map={str(k): v for k, v in ((a.value or {}).get("reply") or {}).items()}))


def mosaic_payload(env, cp):
    ms = sorted(glob.glob(os.path.join(env.item_dir, "work", "qa", "mosaic_*.jpg")))
    return dict(options=[dict(path=m, sha=file_sha(m)) for m in ms], default=None,
                previews=[dict(kind="image", path=m) for m in ms])
