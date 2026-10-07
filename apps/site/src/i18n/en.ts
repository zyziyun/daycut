// English copy. Writing rules: see README "Copy rules"; `npm run check:copy` enforces them.
import type { zh } from './zh';

type Widen<T> = T extends string
  ? string
  : T extends readonly (infer U)[]
    ? readonly Widen<U>[]
    : T extends object
      ? { readonly [K in keyof T]: Widen<T[K]> }
      : T;

export const en: Widen<typeof zh> = {
  lang: 'en',
  htmlLang: 'en',
  meta: {
    title: 'Reelfold · One recording, folded out to every platform',
    description:
      'Reelfold is a free, open-source (MIT) Mac app that turns one recording into platform-ready clips. Describe the batch, AI plans it, the edits run on your Mac, you review only what the checks flag, and it fills in each post for YouTube, TikTok, Instagram, X, LinkedIn, Xiaohongshu, Douyin, Bilibili and more. You press publish.',
  },
  nav: {
    how: 'How it works',
    uses: 'Who it’s for',
    app: 'Mac app',
    proof: 'Real numbers',
    local: 'Local-first',
    oss: 'Open source',
    faq: 'FAQ',
    langGroup: 'Language',
    skip: 'Skip to content',
  },
  cta: {
    download: 'Download for macOS',
    soon: 'macOS app: coming soon',
    soonNote: 'The first macOS release is coming soon. Until then, build it from source or use the engine as a Claude Code skill.',
    star: 'Star on GitHub',
    source: 'Build from source',
    windows: 'Windows: later',
  },
  hero: {
    eyebrow: 'Free and open source (MIT) · macOS app · Apple Silicon',
    titleA: 'Describe it. Drop the footage.',
    titleB: 'Get every cut, for every platform.',
    sub: 'One recording, folded out to every platform. Say what you want in plain words and drop in an interview, a podcast, a lecture or a client batch. AI plans the clips, the whole batch runs on your Mac, and you review only what the checks flag. Every platform gets its own video, cover and post copy; you press publish.',
    points: [
      'Your footage stays on your Mac',
      'You review only the clips the checks flag',
      'Assisted publishing: it fills in the post, you press publish',
    ],
    stickerA: 'Xiaohongshu 3:4',
    stickerB: 'QC passed',
    stickerC: '1 recording → 96 files',
    frameAlts: [
      'Talking-head short with captions and a notes panel',
      'Lecture slice showing code with a title band about hybrid retrieval',
      'Knowledge video with two speakers and a notes panel',
    ],
  },
  how: {
    kicker: 'How it works',
    title: 'One recording in, a whole batch out',
    steps: [
      {
        title: 'Describe',
        body: 'Drop in a recording (an interview, podcast, lecture, livestream replay or a client’s footage) and say in plain words how many clips you want, for which platforms, in what style.',
      },
      {
        title: 'AI plans',
        body: 'AI picks the segments by topic and writes a plan you can read and change: which part becomes which clip, its title, and where it goes.',
      },
      {
        title: 'Batch runs',
        body: 'The whole batch runs in parallel on your Mac: pauses, filler words and repeats removed; captions, title bands, code zooms and notes panels added.',
      },
      {
        title: 'Review exceptions',
        body: 'Every file is checked for loudness, audio/video sync, missing caption words, text under app buttons, clip length and title length. Only the red ones land in your review grid; fix them in the transcript and re-render just those.',
      },
      {
        title: 'Assisted publishing',
        body: 'Each platform gets its own export, cover, title, caption, tags and a reminder to add the AI-content label. Reelfold fills in the upload page; you check it and press publish. It never posts on its own.',
      },
    ],
    platformsLabel: 'Platforms',
    platforms: ['YouTube 16:9 + Shorts 9:16', 'TikTok 9:16', 'Instagram Reels 9:16 + feed 4:5', 'X 16:9 / 1:1 / 9:16', 'Facebook Reels 9:16 + feed 4:5', 'LinkedIn 16:9 / 1:1', 'Threads 9:16', 'Reddit 16:9', 'Pinterest 9:16', 'Snapchat Spotlight 9:16', 'Xiaohongshu 3:4', 'Douyin 9:16', 'WeChat Channels 9:16', 'Bilibili 16:9', 'Kuaishou 9:16', 'Weibo 16:9', 'Zhihu 16:9', 'Dailymotion 16:9', 'Kwai 9:16'],
  },
  uses: {
    kicker: 'Who it’s for',
    title: 'For people who cut in batches and post everywhere',
    lede: 'One engine, many kinds of footage. Each workflow was tested on real recordings.',
    items: [
      { title: 'Batch creators', body: 'Record once, publish all week. One session becomes a set of clips, each exported in the shape, length and loudness every platform you post on expects.' },
      { title: 'Interviews and podcasts', body: 'Pull many clips out of one long conversation, with captions and speaker framing, and a separate export per platform. Guests can be masked and name labels blurred.' },
      { title: 'Studios doing client batches', body: 'Run several clients’ batches side by side on one board. Keep each client’s style and glossary, with a QC report for every batch.' },
      { title: 'Talking-head', body: 'Remove pauses, filler words and repeats, then add captions, keyword pops, a chapter progress bar and a cover.' },
      { title: 'Course slicing', body: 'Turn a long lecture into vertical slices or episodes, with title bands, code crops that follow the text and chapter cards. Student voices can be changed.' },
      { title: 'Explainers', body: '3Blue1Brown-style explainers with AI narration, animated scenes and bilingual captions, made from a script or a topic.' },
    ],
  },
  app: {
    kicker: 'Desktop app',
    title: 'Reelfold for Mac',
    lede: 'Describe the batch in plain words. Reelfold plans it, runs the jobs in parallel on your own computer and tracks them on a board. Review clips in a grid and cut by editing the transcript. When it’s time to post, it fills in each platform’s upload page in a built-in browser, and you press publish yourself.',
    note: 'Free and open source (MIT). Apple Silicon Macs only for now. AI runs on your own Claude Code or Codex subscription, your API keys, or a local model.',
    board: {
      cols: ['Queued', 'Rendering', 'QC', 'Review', 'Approved'],
      cards: ['ep03 · RRF ranks only', 'ep06 · small chunks', 'ep11 · which metric first', 'ep14 · parent-child', 'ep19 · reranking'],
      green: 'green',
      red: 'red · word may be lost at seam',
      caption: 'Illustration of the batch board (not a screenshot).',
    },
  },
  proof: {
    kicker: 'Real numbers',
    title: 'One real batch with the open-source tool',
    lede: 'We ran one of our own 72-minute lectures through it as a single batch. Here is what worked and what didn’t.',
    stats: [
      { value: '96', label: 'finished files', note: '24 clips × 4 platform formats, each with a cover and post copy' },
      { value: '$0.73', label: 'AI API cost for the batch', note: 'About $0.03 per clip; transcription ran locally' },
      { value: '21 / 24', label: 'clips passed automatic QC', note: 'All 3 red clips were at edit seams and went to the review grid' },
      { value: '3–4 h', label: 'first-run machine time', note: 'After a fix, re-running just the 13 affected clips took 18 minutes' },
    ],
    caveatsTitle: 'What isn’t good enough yet',
    caveats: [
      'Chinese captions still get some words wrong. A glossary fixes some of them; you catch the rest in review.',
      'Filler-word cuts still ask you too many yes/no questions (about 15 per clip in this batch). We’re working on letting the low-risk ones through automatically.',
      'When on-screen text in the source is small, it’s hard to read after a vertical crop.',
    ],
    stripCaption: 'Frames from six kinds of edits made with the same tools: talking head, lecture slices, photo story, travel vlog, podcast with face masking and explainer.',
    stripAlts: [
      'Talking-head short with captions and a notes panel',
      'Lecture slice with code and a title band',
      'Photo story comparing a draft and the finished painting',
      'Travel vlog with a place tag and confetti effect',
      'Podcast clip with two speakers and a notes panel',
      'Explainer animating CUDA thread indexing with bilingual captions',
    ],
    sheets: [
      {
        img: 'longform-slices',
        alt: 'Contact sheet of lecture slices: title bands, cropped code screenshots, notes panels and chapter cards',
        caption: 'Lecture slices: vertical clips cut from the 72-minute lecture. Title bands, code crops that follow the text, notes panels, chapter cards.',
      },
      {
        img: 'talkinghead',
        alt: 'Contact sheet of a talking-head edit: chapter progress bar, notes panels, keyword pops',
        caption: 'Talking-head edit: chapter progress bar, notes panels, keyword pops.',
      },
      {
        img: 'explainer-vertical',
        alt: 'Contact sheet of an explainer: animated scenes with English and Chinese captions',
        caption: 'Explainer: AI narration, English and Chinese captions, animated scenes.',
      },
    ],
  },
  deliverables: {
    kicker: 'Every batch',
    title: 'What every clip comes with',
    items: [
      { title: 'Per-platform videos', body: 'YouTube long-form 16:9 and Shorts 9:16; TikTok, Instagram and Facebook Reels, Snapchat and Pinterest 9:16; X, LinkedIn and Reddit in the shape closest to your video; Xiaohongshu 3:4; Douyin, WeChat Channels and Kuaishou 9:16; Bilibili, Weibo, Zhihu and Dailymotion 16:9. Each one is exported separately at that platform’s loudness level, with copy that follows its rules.' },
      { title: 'Captions', body: 'Burned-in captions that stay clear of each app’s buttons and title area. SRT files too, if you want them.' },
      { title: 'Covers', body: 'One per clip, sized and cropped for each platform’s feed.' },
      { title: 'Post copy', body: 'A title, caption and tags for every clip, within each platform’s limits and ready for you to edit.' },
      { title: 'QC report', body: 'Results for every file: what passed, why anything was marked red, and what you changed.' },
      { title: 'Publishing checklist', body: 'A suggested posting schedule and a reminder to tick the AI-content label on each platform.' },
    ],
  },
  local: {
    kicker: 'Local-first',
    title: 'Runs on your Mac, with the AI you choose',
    items: [
      { title: 'Footage stays local', body: 'Video and audio files stay on your computer; transcription and rendering run there too. Your footage never reaches us.' },
      { title: 'Bring your own AI', body: 'Use the Claude Code or Codex subscription you already have, API keys for Anthropic, OpenAI, DeepSeek, Qwen, Kimi and others, or a local model through Ollama. Only transcript text, a few keyframes and titles go to the AI you pick.' },
      { title: 'Costs you can see', body: 'About $0.03 of AI cost per clip in our test batch. With a subscription or a local model there is no separate API bill.' },
    ],
  },
  create: {
    kicker: 'Create',
    badge: 'Coming',
    title: 'From an idea to an AI video',
    body: 'Next up is a Create page: generate video from a script or idea (Kling, Seedance, MiniMax) with a shot list, a credit budget and take review, then export it per platform like any other batch. The engine’s ai-video workflow already works today.',
  },
  oss: {
    kicker: 'Open source',
    title: 'All of it is open source, MIT',
    lede: 'The desktop app, this site and the editing engine live in one repository. The engine also works on its own as a Claude Code skill called video-studio: describe the edit in English or Chinese. It covers 12 workflows, including talking-head shorts, lecture slices, podcast clips with face masking, explainers and vlogs, plus covers, captions, loudness and multi-platform export.',
    tested: 'Each workflow was tested on real footage. Known issues are listed in VALIDATION.md in the repo.',
    button: 'View on GitHub',
    skillLabel: 'Use it as a Claude Code skill',
    sourceLabel: 'Run the Mac app from source',
  },
  faq: {
    kicker: 'FAQ',
    title: 'Questions',
    items: [
      {
        q: 'Is it free?',
        a: 'Yes. Reelfold is open source under the MIT licence: the desktop app, the engine and this site are all on GitHub. You only pay for the AI service you choose, or nothing extra if you use a subscription you already have or a local model.',
      },
      {
        q: 'Which AI does it use?',
        a: 'Your choice: your logged-in Claude Code or Codex subscription (no API key needed), API keys for Anthropic, OpenAI, DeepSeek, Qwen, Kimi, GLM, OpenRouter, Gemini and others, or local models through Ollama, LM Studio or vLLM. You can pick a different one per task.',
      },
      {
        q: 'Where does my footage go?',
        a: 'Video and audio stay on your computer; transcription and rendering run locally. To pick segments, write titles and proofread captions, transcript text, a few keyframe screenshots and titles are sent to the AI service you configure, under its data policy. AI voiceover or AI video generation sends text and reference images to that vendor. The MediaPipe component used by the engine may send anonymous usage statistics to Google; the app explains how to turn that off.',
      },
      {
        q: 'Does it post for me?',
        a: 'No. Reelfold opens each platform’s own upload page in a built-in browser and fills in the video, cover, title, caption and tags. You press publish.',
      },
      {
        q: 'Windows?',
        a: 'Apple Silicon Macs only for now; Windows comes later. The engine on its own (the Claude Code skill) runs on macOS and Linux.',
      },
      {
        q: 'Do I need to label AI content when posting?',
        a: 'YouTube, TikTok, Instagram, Facebook, Xiaohongshu, Douyin, WeChat Channels, Bilibili and others have disclosure rules for AI-generated or AI-edited content; follow each platform’s current rules. The publishing checklist reminds you to tick the AI-content label by default.',
      },
      {
        q: 'What about other people in my videos (guests, students)?',
        a: 'Get their consent to use their face and voice first. Where you don’t have it, you can cover faces with stickers, blur name labels, change students’ voices, or leave that part out.',
      },
    ],
  },
  footer: {
    feedback: 'Feedback · GitHub Discussions',
    privacy: 'Privacy',
    terms: 'Terms',
    note: 'This site uses no cookies, analytics scripts or third-party fonts.',
  },
  legal: {
    draft: 'Draft, review before publishing',
    draftBody: 'This is a first draft that has not been reviewed by a lawyer. It must be checked and revised before the site goes live.',
    updated: 'Updated',
    back: 'Back to home',
    privacyTitle: 'Privacy policy',
    termsTitle: 'Terms of use',
  },
};
