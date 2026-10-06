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
    title: 'video-studio · Turn one lecture into 30 days of short videos',
    description:
      'An AI-native video studio for course and knowledge creators: AI editing, automatic QC and human review. Clips, covers and post copy for Xiaohongshu, Douyin, WeChat Channels, YouTube and Shorts in 72 hours.',
  },
  nav: {
    how: 'How it works',
    proof: 'Real numbers',
    deliverables: 'What you get',
    partner: 'Design partners',
    pricing: 'Pricing',
    desktop: 'Desktop app',
    faq: 'FAQ',
    cta: 'Apply',
    switchLabel: '中文',
    switchAria: '切换到中文',
    skip: 'Skip to content',
  },
  hero: {
    eyebrow: 'An AI video studio for course and knowledge creators',
    titleA: 'Turn one lecture',
    titleB: 'into 30 days of short videos',
    sub: 'Send us a course recording, a talk or a livestream replay. AI editing, automatic QC and human review give you ready-to-post clips, covers and copy for Xiaohongshu, Douyin, WeChat Channels, YouTube and Shorts within 72 hours.',
    ctaPrimary: 'Apply for a free spot (first 30)',
    ctaSecondary: 'See a real batch',
    points: [
      'You only look at the exceptions QC flags',
      'Every clip comes with a cover, title, caption and tags',
      'We never log in to your accounts; you press publish',
    ],
    stickerA: 'Xiaohongshu 3:4',
    stickerB: 'QC passed',
    stickerC: '1 lecture → 24 clips',
    frameAlts: [
      'Talking-head short with captions and a notes panel',
      'Lecture slice showing code with a title band about hybrid retrieval',
      'Knowledge video with two speakers and a notes panel',
    ],
  },
  how: {
    kicker: 'How it works',
    title: 'A whole lecture at once, not one clip at a time',
    steps: [
      {
        title: 'Upload',
        body: 'Send one course recording, talk or livestream replay (ideally 90 minutes or less) and tell us the platforms and style you want.',
      },
      {
        title: 'Batch edit',
        body: 'AI picks segments by topic, removes pauses, filler words and repeats, then adds captions, title bands, code zooms and notes panels for the whole batch.',
      },
      {
        title: 'Automatic QC',
        body: 'Every file is checked: loudness, audio/video sync, missing words in captions, overlap with platform buttons, length and title length. Failures turn red.',
      },
      {
        title: 'Review exceptions',
        body: 'A person watches, fixes and re-renders the red clips plus a random sample of green ones. You do not have to watch everything.',
      },
      {
        title: 'Publish packages',
        body: 'One folder per platform: videos, covers, titles, captions, tags and a reminder to add the AI-content label. You publish them yourself.',
      },
    ],
    platformsLabel: 'Platforms',
    platforms: ['Xiaohongshu 3:4', 'Douyin 9:16', 'WeChat Channels 9:16', 'YouTube 16:9', 'YouTube Shorts 9:16'],
  },
  proof: {
    kicker: 'Real numbers',
    title: 'One real batch, the good and the not yet good',
    lede: 'These numbers come from an internal test batch we ran on one of our own 72-minute lectures. It is not a customer case.',
    stats: [
      { value: '96', label: 'finished files', note: '24 clips × 4 platforms, each with a cover and post copy' },
      { value: '$0.73', label: 'AI API cost for the batch', note: 'About $0.03 per clip; transcription ran locally' },
      { value: '21 / 24', label: 'clips passed automatic QC', note: 'All 3 red clips were at edit seams and went to human review' },
      { value: '3–4 h', label: 'first-run machine time', note: 'After a fix, an incremental re-run of 13 clips took 18 minutes' },
    ],
    caveatsTitle: 'What is not good enough yet',
    caveats: [
      'Chinese captions still mishear some words. A glossary fixes part of it; a person catches the rest.',
      'Too many filler-word cuts still need a human yes or no (about 15 per clip in this batch). We are making low-risk types pass automatically.',
      'When the on-screen text in the source is small, it is hard to read in a vertical crop.',
    ],
    stripCaption: 'Frames from six kinds of edits made with the same tools: talking head, lecture slices, photo story, travel vlog, podcast with face masking, explainer.',
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
    kicker: 'What you get',
    title: 'What lands in your folder',
    items: [
      { title: 'Per-platform videos', body: 'Xiaohongshu 3:4; Douyin, WeChat Channels and Shorts 9:16; YouTube 16:9 when you need it. Each exported separately at the platform loudness.' },
      { title: 'Captions', body: 'Burned-in captions placed clear of each app’s buttons and title area. SRT files on request.' },
      { title: 'Covers', body: 'One per clip, sized and cropped for each platform’s feed.' },
      { title: 'Post copy', body: 'Title, caption and tags for every clip, within each platform’s limits, ready for you to edit.' },
      { title: 'QC report', body: 'Results for every file: what passed, why something was red, and what the reviewer did about it.' },
      { title: 'Publishing checklist', body: 'A suggested posting schedule and a reminder to tick the AI-content label on each platform.' },
    ],
  },
  partner: {
    kicker: 'Design-partner program',
    title: 'Free for the first 30',
    lede: 'We are just starting and need honest feedback and real data. The first 30 knowledge creators get one batch free, in exchange for helping us find out whether this is worth paying for.',
    getTitle: 'You get',
    get: ['1 recording → 10 short clips', '1–2 platforms', 'Cover and post copy for each', 'Delivery in 72 hours'],
    giveTitle: 'You agree to (in writing)',
    give: [
      'Let us show the batch as a case study; anonymous is fine.',
      'Send us views and saves 7 days after posting (screenshots are fine).',
      'One 15-minute feedback interview.',
      'Agree on a second-batch price up front, for example ¥499 for 20 clips if you are happy. You can say no.',
    ],
    priority: 'We prioritise course and knowledge creators with recordings or livestream replays, then podcasters and bilingual creators. Spots are confirmed by fit and order of application; we reply to everyone.',
  },
  form: {
    title: 'Apply as a design partner',
    name: 'Your name',
    contact: 'Contact (email or WeChat)',
    profile: 'Profile link (Xiaohongshu, Bilibili, YouTube, ...)',
    type: 'Content type',
    typeOptions: ['Course recording', 'Talk / lecture', 'Livestream replay', 'Podcast', 'Other'],
    hours: 'Roughly how many hours of long recordings',
    hoursOptions: ['Under 5 hours', '5–20 hours', 'Over 20 hours'],
    platforms: 'Platforms you post on',
    platformOptions: ['Xiaohongshu', 'Douyin', 'WeChat Channels', 'YouTube', 'YouTube Shorts', 'Bilibili'],
    sample: 'The recording you would start with (public link or short description, optional)',
    notes: 'Anything else (optional)',
    consentRights: 'I have the rights to this footage; other people in it have agreed, or need to be masked.',
    consentTerms: 'I understand the 4 conditions above.',
    consentPrivacy: 'I have read the privacy policy.',
    privacyLink: 'privacy policy',
    submit: 'Send application',
    required: 'required',
    offTitle: 'The online form is not open yet',
    offBody: 'Please apply by email for now, with the details below. We reply to everyone.',
    offButton: 'Apply by email',
    mailSubject: 'Design partner application',
    mailBody:
      'Name:\nContact:\nProfile link:\nContent type (course / talk / livestream / podcast / other):\nHours of recordings:\nPlatforms:\nRecording to start with:\n\nI have the rights to the footage and understand the 4 conditions.',
    note: 'We use this only to contact you and check fit. We do not sell it or pass it to third parties.',
  },
  pricing: {
    kicker: 'Pricing',
    title: 'Early pricing',
    lede: 'These are early prices we are still testing with pilots, and they will change. For design partners, the second-batch price is whatever you agreed to in writing.',
    badge: 'Early pricing',
    plans: [
      {
        name: 'Pilot',
        price: '¥499',
        unit: '/ batch',
        items: ['1 recording (up to 90 min)', '20 clips × 2 platforms', 'Covers and post copy', 'Delivery in 72 hours'],
      },
      {
        name: 'Monthly',
        price: '¥2,999–4,999',
        unit: '/ month',
        items: ['4 recordings a month', '80–100 clips', '2–3 platforms', 'Your style and glossary, kept'],
      },
      {
        name: 'Per clip',
        price: '¥25–40',
        unit: '/ clip',
        items: ['Beyond the monthly plan, or one-off needs', 'Same automatic QC and human review'],
      },
    ],
    currency: 'Prices in CNY. Creators outside China: email us for a quote.',
  },
  desktop: {
    kicker: 'Desktop app (preview)',
    title: 'Prefer to do it yourself?',
    lede: 'The same engine runs in a desktop workbench on your own computer: create batches, watch progress on a board, review in a grid, cut by editing the transcript. When you publish, it fills in the platform’s page in a built-in browser and you press the publish button yourself.',
    mac: 'Download for macOS',
    win: 'Download for Windows',
    note: 'Preview build; features and installation will change. If the download page has no files yet, it is not open; apply as a design partner instead. You bring your own AI API keys.',
    board: {
      cols: ['Queued', 'Rendering', 'QC', 'Review', 'Approved'],
      cards: ['ep03 · RRF ranks only', 'ep06 · small chunks', 'ep11 · which metric first', 'ep14 · parent-child', 'ep19 · reranking'],
      green: 'green',
      red: 'red · word may be lost at seam',
      caption: 'Illustration of the batch board (not a screenshot).',
    },
  },
  oss: {
    kicker: 'Open source',
    title: 'The editing engine is open source',
    lede: 'Underneath is video-studio, a Claude Code skill under the MIT licence. Describe the edit in Chinese or English: talking-head shorts, lecture slices, podcast clips with face masking, explainers, vlogs and more across 12 workflows, plus covers, captions, loudness and multi-platform export.',
    button: 'View on GitHub',
    tested: 'Each workflow was tested on real footage; known issues are listed in VALIDATION.md in the repo.',
  },
  faq: {
    kicker: 'FAQ',
    title: 'Privacy, rights and platform rules',
    items: [
      {
        q: 'With the studio service, where does my footage go?',
        a: 'You send it to us the way we agree on (for example a cloud-drive link) and we process it on our own computers, not on a cloud server. The video and audio files are not sent to AI services. To pick segments, write titles and proofread captions, the transcript text, a few keyframe screenshots and titles are sent to AI providers’ APIs (currently Anthropic and OpenAI). Transcription runs locally by default; audio goes to OpenAI for transcription only if local transcription fails and you agree.',
      },
      {
        q: 'And with the desktop app or the open-source skill?',
        a: 'Your footage stays on your own computer by default and never reaches us. As above, transcripts, keyframes and titles go to the AI services you configure, using your own API keys; AI voiceover or AI video generation sends text and reference images to that vendor. The MediaPipe component used by the engine may send anonymous usage statistics to Google; we will explain this, and how to turn it off, inside the app.',
      },
      {
        q: 'What do the AI providers do with that data?',
        a: 'It is handled under each provider’s API data policy, which decides retention and whether it is used for training. The privacy policy links to those policies so you can check them yourself.',
      },
      {
        q: 'Do I need to label AI content when posting?',
        a: 'Xiaohongshu, Douyin, WeChat Channels, YouTube and others have disclosure or label rules for AI-generated or AI-edited content; follow each platform’s current rules. Our publishing checklist reminds you to tick the AI-content label by default. We do not log in to your accounts or post for you.',
      },
      {
        q: 'What about other people in my videos (guests, students)?',
        a: 'You confirm you have their consent to use their face and voice. Where you do not, we can cover faces with stickers, blur name labels, change students’ voices, or leave that part out.',
      },
      {
        q: 'When is my data deleted?',
        a: 'By default, your source footage and intermediate files are deleted within 30 days of delivery. Email us any time to delete earlier; we act within 7 days and confirm by reply. Data already sent to AI providers follows their retention policies, and we cannot delete it on their behalf.',
      },
      {
        q: 'When do the 72 hours start?',
        a: 'Once all the footage has arrived and the brief is confirmed. If we are going to be late, we tell you in advance.',
      },
      {
        q: 'Who owns the videos?',
        a: 'You own your footage and the finished clips. Case studies are shown only as far as you agreed in writing, and can be anonymous.',
      },
    ],
  },
  contact: {
    kicker: 'Contact',
    title: 'Questions? Email us',
    body: 'Partnerships, questions and data-deletion requests all go to this address. For the open-source skill you can also open a GitHub issue.',
    github: 'GitHub issues',
  },
  footer: {
    privacy: 'Privacy',
    terms: 'Terms',
    note: 'This site uses no cookies, analytics scripts or third-party fonts.',
  },
  legal: {
    draft: 'Draft, review before publishing',
    draftBody: 'This is a first draft that has not been reviewed by a lawyer. It must be checked and revised before the site goes live.',
    updated: 'Updated',
    back: 'Back to home',
  },
};
