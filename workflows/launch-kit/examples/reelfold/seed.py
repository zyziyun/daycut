#!/usr/bin/env python3
"""Seed a privacy-safe, throwaway Reelfold profile with REAL engine data, for capturing the app itself.

    python3 seed.py --root DIR [--explainer OUT_DIR] [--shared-cache CACHE_DIR] [--python PY] [--steps ...]
    node ../../scripts/capture.mjs --shots shots.yaml --out CAPTURE_DIR \
         --electron <repo>/apps/desk --env-json DIR/env.json

Everything lives under DIR (pass a fresh temp dir): ``profile/`` (DESK_USER_DATA), ``vhome/`` (VSTUDIO_HOME),
``cache/`` (VSTUDIO_CACHE / DESK_SHARED_CACHE), ``media/``, ``watch/`` (DESK_HISTORY_WATCH). Nothing outside DIR is
written; the creator's real profile, VSTUDIO_HOME and caches are never touched (the shared cache's ``fonts`` and
``models`` folders are symlinked read-only for fonts / face models; Whisper / Kokoro load from the Hugging Face cache
in offline mode).

Steps (``--steps``, default all, in this order):
  media    a synthetic English talk: typographic slides + an offline Kokoro voice (``vstudio.tts``), with real
           filler words and pauses so cleanup has something to find -> ``media/creator-workshop-screencast.mp4``
  engine   through the real engine CLI, no AI account (rule planner): intake analyze (ASR warm-up for the Home shot),
           project "Workshop talk" (intake plan + apply + ``vstudio.project run``, checkpoints answered with their
           defaults, QC-red clips approved, exported -> the transcript and publish shots) and project "Office hours"
           (run until it parks at the filler checkpoint -> inbox items)
  profile  desk settings: English UI, light appearance (notebook-light), default platforms TikTok + YouTube Shorts +
           Xiaohongshu, three publishing accounts named "Reelfold demo" (no real handles, no emails, never logged in)
  outputs  (only with --explainer) copies the creator's own finished English explainer outputs (her face only, no
           other people, no personal data: checked frame by frame before use) into ``watch/`` as a finished project
Writes ``DIR/env.json``: the env vars for ``capture.mjs --env-json``.
"""
import argparse
import json
import os
import shutil
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.abspath(os.path.join(HERE, "..", "..", "..", ".."))
TALK = "creator-workshop-screencast.mp4"   # "screencast": the rule planner reads it as a talk to slice

# (slide title, slide lines, spoken lines). "um" / "uh" / repeats are on purpose: the filler pass finds them.
SCRIPT = [
    ("One recording,\na week of posts", ["A short workshop talk", "Reelfold demo"], [
        "Hi everyone. Um, today I want to show you how I turn one recording into a whole week of posts.",
        "Most of us film one long video, and then, uh, it just sits on the hard drive.",
        "So, basically, the work is already done. We just never cut it up.",
        "Let's fix that. There are four steps, and none of them take very long.",
    ]),
    ("1  Find the moments", ["One idea per clip", "A hook in the first line", "A clear ending"], [
        "Step one is finding the moments that stand on their own.",
        "A good clip has one idea, one hook, and, um, a clear ending.",
        "If you have to explain the context first, it's, it's probably not a clip.",
        "And, you know, the best moments are usually the ones where you got a little excited.",
        "I usually find three to five of these in a twenty minute recording.",
    ]),
    ("2  Cut it tight", ["Drop the pauses", "Drop the ums and false starts", "Keep the energy"], [
        "Step two: cut it tight. Remove the pauses, the filler words, and the false starts.",
        "Viewers decide in about two seconds, so, uh, the first line matters more than anything else.",
        "I mean, if the first sentence is slow, nobody hears the second one.",
        "Tight doesn't mean rushed. Keep the breaths that carry the meaning.",
    ]),
    ("3  Fit every platform", ["TikTok and Shorts: vertical, big captions", "Xiaohongshu: a strong cover", "One master, many exports"], [
        "Step three: fit every platform.",
        "TikTok and YouTube Shorts want vertical video with big, readable captions.",
        "Xiaohongshu wants a strong cover and a short title. Um, the cover does most of the work there.",
        "Actually, like, the same clip can look completely different on each one.",
        "So edit one master, and let the exports follow it.",
    ]),
    ("4  Plan the week", ["One clip a day is plenty", "Batch once, post daily"], [
        "Step four: plan the week. One clip a day is, uh, plenty.",
        "Pick a time for each account, and fill the empty days first.",
        "Batch the work once, and then just show up and post.",
    ]),
    ("Thank you", ["One recording, a week of posts", "Reelfold demo"], [
        "That's it. One recording, a week of posts.",
        "Try it on your next video, and, you know, tell me how it goes. Thanks for watching.",
    ]),
]

