# Roadmap

What we are working on and what comes next. **No dates**: this is a one-maintainer open-source project, and the
order changes with what real users hit. Items marked **help wanted** are good places to contribute; ask in the issue
or in [Discussions](https://github.com/zyziyun/reelfold/discussions) before starting something big.

Want something that isn't here? [Open a feature request](https://github.com/zyziyun/reelfold/issues/new/choose).

## Now: first macOS release (0.2.0)

- Signed and notarized Apple Silicon build on [Releases](https://github.com/zyziyun/reelfold/releases), with
  auto-update.
- Calmer first run: sign in with your AI subscription first, keys second, no developer settings in the way.
- Clear progress while a plan or pilot runs (elapsed time, step, stop), and plain-language errors with a retry.
- Layout and wording polish across Settings, the publish package page and narrow windows.
- A short demo video and an examples gallery in the docs.

## Next

**Platforms and publishing**
- Assisted publishing for 小红书 and 抖音 (the profiles exist; the upload-page fill does not yet).
- Verify the assisted-fill selectors for X, Instagram, 视频号 and B站 against live upload pages.
- More platform profiles on request (Lemon8, Twitch clips, Naver Clip…). **help wanted**

**Editing quality**
- Format defaults flow into every plan, so a talking head, a podcast clip and a lecture slice each start with the
  right speed, hooks, cleanup strength and cover rules.
- One-step cover recipe: a four-frame collage with retouch, same canvas as the clip.
- Hashtag sets chosen by format reach the post copy.
- Caption fixes you make (names, places, terms) are remembered for next time.
- A podcast long-form preset for YouTube.
- Optional noise reduction for your own voice-over.

**App**
- Run any workflow as a project type, with an agent panel inside the project.
- Built-in terminal to start Claude Code or Codex next to your project.
- Multi-client workspaces for studios cutting for several clients.

## Later

- **Windows** build (the app is Electron and the bundled runtime already has Windows pieces; a tested build, packaging and signing are the
  missing parts). **help wanted**
- More app languages: Español next (the docs and website already have it), then Japanese and Korean. **help wanted**
- Docs translations beyond en / zh / fr / es. **help wanted**
- The Create page out of its settings flag: series studio for AI-generated video, with a spend gate.
- Linux build of the app (the engine and skill already run on Linux).

## Done recently

See the [changelog](CHANGELOG.md).
