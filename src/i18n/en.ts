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
    title: 'Daycut · Turn one recording into a month of short videos',
    description:
      'Daycut is an AI video studio for course and knowledge creators. Send one long recording and get clips, covers and post copy for Xiaohongshu, Douyin, WeChat Channels, Bilibili, YouTube, Shorts, X and Instagram within 72 hours, edited by AI and checked by a person.',
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
    langGroup: 'Language',
    skip: 'Skip to content',
  },
  hero: {
    eyebrow: 'An AI video studio for course and knowledge creators',
    titleA: 'Turn one lecture',
    titleB: 'into 30 days of short\u00a0videos',
    sub: 'Send us a course recording, a talk or a livestream replay. Within 72 hours you get ready-to-post clips with covers and copy for Xiaohongshu, Douyin, WeChat Channels, Bilibili, YouTube, Shorts, X and Instagram. AI does the editing, automatic checks catch problems, and a person reviews anything they flag.',
    ctaPrimary: 'Apply for a free spot (first 30)',
    ctaSecondary: 'See a real batch',
    points: [
      'You only review the clips our checks flag',
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
    title: 'One lecture in, a whole batch out',
    steps: [
      {
        title: 'Upload',
        body: 'Send one course recording, talk or livestream replay (ideally 90 minutes or less) and tell us which platforms and style you want.',
      },
      {
        title: 'Batch edit',
        body: 'AI splits the recording by topic and removes pauses, filler words and repeats. Then it adds captions, title bands, code zooms and notes panels across the whole batch.',
      },
      {
        title: 'Automatic QC',
        body: 'Every file is checked for loudness, audio/video sync, missing caption words, text hidden under app buttons, clip length and title length. Anything that fails is marked red.',
      },
      {
        title: 'Review exceptions',
        body: 'A person watches, fixes and re-renders every red clip, plus a random sample of green ones. You don’t have to watch them all.',
      },
      {
        title: 'Publish packages',
        body: 'You get one folder per platform with videos, covers, titles, captions, tags and a reminder to add the AI-content label. You do the posting.',
      },
    ],
    platformsLabel: 'Platforms',
    platforms: ['Xiaohongshu 3:4', 'Douyin 9:16', 'WeChat Channels 9:16', 'Bilibili 16:9', 'YouTube 16:9', 'YouTube Shorts 9:16', 'X 16:9 / 1:1 / 9:16', 'Instagram Reels 9:16 + feed 4:5'],
  },
  proof: {
    kicker: 'Real numbers',
    title: 'One real batch: what worked and what didn’t',
    lede: 'These numbers are from an internal test batch on one of our own 72-minute lectures, not a customer project.',
    stats: [
      { value: '96', label: 'finished files', note: '24 clips × 4 platforms, each with a cover and post copy' },
      { value: '$0.73', label: 'AI API cost for the batch', note: 'About $0.03 per clip; transcription ran locally' },
      { value: '21 / 24', label: 'clips passed automatic QC', note: 'All 3 red clips were at edit seams and went to a person' },
      { value: '3–4 h', label: 'first-run machine time', note: 'After a fix, re-running just the 13 affected clips took 18 minutes' },
    ],
    caveatsTitle: 'What isn’t good enough yet',
    caveats: [
      'Chinese captions still get some words wrong. A glossary fixes some of them and a person catches the rest.',
      'Filler-word cuts still need too many human yes/no calls (about 15 per clip in this batch). We’re working on letting the low-risk ones through automatically.',
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
    kicker: 'What you get',
    title: 'What you receive',
    items: [
      { title: 'Per-platform videos', body: 'Xiaohongshu 3:4; Douyin, WeChat Channels, Shorts and Instagram Reels 9:16; Bilibili and YouTube 16:9; X in the shape closest to your video; Instagram feed 4:5. Each one is exported separately at that platform’s loudness level, with English post copy for X and Instagram when your video is in English.' },
      { title: 'Captions', body: 'Burned-in captions that stay clear of each app’s buttons and title area. SRT files on request.' },
      { title: 'Covers', body: 'One per clip, sized and cropped for each platform’s feed.' },
      { title: 'Post copy', body: 'A title, caption and tags for every clip, within each platform’s limits and ready for you to edit.' },
      { title: 'QC report', body: 'Results for every file: what passed, why anything was marked red, and what the reviewer did about it.' },
      { title: 'Publishing checklist', body: 'A suggested posting schedule and a reminder to tick the AI-content label on each platform.' },
    ],
  },
  partner: {
    kicker: 'Design-partner program',
    title: 'Free for the first 30',
    lede: 'We’re just getting started and need honest feedback and real data. The first 30 knowledge creators get one batch free. In return, you help us find out whether this is worth paying for.',
    getTitle: 'You get',
    get: ['1 recording → 10 short clips', '1–2 platforms', 'Cover and post copy for each', 'Delivery in 72 hours'],
    giveTitle: 'In return, you agree in writing to',
    give: [
      'Let us show the batch as a case study (it can be anonymous).',
      'Share views and saves 7 days after posting (screenshots are fine).',
      'Do one 15-minute feedback call.',
      'Agree up front on a price for a second batch if you’re happy, for example ¥499 for 20 clips. You can still say no.',
    ],
    priority: 'Course and knowledge creators with recordings or livestream replays come first, then podcasters and bilingual creators. Spots are given by fit and order of application, and we reply to everyone.',
  },
  form: {
    title: 'Apply as a design partner',
    name: 'Your name',
    contact: 'Contact (email or WeChat)',
    profile: 'Profile link (Xiaohongshu, Bilibili, YouTube, ...)',
    type: 'Content type',
    typeOptions: ['Course recording', 'Talk / lecture', 'Livestream replay', 'Podcast', 'Other'],
    hours: 'Roughly how many hours of long recordings you have',
    hoursOptions: ['Under 5 hours', '5–20 hours', 'Over 20 hours'],
    platforms: 'Platforms you post on',
    platformOptions: ['Xiaohongshu', 'Douyin', 'WeChat Channels', 'YouTube', 'YouTube Shorts', 'Bilibili', 'X', 'Instagram'],
    sample: 'The recording you would start with (public link or short description, optional)',
    notes: 'Anything else (optional)',
    consentRights: 'I have the rights to this footage; other people in it have agreed, or need to be masked.',
    consentTerms: 'I understand the 4 conditions above.',
    consentPrivacy: 'I have read the privacy policy.',
    privacyLink: 'privacy policy',
    submit: 'Send application',
    required: 'required',
    offTitle: 'The online form is not open yet',
    offBody: 'For now, please apply by email with the details below. We reply to everyone.',
    offButton: 'Apply by email',
    mailSubject: 'Design partner application',
    mailBody:
      'Name:\nContact:\nProfile link:\nContent type (course / talk / livestream / podcast / other):\nHours of recordings:\nPlatforms:\nRecording to start with:\n\nI have the rights to the footage and understand the 4 conditions.',
    note: 'We only use this to contact you and check fit. We don’t sell it or share it with third parties.',
  },
  pricing: {
    kicker: 'Pricing',
    title: 'Early pricing',
    lede: 'We’re still testing these prices with pilot customers, so they will change. Design partners pay whatever second-batch price they agreed to in writing.',
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
        items: ['4 recordings a month', '80–100 clips', '2–3 platforms', 'We keep your style and glossary'],
      },
      {
        name: 'Per clip',
        price: '¥25–40',
        unit: '/ clip',
        items: ['Extra clips beyond the monthly plan, or one-off jobs', 'Same automatic QC and human review'],
      },
    ],
    currency: 'Prices are in CNY. Outside China? Email us for a quote.',
  },
  desktop: {
    kicker: 'Desktop app (preview)',
    title: 'Prefer to do it yourself?',
    lede: 'The same engine also runs as a desktop app on your own computer. Create batches, track them on a board, review clips in a grid and cut by editing the transcript. When it’s time to post, it fills in each platform’s upload page in a built-in browser, and you click publish yourself.',
    mac: 'Download for macOS',
    win: 'Download for Windows',
    note: 'This is a preview build, so features and installation will change. If the download page has no files yet, the preview isn’t open; apply as a design partner instead. You’ll need your own AI API keys.',
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
    lede: 'Under the hood is video-studio, an MIT-licensed Claude Code skill. Describe the edit in English or Chinese. It covers 12 workflows, including talking-head shorts, lecture slices, podcast clips with face masking, explainers and vlogs, plus covers, captions, loudness and multi-platform export.',
    button: 'View on GitHub',
    tested: 'Each workflow was tested on real footage. Known issues are listed in VALIDATION.md in the repo.',
  },
  faq: {
    kicker: 'FAQ',
    title: 'Privacy, rights and platform rules',
    items: [
      {
        q: 'If I use the studio service, where does my footage go?',
        a: 'You send it to us the way we agree on (for example a cloud-drive link) and we process it on our own computers, not on a cloud server. The video and audio files are not sent to AI services. To pick segments, write titles and proofread captions, the transcript text, a few keyframe screenshots and titles are sent to AI providers’ APIs (currently Anthropic and OpenAI). Transcription runs locally by default; audio goes to OpenAI for transcription only if local transcription fails and you agree.',
      },
      {
        q: 'What about the desktop app or the open-source skill?',
        a: 'Your footage stays on your own computer by default and never reaches us. As above, transcripts, keyframes and titles go to the AI services you configure, using your own API keys; AI voiceover or AI video generation sends text and reference images to that vendor. The MediaPipe component used by the engine may send anonymous usage statistics to Google; we will explain this, and how to turn it off, inside the app.',
      },
      {
        q: 'What do the AI providers do with that data?',
        a: 'It is handled under each provider’s API data policy, which decides retention and whether it is used for training. The privacy policy links to those policies so you can check them yourself.',
      },
      {
        q: 'Do I need to label AI content when posting?',
        a: 'Xiaohongshu, Douyin, WeChat Channels, Bilibili, YouTube, Instagram and others have disclosure or label rules for AI-generated or AI-edited content; follow each platform’s current rules. Our publishing checklist reminds you to tick the AI-content label by default. We do not log in to your accounts or post for you.',
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
    title: 'Questions? Send us an email',
    body: 'Partnerships, questions and data-deletion requests all go to this address. For the open-source skill, you can also open a GitHub issue.',
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