W, H = 1920, 1080


def sh(cmd, env=None, **kw):
    print("+", " ".join(str(c) for c in cmd)[:200], flush=True)
    return subprocess.run(cmd, check=True, env=env, **kw)


def font(cache, name):
    p = os.path.join(cache, "fonts", name)
    if not os.path.isfile(p):
        sys.exit(f"font {name} missing under {cache}/fonts (run the skill's install.sh, or pass --shared-cache)")
    return p


def slide(path, title, lines, idx, n, cache, k=2):
    """One slide at k x 1080p (the talk drifts in slowly, so the text stays sharp)."""
    from PIL import Image, ImageDraw, ImageFont
    im = Image.new("RGB", (W * k, H * k), (14, 17, 19))
    d = ImageDraw.Draw(im)
    bold, reg = font(cache, "NotoSansSC-Bold.otf"), font(cache, "NotoSansSC-Regular.otf")
    d.rectangle([140 * k, 200 * k, 152 * k, 880 * k], fill=(45, 212, 191))
    y = 210
    for t in title.split("\n"):
        d.text((200 * k, y * k), t, font=ImageFont.truetype(bold, 96 * k), fill=(240, 244, 245))
        y += 124
    y += 40
    for ln in lines:
        d.text((200 * k, y * k), ln, font=ImageFont.truetype(reg, 46 * k), fill=(160, 172, 178))
        y += 72
    small = ImageFont.truetype(reg, 30 * k)
    d.text((200 * k, 960 * k), "Demo talk  ·  synthetic voice", font=small, fill=(90, 102, 108))
    d.text(((W - 260) * k, 960 * k), f"{idx} / {n}", font=small, fill=(90, 102, 108))
    im.save(path)


def say(tts, text, out):
    """Kokoro (offline). mlx-audio's Kokoro fails on some lengths: nudge the speed, else say it in two halves."""
    for speed in (1.0, 0.97):
        try:
            return tts.synth(text, engine="kokoro", voice="af_heart", speed=speed, out=out)
        except (ValueError, RuntimeError) as e:
            print(f"tts retry ({str(e).strip().splitlines()[-1][:120]})", flush=True)
    cuts = [i for i, c in enumerate(text) if c == ","]
    if not cuts:
        sys.exit(f"tts failed on: {text}")
    i = min(cuts, key=lambda c: abs(c - len(text) / 2)) + 1
    a, b = say(tts, text[:i].strip(), out + ".a.wav"), say(tts, text[i:].strip(), out + ".b.wav")
    sh(["ffmpeg", "-v", "error", "-y", "-i", a, "-i", b, "-filter_complex", "[0][1]concat=n=2:v=0:a=1", "-c:a", "pcm_s16le", out])
    return out


