<p align="center">
  <b>English</b> · <a href="README.zh-CN.md">简体中文</a> · <a href="README.fr.md">Français</a> · <a href="README.es.md">Español</a>
</p>

<p align="center">
  <picture>
    <source media="(prefers-color-scheme: dark)" srcset="docs/brand/wordmark-on-dark.svg">
    <img alt="Reelfold" src="docs/brand/wordmark-on-light.svg" width="340">
  </picture>
</p>

<p align="center"><b>One recording, every cut, for every platform.</b><br>
Free, open-source video tool for people who cut in batches. 千剪：一条素材，千条成片。</p>

<p align="center">
  <a href="https://reelfold.com/docs/">Docs</a> ·
  <a href="https://github.com/zyziyun/reelfold/releases/latest">Download for macOS</a> ·
  <a href="https://reelfold.com">reelfold.com</a> ·
  <a href="LICENSE">MIT</a>
</p>

- **Describe it, drop the footage.** Say what you want in plain words; Reelfold plans the clips and edits them in
  parallel on your own Mac.
- **Review only the exceptions.** Every file is checked automatically; you look at what was flagged.
- **Every platform in its own shape.** 20 platforms, each with its own size, captions, loudness, cover and copy.
  Publishing is assisted: Reelfold fills in the upload page, you press publish.

![Talking head · lecture slices · photo story · beat-cut vlog · podcast with masked faces · explainer](docs/demos/strip.jpg)

## Get it

**Mac app** (Apple Silicon, free). Download from [Releases](https://github.com/zyziyun/reelfold/releases/latest) once
the first build is out (coming soon); until then, [build from source](https://reelfold.com/docs/start/install-mac/).

**Claude Code skill** (same engine, still named `video-studio`):

```bash
git clone https://github.com/zyziyun/reelfold ~/.claude/skills/video-studio
~/.claude/skills/video-studio/install.sh
cp ~/.claude/skills/video-studio/persona.example.yaml ~/.claude/skills/video-studio/persona.local.yaml
```

AI runs on what you already have: your Claude Code or Codex login, your own API key, or a local model.

**Docs → [reelfold.com/docs](https://reelfold.com/docs/)**

## Say it like this

| You want | Say something like |
|---|---|
| A tight talking-head short | "Cut the pauses, filler words and repeats, speed it up 1.1×, add captions and a progress bar, export for TikTok and Shorts" |
| A lecture as vertical clips | "Slice this 70-minute lecture into 3 vertical episodes, one idea each, zoom into the code, with covers and post copy" |
| A podcast clip | "Find the best minute of this Zoom podcast, hide the guest's face and name label, vertical" |
| A fast travel vlog | "Make a fast beat-cut vlog from these Disneyland photos and clips, with day stamps, places, sound effects, 9:16" |
| One video, many platforms | "Export this for Xiaohongshu 3:4, TikTok and YouTube Shorts, each with its own safe zones and loudness" |

More: [example prompts](https://reelfold.com/docs/examples/).

## Learn more

[Getting started](https://reelfold.com/docs/start/what-is-reelfold/) ·
[Guides](https://reelfold.com/docs/guides/talking-head/) ·
[Concepts](https://reelfold.com/docs/concepts/projects/) ·
[Reference](https://reelfold.com/docs/reference/) ·
[Troubleshooting](https://reelfold.com/docs/help/troubleshooting/) ·
[Contributing](https://reelfold.com/docs/contributing/)

## License

MIT, including the desktop app (`apps/desk`), the website (`apps/site`) and the docs (`apps/docs`). Fonts and models
are downloaded at install time under their own licences (SIL OFL 1.1, Apache-2.0); the website and the docs ship
their own OFL web fonts. Built with
[HyperFrames](https://hyperframes.heygen.com) for the HTML-to-video workflows.

Formerly **video-studio** (the skill and engine) and **Daycut** (the desktop app). Existing installs in
`~/.claude/skills/video-studio` keep working; point them at the new URL with
`git -C ~/.claude/skills/video-studio remote set-url origin https://github.com/zyziyun/reelfold`.
