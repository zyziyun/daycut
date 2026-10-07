// English copy (the shape every other language follows: zh.ts, fr.ts, es.ts are typed as `Dict`).
// Writing rules: README "Copy rules"; `npm run check:copy` enforces them on the built HTML.

export const en = {
  meta: {
    title: 'Reelfold: turn one recording into clips for 20 platforms (free, open source, Mac)',
    description:
      'Free, open-source Mac app that turns one long video into platform-ready clips for YouTube Shorts, TikTok, Instagram, Xiaohongshu, Douyin, Bilibili and more. Runs locally with the AI you choose.',
    ogAlt: 'Reelfold. One recording. Every platform. Free and open source, for Apple Silicon Macs.',
  },
  nav: {
    skip: 'Skip to content',
    docs: 'Docs',
    main: 'Main',
    how: 'How it works',
    batch: 'A real batch',
    oss: 'Open source',
    faq: 'FAQ',
    lang: 'Language',
    footer: 'Footer',
    breadcrumb: 'Breadcrumb',
  },
  cta: {
    download: 'Download for macOS',
    downloadShort: 'Download',
    star: 'Star on GitHub',
    starShort: 'Star',
    source: 'Build from source',
    fine: 'Apple Silicon · MIT licensed · also installs as a Claude Code skill',
    fineSoon: 'macOS app coming soon · MIT licensed · works today as a Claude Code skill',
    windows: 'Windows (preview, unsigned)',
  },
  hero: {
    eyebrow: 'Free and open source · for Apple Silicon Macs',
    h1a: 'One recording.',
    h1b: 'Every platform.',
    sub: 'Reelfold turns a long video into clips ready for twenty platforms. Describe what you want in a sentence. It plans the cuts, runs the whole batch on your Mac, and only asks you about the clips its checks flag.',
    fig: 'Home. Four things need you, about nine minutes.',
    figAlt: 'The Reelfold home screen: a request box, an inbox of four items that need a person (an English lesson, a backend class), and the batches running on this Mac.',
  },
  fig: 'Fig.',
  how: {
    k: 'How it works',
    t: 'You describe it. Reelfold does the batch.',
    l: 'Five steps from one recording to a week of posts. You stay in charge of two of them.',
    steps: [
      { label: 'Describe', t: 'Say what you want.', b: '“Cut this lecture into two-minute clips for Xiaohongshu and Shorts, keep the code readable.” Drop in a file, or a whole folder.' },
      { label: 'Plan', t: 'See the plan before anything runs.', b: 'Reelfold proposes the clips, formats and an AI cost estimate. Change a line, or approve it.' },
      { label: 'Batch', t: 'It runs on your Mac.', b: 'Cutting, captions, covers, loudness and one export per platform, all rendered locally.' },
      { label: 'Review', t: 'Look only at what’s flagged.', b: 'Every clip goes through automatic checks for length, captions, framing and loudness. You see the few that need a person.' },
      { label: 'Publish', t: 'You press publish.', b: 'Reelfold fills in each platform’s upload page, cover and copy included. It never posts on its own.' },
    ],
    figReview: 'Review. Only what the checks flagged.',
    figReviewAlt: 'Review screen: four suggested cuts in one clip, each with a before and after preview and a checkbox.',
    figPublish: 'Publish. A week, scheduled; you press publish.',
    figPublishAlt: 'Publish screen: a week calendar with clips placed per day and per platform, each marked ready, draft or posted.',
  },
  who: {
    k: 'Made for',
    t: 'People who post the same idea in many places.',
    items: [
      { slug: 'course-slicing', t: 'Course and lecture creators', b: 'Turn a recorded class into a series of short lessons, code and slides kept readable.', more: 'Course slicing' },
      { slug: 'podcast-clips', t: 'Podcast and interview clips', b: 'Pull the strongest answers from a long conversation, with captions and faces handled.', more: 'Podcast clips' },
      { slug: 'studios', t: 'Studios with client batches', b: 'Run the same treatment across many recordings and hand back one folder per platform.', more: 'Batch workflows' },
    ],
  },
  batch: {
    k: 'A real batch',
    t: 'One class, measured.',
    l: 'A 124-minute recorded backend class in English, cut into a batch on one Mac. Your numbers will vary with length and model.',
    nums: [
      { v: '124', u: 'min', l: 'one recorded class in' },
      { v: '9', u: '', l: 'clips planned and cut' },
      { v: '27', u: '', l: 'files out, 9 clips × 3 formats' },
      { v: '$0.29', u: '', l: 'total AI cost for the run' },
      { v: '8', u: '/9', l: 'passed every check on their own' },
    ],
    foot: 'The other one was flagged for a person to look at: its first frame was too dark for a preview. A longer chapter title fixed it.',
    passed: 'passed',
    flagged: 'flagged',
    cap: '8 of the 9 clips, with where each starts in the class',
    clipAlt: 'Cover of clip {n} of 9: “{title}”',
  },
  plat: {
    k: 'Platforms',
    t: 'Twenty platforms, each in its own shape.',
    l: 'Right aspect ratio, loudness, cover size and copy limits for every one, including the Chinese platforms most tools skip.',
    more: 'Every size and limit',
  },
  local: {
    k: 'Local first',
    t: 'Your Mac. Your AI. Your accounts.',
    items: [
      { t: 'Runs on your Mac', b: 'Video is cut, captioned and rendered on your own machine. No upload queue, no render credits.' },
      { t: 'Bring your own AI', b: 'Use the Claude Code or Codex subscription you already pay for, an API key, or a local model.' },
      { t: 'You press publish', b: 'You sign in to each platform yourself, inside the app. Reelfold never posts without you pressing publish.' },
    ],
  },
  create: {
    k: 'Coming next',
    t: 'Create.',
    l: 'AI video for the things you can’t film: series ads with the same cast every episode, sketches, product spots. Plus a recording studio with a teleprompter and automatic retake cleanup.',
    tag: 'In development',
    alt: 'Create, in development: a home screen for AI series, sketches and product spots.',
  },
  os: {
    k: 'Open source',
    t: 'MIT licensed. Built in the open.',
    l: 'The app and the engine underneath it are on GitHub. Read the code, file an issue, or teach it a new workflow.',
    links: [
      { t: 'Star on GitHub', b: 'Follow releases and the roadmap' },
      { t: 'Discussions', b: 'Ask questions, share batches' },
      { t: 'Contribute', b: 'Workflows, platforms, translations' },
    ],
    skillT: 'Prefer the terminal?',
    skillL: 'The same engine runs as a Claude Code skill.',
  },
  faq: {
    k: 'FAQ',
    t: 'Questions, answered plainly.',
    items: [
      { q: 'Is it really free?', a: 'Yes. Reelfold is MIT licensed and free to use. The only cost is the AI you connect: the 124-minute class above used $0.29. With a subscription you already have, or a local model, there’s no extra bill.' },
      { q: 'What do I need?', a: 'A Mac with Apple Silicon, and an AI: a Claude Code or Codex subscription, an API key, or a local model. A Windows version comes later.' },
      { q: 'Does my video leave my Mac?', a: 'Cutting and rendering happen on your Mac. The AI you connect sees what it needs to plan, such as the transcript, under that provider’s terms. With a local model, nothing leaves.' },
      { q: 'Will it post for me?', a: 'No. It prepares each upload page with the video, cover and copy filled in. You check it and press publish.' },
      { q: 'How is it different from Opus Clip or Descript?', a: 'Reelfold is built for batches: one recording into many clips across twenty platforms, rendered locally, with the AI you choose. It’s open source and free. Descript is a great editor for one video at a time; Reelfold is for the week of posts after it.' },
      { q: 'Do I need to label AI content?', a: 'Many platforms ask you to disclose AI-edited or AI-generated content. Reelfold’s publishing checklist reminds you on each one.' },
    ],
  },
  final: { t: 'Make the week from one recording.' },
  footer: {
    tag: 'Turns one recording into many platform-ready clips. Free and open source.',
    product: 'Product',
    useCases: 'Use cases',
    compare: 'Compare',
    project: 'Project',
    skill: 'Claude Code skill',
    releases: 'Releases',
    specs: 'Platform specs',
    discussions: 'Discussions',
    privacy: 'Privacy',
    terms: 'Terms',
    license: 'MIT License',
    vs: 'vs {name}',
  },
  page: {
    home: 'Home',
    useCases: 'Use cases',
    compare: 'Compare',
    related: 'Related',
    faqT: 'Questions',
    lastChecked: 'Last checked',
    sources: 'Sources',
    getStarted: 'Try it on your next recording.',
    getStartedL: 'Free and open source. Your video stays on your Mac.',
  },
  legal: {
    draft: 'Draft, review before publishing',
    draftBody: 'This is a first draft that has not been reviewed by a lawyer. It must be checked and revised before the site goes live.',
    updated: 'Updated',
    back: 'Back to home',
    privacyTitle: 'Privacy policy',
    termsTitle: 'Terms of use',
    englishOnly: '',
  },
  notFound: {
    title: 'Page not found',
    t: 'This page isn’t here.',
    l: 'The link may be old, or the page moved when the site was rebuilt.',
    home: 'Go to the home page',
  },
  platformNames: {
    youtube: 'YouTube', 'youtube-shorts': 'YouTube Shorts', tiktok: 'TikTok', instagram: 'Instagram', x: 'X',
    facebook: 'Facebook', linkedin: 'LinkedIn', threads: 'Threads', reddit: 'Reddit', pinterest: 'Pinterest',
    snapchat: 'Snapchat', xiaohongshu: 'Xiaohongshu', douyin: 'Douyin', 'wechat-channels': 'WeChat Channels',
    bilibili: 'Bilibili', kuaishou: 'Kuaishou', weibo: 'Weibo', zhihu: 'Zhihu', dailymotion: 'Dailymotion', kwai: 'Kwai',
  } as Record<string, string>,
};

type Widen<T> = T extends string
  ? string
  : T extends readonly (infer U)[]
    ? Widen<U>[]
    : T extends object
      ? { [K in keyof T]: Widen<T[K]> }
      : T;
export type Dict = Widen<typeof en>;