def make_media(root, cache, py):
    """Slides + Kokoro narration -> one 1080p talk with a real voice track (pauses between lines)."""
    media = os.path.join(root, "media")
    work = os.path.join(media, "work")
    os.makedirs(work, exist_ok=True)
    out = os.path.join(media, TALK)
    if os.path.isfile(out):
        print("media: exists", out)
        return out
    sys.path.insert(0, os.path.join(REPO, "lib"))
    from vstudio import tts
    parts, k = [], 0
    for si, (title, lines, spoken) in enumerate(SCRIPT, 1):
        png = os.path.join(work, f"slide{si}.png")
        slide(png, title, lines, si, len(SCRIPT), cache)
        wavs = []
        for line in spoken:
            k += 1
            wav = say(tts, line, os.path.join(work, f"l{k:02d}.wav"))
            wavs.append(wav)
        # line pauses: 0.45 s, a longer 1.4 s gap after the 2nd line of each slide (a "breath" cleanup can cut)
        lst = os.path.join(work, f"s{si}.txt")
        with open(lst, "w") as f:
            for j, w in enumerate(wavs):
                f.write(f"file '{w}'\n")
                gap = os.path.join(work, "gap_long.wav" if j == 1 else "gap.wav")
                f.write(f"file '{gap}'\n")
        parts.append((png, lst))
    for name, secs in (("gap.wav", 0.45), ("gap_long.wav", 1.4)):
        sh(["ffmpeg", "-v", "error", "-y", "-f", "lavfi", "-i", f"anullsrc=r=48000:cl=mono", "-t", str(secs),
            "-c:a", "pcm_s16le", os.path.join(work, name)])
    segs = []
    for si, (png, lst) in enumerate(parts, 1):
        wav = os.path.join(work, f"s{si}.wav")
        sh(["ffmpeg", "-v", "error", "-y", "-f", "concat", "-safe", "0", "-i", lst, "-c:a", "pcm_s16le", "-ar", "48000", wav])
        seg = os.path.join(work, f"s{si}.mp4")
        secs = float(subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", wav],
                                    check=True, capture_output=True, text=True).stdout)
        # a slow push-in: a real talk is never a frozen frame (QC flags frozen video)
        zoom = f"zoompan=z='1+0.05*on/{int(secs * 30)}':x='iw/2-iw/zoom/2':y='ih/2-ih/zoom/2':d=1:s={W}x{H}:fps=30"
        sh(["ffmpeg", "-v", "error", "-y", "-loop", "1", "-framerate", "30", "-i", png, "-i", wav, "-shortest",
            "-vf", zoom, "-c:v", "libx264", "-preset", "veryfast", "-crf", "18", "-pix_fmt", "yuv420p", "-r", "30",
            "-c:a", "aac", "-b:a", "160k", seg])
        segs.append(seg)
    lst = os.path.join(work, "all.txt")
    with open(lst, "w") as f:
        f.writelines(f"file '{s}'\n" for s in segs)
    sh(["ffmpeg", "-v", "error", "-y", "-f", "concat", "-safe", "0", "-i", lst, "-c", "copy", "-movflags", "+faststart", out])
    shutil.rmtree(work)
    print("media:", out)
    return out


PROMPT = "Cut this talk into vertical clips for TikTok and Xiaohongshu"
PERSONA = """# the demo creator: English speech, a neutral name (no handle, no email)
creator: {name: "Reelfold demo", handle: "", language: en}
"""


def eng(py, env, *args, ok=(0,)):
    """One engine CLI call (``python -m vstudio.<module> ... --json``) -> its JSON document."""
    r = subprocess.run([py, "-m", *args], env=engine_env(env), capture_output=True, text=True)
    if r.returncode not in ok:
        sys.exit(f"engine {' '.join(args[:2])} failed (exit {r.returncode}):\n{r.stderr[-3000:]}")
    return json.loads(r.stdout) if r.stdout.strip().startswith("{") else {}


def new_project(py, env, root, talk, name):
    """The same path the Home composer takes: intake plan (rule planner, no AI account) -> apply."""
    plan = os.path.join(root, "media", f"{name}.plan.json")
    eng(py, env, "vstudio.intake", "plan", "--prompt", PROMPT, "--inputs", talk, "--out", plan, "--json")
    with open(plan) as f:
        doc = json.load(f)
    doc["projects"][0]["name"] = name            # what she would type on the plan card
    with open(plan, "w") as f:
        json.dump(doc, f, ensure_ascii=False, indent=1)
    out = eng(py, env, "vstudio.intake", "apply", "--plan", plan, "--json")
    return out["projects"][0]["dir"]


