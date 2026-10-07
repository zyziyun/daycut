"""vstudio.launch - launch and update videos for makers: one config -> a demo video (16:9, 9:16, 1:1), a looping
README GIF, short feature clips, Product Hunt / OG stills, post copy per platform (EN + 中文) and a posting schedule.

    python -m vstudio.launch features CONFIG          # draft the feature list from the changelog / git range / notes
    python -m vstudio.launch capture CONFIG           # record the product (Playwright: an Electron app or a URL)
    python -m vstudio.launch all CONFIG               # build + render + stills + copy + schedule + first-pass check

Modules: features (release notes -> features), config (launch.config.yaml), story (timed plans + camera),
brand (theme + fonts + measured text), compose (HyperFrames project + render), stills, posts, schedule, kit.
Workflow guide: workflows/launch-kit/WORKFLOW.md.
"""
