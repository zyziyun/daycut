"""batch board: items for any vstudio.batch recipe - a segment list / plan-segments for the long-recording recipes,
one item per clip for the folder recipes."""
import glob
import os

from vstudio.batch.util import slug

from . import longform

FOLDER_RECIPES = ("talkinghead-clips", "talkinghead-folder")
VIDEO_EXT = (".mp4", ".mov", ".m4v", ".mkv", ".webm")


def plan_items(project, **kw):
    ins = project.data.get("inputs") or {}
    if project.batch() in FOLDER_RECIPES and not ins.get("segments"):
        folder = ins.get("folder")
        folder = folder[0] if isinstance(folder, list) else folder
        if not folder:
            raise ValueError("batch: inputs.folder (the clips) is required for " + project.batch())
        files = sorted(f for f in glob.glob(os.path.join(folder, "*")) if f.lower().endswith(VIDEO_EXT)
                       and not os.path.basename(f).startswith("."))
        return [dict(id=slug(os.path.splitext(os.path.basename(f))[0]), params=dict(file=os.path.basename(f)))
                for f in files]
    return longform.plan_items(project, **kw)