def seed_engine(root, env, py, talk):
    if not os.path.isfile(talk):
        sys.exit(f"no talk at {talk}: run --steps media first")
    home = env["VSTUDIO_HOME"]
    if os.path.isfile(os.path.join(home, "projects.json")):
        print("engine: already seeded", home)
        return
    # 1. warm the intake analysis + ASR cache, so the recorded Home plan appears in seconds, not minutes
    eng(py, env, "vstudio.intake", "analyze", "--inputs", talk, "--json")
    # 2. a finished project: every checkpoint answered with its default, QC-red clips approved, exported
    done = new_project(py, env, root, talk, "Workshop talk")
    eng(py, env, "vstudio.project", "run", "--dir", done, "--auto", "segments,filler", "--json", ok=(0, 1, 7))
    eng(py, env, "vstudio.project", "checkpoint", "--dir", done, "--id", "publish", "--answer", '{"approve": true}', "--run", "--json",
        ok=(0, 1, 7))
    eng(py, env, "vstudio.project", "export", "--dir", done, "--json")
    # 3. a project that parks at the filler checkpoint (taste calls like a sentence-initial "So,"): inbox items
    wait = new_project(py, env, root, talk, "Office hours")
    eng(py, env, "vstudio.project", "run", "--dir", wait, "--auto", "segments", "--json", ok=(0, 1, 7))
    for d in (done, wait):
        st = eng(py, env, "vstudio.project", "status", "--dir", d, "--json", "--brief")
        print("engine:", os.path.basename(d), st.get("state"), st.get("pending"))


def continue_latest(root, env, py, timeout=180):
    """Shot helper: the project the Home shot just started parks at "approve the segments" after its pilot probe;
    approve them (the default) and run the rest (pilot confirmed) in the background with the engine CLI, with the
    filler questions answered by their defaults so the next shot shows clips rendering (answered in the app's inbox,
    the run would go on too, but stop at each clip's filler question). Returns once the run has started."""
    import glob
    import time
    dirs = sorted(glob.glob(os.path.join(env["VSTUDIO_HOME"], "projects", "*", "*", "project.yaml")), key=os.path.getmtime)
    if not dirs:
        sys.exit("no project yet: click Start on the plan card first")
    d = os.path.dirname(dirs[-1])
    t0 = time.time()
    while True:
        st = eng(py, env, "vstudio.project", "status", "--dir", d, "--json", "--brief")
        if st.get("state") == "needs-you":
            break
        if time.time() - t0 > timeout:
            sys.exit(f"the pilot of {d} never reached a checkpoint (state {st.get('state')})")
        time.sleep(1)
    eng(py, env, "vstudio.project", "checkpoint", "--dir", d, "--id", "segments", "--default", "--json", ok=(0, 1))
    log = open(os.path.join(root, "continue.log"), "ab")  # noqa: SIM115
    subprocess.Popen([py, "-m", "vstudio.project", "run", "--dir", d, "--confirm-pilot", "--auto", "segments,filler",
                      "--json-events"],
                     env=engine_env(env), stdout=log, stderr=log, stdin=subprocess.DEVNULL, start_new_session=True)
    print("continue:", d)


def seed_profile(root):
    """Desk settings: English UI, three publishing accounts with a neutral name, never logged in."""
    accounts = {"tiktok": "18:00", "youtube-studio": "12:00", "xiaohongshu": "20:00"}
    s = dict(lang="en", theme="notebook-light", accent="teal", firstRunDone=True, cleanupMigrated=True,
             defaultPlatforms=["tiktok", "youtube-shorts", "xiaohongshu"], personaPath=os.path.join(root, "persona.yaml"),
             accounts={a: ["main"] for a in accounts},
             channels={f"{a}/main": dict(name="Reelfold demo", times=[t]) for a, t in accounts.items()})
    with open(os.path.join(root, "profile", "settings.json"), "w") as f:
        json.dump(s, f, indent=2)


def seed_outputs(root, src):
    """The creator's own finished explainer as a plain work folder (copied; the source folder is only read): one
    clip in two shapes, its cover and its post copy."""
    dst = os.path.join(root, "watch", "AI explainer", "final")
    if os.path.isdir(dst):
        return
    os.makedirs(dst)
    for name, out in (("tiktok-vertical.mp4", "ai-explainer_9x16.mp4"), ("linkedin-horizontal.mp4", "ai-explainer_16x9.mp4"),
                      ("tiktok-vertical.cover.jpg", "ai-explainer_cover.jpg"), ("youtube-shorts-vertical.post.md", "post.md")):
        if not os.path.isfile(os.path.join(src, name)):
            sys.exit(f"--explainer: {name} missing in {src}")
        shutil.copy2(os.path.join(src, name), os.path.join(dst, out))


def link_cache(root, shared):
    """A private cache whose fonts / models point at the shared one (read-only use); everything else is new."""
    cache = os.path.join(root, "cache")
    os.makedirs(cache, exist_ok=True)
    for sub in ("fonts", "models"):
        src, dst = os.path.join(shared, sub), os.path.join(cache, sub)
        if os.path.isdir(src) and not os.path.exists(dst):
            os.symlink(src, dst)
    return cache


def env_for(root, cache, py):
    return {
        "DESK_USER_DATA": os.path.join(root, "profile"),
        "VSTUDIO_HOME": os.path.join(root, "vhome"),
        "DESK_SHARED_CACHE": cache,
        "VSTUDIO_CACHE": cache,
        "DESK_HISTORY_WATCH": os.path.join(root, "watch"),
        "DESK_PYTHON": py,
        "VSTUDIO_PERSONA": os.path.join(root, "persona.yaml"),
        "DESK_SKIP_FIRST_RUN": "1",
        "VSTUDIO_DEFAULT_PERSONA": "1",     # the repo's persona.example.yaml only: no private persona / AI routes
        "HF_HUB_OFFLINE": "1",
        "VITE_DEV_SERVER_URL": "",
    }


AI_ENV = ("ANTHROPIC_API_KEY", "ANTHROPIC_AUTH_TOKEN", "ANTHROPIC_BASE_URL", "OPENAI_API_KEY", "OPENAI_BASE_URL",
          "GEMINI_API_KEY", "ELEVENLABS_API_KEY")


def engine_env(env):
    """The seed's own engine calls: same isolation as the app, no AI credentials inherited."""
    e = {k: v for k, v in os.environ.items() if not k.startswith(("ANTHROPIC_", "OPENAI_", "GEMINI_", "ELEVENLABS_"))}
    e.update(env)
    e["PYTHONPATH"] = os.path.join(REPO, "lib")
    return e


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--root", required=True, help="a fresh temp folder; everything is written under it")
    ap.add_argument("--explainer", help="finished English explainer outputs to show as a finished project (optional)")
    ap.add_argument("--shared-cache", default=os.environ.get("VSTUDIO_SHARED_CACHE"),
                    help="the skill's cache to borrow fonts / models from (read-only; default env VSTUDIO_SHARED_CACHE)")
    ap.add_argument("--python", default=sys.executable, help="the Python with the engine's dependencies")
    ap.add_argument("--steps", default="media,engine,profile,outputs")
    ap.add_argument("--continue-latest", action="store_true", help="(shot setup) approve the newest project's segments "
                                                                     "and run it in the background")
    a = ap.parse_args()
    root = os.path.abspath(a.root)
    if not a.shared_cache and not a.continue_latest:
        sys.exit("--shared-cache (or env VSTUDIO_SHARED_CACHE): the skill's cache folder with fonts/ and models/")
    for sub in ("profile", "vhome", "watch", "media"):
        os.makedirs(os.path.join(root, sub), exist_ok=True)
    cache = link_cache(root, os.path.abspath(a.shared_cache)) if a.shared_cache else os.path.join(root, "cache")
    with open(os.path.join(root, "persona.yaml"), "w") as f:
        f.write(PERSONA)
    env = env_for(root, cache, os.path.abspath(a.python))
    os.environ.update({k: env[k] for k in ("VSTUDIO_CACHE", "VSTUDIO_HOME", "HF_HUB_OFFLINE", "VSTUDIO_DEFAULT_PERSONA",
                                           "VSTUDIO_PERSONA")})
    if a.continue_latest:
        return continue_latest(root, env, a.python)
    steps = a.steps.split(",")
    talk = os.path.join(root, "media", TALK)
    if "media" in steps:
        talk = make_media(root, cache, a.python)
    if "engine" in steps:
        seed_engine(root, env, a.python, talk)
    if "profile" in steps:
        seed_profile(root)
    if "outputs" in steps and a.explainer:
        seed_outputs(root, os.path.abspath(a.explainer))
    with open(os.path.join(root, "env.json"), "w") as f:
        # null = drop it from the inherited env: the app must not pick up the operator's AI credentials
        json.dump({**env, **{k: None for k in AI_ENV}, "REELFOLD_SEED": os.path.abspath(__file__), "REELFOLD_SEED_ROOT": root,
                   "REELFOLD_DEMO_TALK": talk}, f, indent=2)
    print("env:", os.path.join(root, "env.json"))


if __name__ == "__main__":
    main()
