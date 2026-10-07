// Comparison pages. Honest format (IMPLEMENTATION.md §6.9): what the other tool does well, where Reelfold differs,
// a yes / no / partial table checked against each tool's own public pages on CHECKED, and the sources.
// Anything we could not confirm on a primary source is shown as "not verified", never guessed.
// Re-check every row before changing CHECKED.
import type { Lang } from '../i18n';
import { SITE } from '../config';

export const COMPARE = ['opus-clip', 'descript', 'capcut'] as const;
export type CompareSlug = (typeof COMPARE)[number];
export const CHECKED = '2026-10-07';

export type V = 'yes' | 'no' | 'partial' | 'unknown';
export const ROWS = ['free', 'oss', 'local', 'mac', 'win', 'web', 'mobile', 'batch', 'byoai', 'post', 'cn', 'text', 'filler', 'pick', 'team'] as const;
export type Row = (typeof ROWS)[number];

/** Row labels and cell words per language. */
export const LABELS: Record<Lang, Record<Row, string> & Record<V, string> & { feature: string; tableCaption: string }> = {
  en: {
    feature: 'Feature', tableCaption: 'Checked against each product’s public pages on {date}. Prices and features change; follow the sources below.',
    yes: 'Yes', no: 'No', partial: 'Partly', unknown: 'Not verified',
    free: 'Free to use', oss: 'Open source', local: 'Renders on your own computer', mac: 'macOS app', win: 'Windows app', web: 'Works in a browser',
    mobile: 'Phone app', batch: 'Many recordings in one batch', byoai: 'Bring your own AI model', post: 'Posts or schedules for you',
    cn: 'Chinese platform formats (Xiaohongshu, Douyin, Bilibili, WeChat Channels)', text: 'Edit by transcript', filler: 'Filler-word removal',
    pick: 'AI picks clips from a long video', team: 'Team workspaces',
  },
  zh: {
    feature: '功能', tableCaption: '于 {date} 对照各产品的公开页面核对。价格和功能会变，请以下方来源为准。',
    yes: '有', no: '没有', partial: '部分', unknown: '未核实',
    free: '可免费使用', oss: '开源', local: '在你自己的电脑上渲染', mac: 'macOS 应用', win: 'Windows 应用', web: '浏览器里使用',
    mobile: '手机应用', batch: '一批处理多条录像', byoai: '接入你自己的 AI 模型', post: '替你发布或定时发布',
    cn: '国内平台尺寸（小红书、抖音、B站、视频号）', text: '改文字稿来剪辑', filler: '去口头禅',
    pick: 'AI 从长视频里挑片段', team: '团队协作空间',
  },
  fr: {
    feature: 'Fonction', tableCaption: 'Vérifié sur les pages publiques de chaque produit le {date}. Prix et fonctions évoluent ; référez-vous aux sources ci-dessous.',
    yes: 'Oui', no: 'Non', partial: 'En partie', unknown: 'Non vérifié',
    free: 'Utilisable gratuitement', oss: 'Open source', local: 'Rendu sur votre propre ordinateur', mac: 'App macOS', win: 'App Windows', web: 'Dans le navigateur',
    mobile: 'App mobile', batch: 'Plusieurs enregistrements en un lot', byoai: 'Votre propre modèle d’IA', post: 'Publie ou programme à votre place',
    cn: 'Formats des plateformes chinoises (Xiaohongshu, Douyin, Bilibili, WeChat Channels)', text: 'Montage par la transcription', filler: 'Retrait des hésitations',
    pick: 'L’IA choisit les clips d’une longue vidéo', team: 'Espaces d’équipe',
  },
  es: {
    feature: 'Función', tableCaption: 'Comprobado en las páginas públicas de cada producto el {date}. Los precios y las funciones cambian; consulta las fuentes de abajo.',
    yes: 'Sí', no: 'No', partial: 'En parte', unknown: 'Sin verificar',
    free: 'Se puede usar gratis', oss: 'Código abierto', local: 'Renderiza en tu propio equipo', mac: 'App para macOS', win: 'App para Windows', web: 'Funciona en el navegador',
    mobile: 'App para móvil', batch: 'Varias grabaciones en un lote', byoai: 'Usa tu propio modelo de IA', post: 'Publica o programa por ti',
    cn: 'Formatos de plataformas chinas (Xiaohongshu, Douyin, Bilibili, WeChat Channels)', text: 'Editar desde la transcripción', filler: 'Quitar muletillas',
    pick: 'La IA elige clips de un video largo', team: 'Espacios de equipo',
  },
};

/** Reelfold's own column (same for every page). Notes per language where a bare yes/no would mislead. */
export const REELFOLD: Record<Row, V> = {
  free: 'yes', oss: 'yes', local: 'yes', mac: SITE.downloadReady ? 'yes' : 'partial', win: 'no', web: 'no', mobile: 'no', batch: 'yes',
  byoai: 'yes', post: 'no', cn: 'yes', text: 'yes', filler: 'yes', pick: 'yes', team: 'no',
};
export const REELFOLD_NOTES: Record<Lang, Partial<Record<Row, string>>> = {
  en: { mac: SITE.downloadReady ? 'Apple Silicon' : 'Apple Silicon; first release coming soon, build from source today', win: 'Planned', post: 'By design: fills each upload page, you press publish', free: 'MIT; you pay only for the AI you connect' },
  zh: { mac: SITE.downloadReady ? 'Apple 芯片' : 'Apple 芯片；正式版即将发布，现在可从源码构建', win: '在计划中', post: '有意为之：替你填好上传页，由你按下发布', free: 'MIT；只为你接入的 AI 付费' },
  fr: { mac: SITE.downloadReady ? 'Apple Silicon' : 'Apple Silicon ; première version bientôt, compilable dès aujourd’hui', win: 'Prévue', post: 'Choix délibéré : il remplit chaque page, vous publiez', free: 'MIT ; seule l’IA branchée est payante' },
  es: { mac: SITE.downloadReady ? 'Apple Silicon' : 'Apple Silicon; primera versión muy pronto, ya se puede compilar', win: 'Prevista', post: 'A propósito: rellena cada página de subida y tú publicas', free: 'MIT; solo pagas la IA que conectes' },
};

interface Item { t: string; b: string }
export interface ComparePage {
  name: string; title: string; description: string; kicker: string; h1: string; intro: string;
  theyT: string; they: Item[]; weT: string; we: Item[];
  chooseT: string; choose: Item[];
  values: Record<Row, V>; notes: Partial<Record<Row, string>>;
  faq: { q: string; a: string }[];
}
export interface CompareEntry { sources: { label: string; url: string }[]; byLang: Record<Lang, ComparePage> }

// ----------------------------------------------------------------------------- shared values per tool
const OPUS_V: Record<Row, V> = { free: 'yes', oss: 'no', local: 'no', mac: 'no', win: 'no', web: 'yes', mobile: 'unknown', batch: 'partial', byoai: 'no', post: 'yes', cn: 'no', text: 'unknown', filler: 'unknown', pick: 'yes', team: 'yes' };
const DESCRIPT_V: Record<Row, V> = { free: 'yes', oss: 'no', local: 'unknown', mac: 'yes', win: 'yes', web: 'yes', mobile: 'unknown', batch: 'unknown', byoai: 'no', post: 'partial', cn: 'unknown', text: 'yes', filler: 'yes', pick: 'yes', team: 'yes' };
const CAPCUT_V: Record<Row, V> = { free: 'yes', oss: 'no', local: 'unknown', mac: 'yes', win: 'yes', web: 'yes', mobile: 'yes', batch: 'unknown', byoai: 'no', post: 'unknown', cn: 'unknown', text: 'unknown', filler: 'unknown', pick: 'yes', team: 'unknown' };

const DATA: Record<CompareSlug, CompareEntry> = {
  'opus-clip': {
    sources: [
      { label: 'Opus Clip pricing (plans, features per plan, posting platforms)', url: 'https://www.opus.pro/pricing' },
      { label: 'Opus Clip help: supported video languages', url: 'https://help.opus.pro/docs/article/video-languages-supported' },
      { label: 'Opus Clip API', url: 'https://www.opus.pro/api' },
    ],
    byLang: {
      en: {
        name: 'Opus Clip',
        title: 'Reelfold vs Opus Clip: an open-source alternative for batches | Reelfold',
        description: 'An honest comparison of Reelfold and Opus Clip: hosted clipping in the browser vs a free, open-source Mac app that renders locally, uses your own AI and covers Chinese platforms. Checked October 2026.',
        kicker: 'Compare',
        h1: 'Reelfold and Opus Clip, side by side.',
        intro: 'Both turn a long video into short clips with AI. Opus Clip is a hosted web service with credits and a built-in scheduler. Reelfold is a free, open-source Mac app that renders on your machine with the AI you bring. Here is where each one fits.',
        theyT: 'Where Opus Clip is strong',
        they: [
          { t: 'Nothing to install', b: 'It runs in the browser on any computer, including Windows, and imports straight from links such as YouTube.' },
          { t: 'Posting built in', b: 'Paid plans post and schedule to YouTube Shorts, TikTok, Instagram, LinkedIn, Facebook and X.' },
          { t: 'Teams and brand templates', b: 'Shared workspaces, brand templates and, on higher plans, analytics and an API.' },
        ],
        weT: 'Where Reelfold is different',
        we: [
          { t: 'Local and private', b: 'Cutting and rendering happen on your Mac. There is no upload queue and no per-minute credit.' },
          { t: 'Your own AI', b: 'Use a Claude Code or Codex subscription, an API key or a local model. The 72-minute batch on our home page cost $0.73.' },
          { t: 'Chinese platforms', b: 'Profiles for Xiaohongshu, Douyin, WeChat Channels, Bilibili, Kuaishou, Weibo and Zhihu, plus Chinese captions and fillers.' },
          { t: 'Open source', b: 'MIT licensed. Read the code, change a workflow, or run the engine as a Claude Code skill.' },
        ],
        chooseT: 'Which one to pick',
        choose: [
          { t: 'Pick Opus Clip if', b: 'you want clips from a link, on any computer, with posting and a team workspace handled for you.' },
          { t: 'Pick Reelfold if', b: 'you have a Mac, post to Chinese or many platforms, want your recordings to stay local, or want to pay only for the AI you already use.' },
        ],
        values: OPUS_V,
        notes: { free: 'Free plan with limits; paid plans from $15/month', local: 'Processing runs on Opus Clip’s servers', batch: 'Parallel processing through the API on higher plans', post: 'Scheduler on paid plans', cn: 'Not among its posting targets; Chinese not in its listed video languages', team: 'Pro: up to 4 users; Business: unlimited' },
        faq: [
          { q: 'Is Reelfold a free Opus Clip alternative?', a: 'Reelfold is free and open source, and it also picks clips from long videos. It runs on your Mac instead of in the browser, so it suits people who want local processing and their own AI.' },
          { q: 'Can Reelfold post for me like Opus Clip?', a: 'No, on purpose. Reelfold fills in each platform’s upload page with the video, cover and copy, and you press publish.' },
        ],
      },
      zh: {
        name: 'Opus Clip',
        title: '千剪和 Opus Clip 对比：开源、可批量的替代方案 | 千剪',
        description: '如实对比千剪和 Opus Clip：一个是在浏览器里用的托管剪辑服务，一个是免费开源、在 Mac 本机渲染、用你自己的 AI、支持国内平台的应用。2026 年 10 月核对。',
        kicker: '对比',
        h1: '千剪和 Opus Clip，放在一起看。',
        intro: '两者都用 AI 把长视频剪成短片。Opus Clip 是按点数计费、自带定时发布的托管网页服务；千剪是免费开源的 Mac 应用，用你自己的 AI 在本机渲染。下面说清楚各自适合谁。',
        theyT: 'Opus Clip 擅长的',
        they: [
          { t: '不用安装', b: '在任何电脑的浏览器里都能用，包括 Windows，也能直接从 YouTube 等链接导入。' },
          { t: '自带发布', b: '付费版可以发布和定时发布到 YouTube Shorts、TikTok、Instagram、LinkedIn、Facebook 和 X。' },
          { t: '团队与品牌模板', b: '共享工作区、品牌模板；更高的套餐还有数据分析和 API。' },
        ],
        weT: '千剪不一样的地方',
        we: [
          { t: '本机、私密', b: '剪辑和渲染都在你的 Mac 上完成。没有上传排队，也没有按分钟计的点数。' },
          { t: '用你自己的 AI', b: '用 Claude Code 或 Codex 订阅、API Key 或本地模型。首页那批 72 分钟的录像，AI 费用是 0.73 美元。' },
          { t: '国内平台', b: '内置小红书、抖音、视频号、B站、快手、微博、知乎的规格，中文字幕和中文口头禅也能处理。' },
          { t: '开源', b: 'MIT 协议。可以读代码、改工作流，或者把引擎当作 Claude Code 技能来用。' },
        ],
        chooseT: '该选哪个',
        choose: [
          { t: '选 Opus Clip，如果', b: '你想直接从一个链接拿到片段，在任何电脑上都能用，发布和团队协作都替你管好。' },
          { t: '选千剪，如果', b: '你用 Mac、要发国内平台或很多平台、希望录像留在本机，或者只想为你已经在用的 AI 付费。' },
        ],
        values: OPUS_V,
        notes: { free: '免费版有额度限制；付费版每月 15 美元起', local: '在 Opus Clip 的服务器上处理', batch: '更高套餐可通过 API 并行处理', post: '付费版有定时发布', cn: '发布平台里没有国内平台；支持的视频语言里没有中文', team: 'Pro 至多 4 人；Business 不限人数' },
        faq: [
          { q: '千剪能当免费的 Opus Clip 替代品吗？', a: '千剪免费开源，也能从长视频里挑片段。它在你的 Mac 上运行而不是在浏览器里，适合希望本机处理、用自己 AI 的人。' },
          { q: '千剪能像 Opus Clip 那样替我发布吗？', a: '不能，这是有意的。千剪把视频、封面和文案填进各平台的上传页，由你按下发布。' },
        ],
      },
      fr: {
        name: 'Opus Clip',
        title: 'Reelfold ou Opus Clip : une alternative open source pour les lots | Reelfold',
        description: 'Comparaison honnête de Reelfold et d’Opus Clip : un service de découpe hébergé dans le navigateur, face à une app Mac gratuite et open source qui rend en local, avec votre IA et les plateformes chinoises. Vérifié en octobre 2026.',
        kicker: 'Comparer',
        h1: 'Reelfold et Opus Clip, côte à côte.',
        intro: 'Les deux transforment une longue vidéo en clips courts grâce à l’IA. Opus Clip est un service web hébergé, avec des crédits et une programmation intégrée. Reelfold est une app Mac gratuite et open source qui rend sur votre machine, avec l’IA de votre choix. Voici à qui chacun convient.',
        theyT: 'Les points forts d’Opus Clip',
        they: [
          { t: 'Rien à installer', b: 'Il fonctionne dans le navigateur sur n’importe quel ordinateur, Windows compris, et importe directement depuis un lien, YouTube par exemple.' },
          { t: 'Publication intégrée', b: 'Les offres payantes publient et programment sur YouTube Shorts, TikTok, Instagram, LinkedIn, Facebook et X.' },
          { t: 'Équipes et modèles de marque', b: 'Espaces partagés, modèles de marque et, sur les offres supérieures, statistiques et API.' },
        ],
        weT: 'Ce qui distingue Reelfold',
        we: [
          { t: 'Local et privé', b: 'Coupes et rendu se font sur votre Mac. Pas de file d’envoi, pas de crédit à la minute.' },
          { t: 'Votre propre IA', b: 'Un abonnement Claude Code ou Codex, une clé d’API ou un modèle local. Le lot de 72 minutes de notre page d’accueil a coûté 0,73 $.' },
          { t: 'Plateformes chinoises', b: 'Profils pour Xiaohongshu, Douyin, WeChat Channels, Bilibili, Kuaishou, Weibo et Zhihu, avec sous-titres et hésitations en chinois.' },
          { t: 'Open source', b: 'Licence MIT. Lisez le code, modifiez un workflow, ou utilisez le moteur comme skill Claude Code.' },
        ],
        chooseT: 'Lequel choisir',
        choose: [
          { t: 'Choisissez Opus Clip si', b: 'vous voulez des clips à partir d’un simple lien, sur n’importe quel ordinateur, avec la publication et l’équipe gérées pour vous.' },
          { t: 'Choisissez Reelfold si', b: 'vous avez un Mac, publiez sur les plateformes chinoises ou sur beaucoup de plateformes, voulez garder vos enregistrements en local, ou ne payer que l’IA que vous utilisez déjà.' },
        ],
        values: OPUS_V,
        notes: { free: 'Offre gratuite limitée ; offres payantes dès 15 $/mois', local: 'Le traitement se fait sur les serveurs d’Opus Clip', batch: 'Traitement en parallèle via l’API sur les offres supérieures', post: 'Programmation sur les offres payantes', cn: 'Absentes de ses cibles de publication ; chinois absent des langues vidéo listées', team: 'Pro : jusqu’à 4 personnes ; Business : illimité' },
        faq: [
          { q: 'Reelfold est-il une alternative gratuite à Opus Clip ?', a: 'Reelfold est gratuit et open source, et il choisit lui aussi des clips dans les longues vidéos. Il tourne sur votre Mac plutôt que dans le navigateur : il convient à qui veut un traitement local et sa propre IA.' },
          { q: 'Reelfold peut-il publier pour moi comme Opus Clip ?', a: 'Non, et c’est voulu. Reelfold remplit la page de mise en ligne de chaque plateforme avec la vidéo, la couverture et le texte, et c’est vous qui publiez.' },
        ],
      },
      es: {
        name: 'Opus Clip',
        title: 'Reelfold vs Opus Clip: una alternativa de código abierto para lotes | Reelfold',
        description: 'Comparación honesta entre Reelfold y Opus Clip: un servicio alojado que corta en el navegador frente a una app gratuita y de código abierto para Mac que renderiza en local, usa tu IA y cubre plataformas chinas. Revisado en octubre de 2026.',
        kicker: 'Comparar',
        h1: 'Reelfold y Opus Clip, lado a lado.',
        intro: 'Los dos convierten un video largo en clips cortos con IA. Opus Clip es un servicio web alojado, con créditos y programación integrada. Reelfold es una app gratuita y de código abierto para Mac que renderiza en tu equipo con la IA que tú elijas. Así encaja cada uno.',
        theyT: 'Dónde destaca Opus Clip',
        they: [
          { t: 'Nada que instalar', b: 'Funciona en el navegador de cualquier computadora, Windows incluido, e importa directamente desde enlaces como YouTube.' },
          { t: 'Publicación integrada', b: 'Los planes de pago publican y programan en YouTube Shorts, TikTok, Instagram, LinkedIn, Facebook y X.' },
          { t: 'Equipos y plantillas de marca', b: 'Espacios compartidos, plantillas de marca y, en los planes superiores, estadísticas y API.' },
        ],
        weT: 'En qué es distinto Reelfold',
        we: [
          { t: 'Local y privado', b: 'Los cortes y el renderizado se hacen en tu Mac. Sin colas de subida ni créditos por minuto.' },
          { t: 'Tu propia IA', b: 'Una suscripción de Claude Code o Codex, una clave de API o un modelo local. El lote de 72 minutos de nuestra página de inicio costó 0,73 US$.' },
          { t: 'Plataformas chinas', b: 'Perfiles para Xiaohongshu, Douyin, WeChat Channels, Bilibili, Kuaishou, Weibo y Zhihu, con subtítulos y muletillas en chino.' },
          { t: 'Código abierto', b: 'Licencia MIT. Lee el código, cambia un flujo de trabajo o usa el motor como skill de Claude Code.' },
        ],
        chooseT: 'Cuál elegir',
        choose: [
          { t: 'Elige Opus Clip si', b: 'quieres clips a partir de un enlace, en cualquier computadora, con la publicación y el equipo resueltos por ti.' },
          { t: 'Elige Reelfold si', b: 'tienes un Mac, publicas en plataformas chinas o en muchas plataformas, quieres que tus grabaciones se queden en local o pagar solo la IA que ya usas.' },
        ],
        values: OPUS_V,
        notes: { free: 'Plan gratuito con límites; planes de pago desde 15 US$/mes', local: 'El procesamiento ocurre en los servidores de Opus Clip', batch: 'Procesamiento en paralelo vía API en planes superiores', post: 'Programación en los planes de pago', cn: 'No están entre sus destinos de publicación; el chino no figura entre sus idiomas de video', team: 'Pro: hasta 4 personas; Business: sin límite' },
        faq: [
          { q: '¿Reelfold es una alternativa gratuita a Opus Clip?', a: 'Reelfold es gratis y de código abierto, y también elige clips de videos largos. Funciona en tu Mac en lugar del navegador, así que encaja con quien quiere procesar en local y con su propia IA.' },
          { q: '¿Reelfold puede publicar por mí como Opus Clip?', a: 'No, a propósito. Reelfold rellena la página de subida de cada plataforma con el video, la portada y el texto, y tú pulsas publicar.' },
        ],
      },
    },
  },

  descript: {
    sources: [
      { label: 'Descript pricing (plans, media hours, features)', url: 'https://www.descript.com/pricing' },
      { label: 'Descript clips', url: 'https://www.descript.com/clips' },
      { label: 'Descript system requirements', url: 'https://help.descript.com/getting-started/descript-system-requirements' },
    ],
    byLang: {
      en: {
        name: 'Descript',
        title: 'Reelfold vs Descript: a batch-first Descript alternative for Mac | Reelfold',
        description: 'An honest comparison of Reelfold and Descript: a polished text-based editor for one video at a time vs a free, open-source Mac app that turns one recording into a week of clips. Checked October 2026.',
        kicker: 'Compare',
        h1: 'Reelfold and Descript, side by side.',
        intro: 'Descript is an editor: you shape one video by editing its transcript, with strong audio tools and collaboration. Reelfold is a batch tool: one recording becomes many clips for many platforms, rendered on your Mac. Many people could use both.',
        theyT: 'Where Descript is strong',
        they: [
          { t: 'Editing by transcript', b: 'A mature, polished editor where deleting a word deletes it from the video, with multitrack and screen recording.' },
          { t: 'Audio tools', b: 'Studio Sound, filler-word removal and, on higher plans, translation and dubbing.' },
          { t: 'Collaboration everywhere', b: 'Desktop apps for Mac and Windows, a web app, and shared projects for teams.' },
        ],
        weT: 'Where Reelfold is different',
        we: [
          { t: 'Batches, not one timeline', b: 'Plan 24 clips from one recording, run them in parallel and look only at the ones its checks flag.' },
          { t: 'Twenty platform profiles', b: 'Each clip comes out per platform with captions inside the safe area, a cover, loudness set and copy within limits.' },
          { t: 'Local, with your own AI', b: 'Rendering happens on your Mac; planning uses the AI you choose, including a local model.' },
          { t: 'Free and open source', b: 'No media-hour quota. MIT licensed, with the engine also available as a Claude Code skill.' },
        ],
        chooseT: 'Which one to pick',
        choose: [
          { t: 'Pick Descript if', b: 'you craft one video at a time, need serious audio cleanup, record your screen, or work with a team on Windows and Mac.' },
          { t: 'Pick Reelfold if', b: 'you have long recordings to turn into many clips for many platforms, including Chinese ones, and want it done on your own Mac.' },
        ],
        values: DESCRIPT_V,
        notes: { free: 'Free plan: 60 media minutes a month, 720p with watermark; paid from $16/month billed yearly', mac: 'macOS 14 or later', win: 'Windows 11', post: 'Publishes directly to YouTube', pick: 'Underlord “Create clips”' },
        faq: [
          { q: 'Is Reelfold a Descript alternative?', a: 'For turning long recordings into many platform-ready clips, yes. For detailed editing of a single video, Descript does more. Reelfold has a transcript-based clip editor, but its focus is the batch.' },
          { q: 'Can I use both?', a: 'Yes. Some people polish a long video in Descript, export it, and let Reelfold cut the week of clips from that export.' },
        ],
      },
      zh: {
        name: 'Descript',
        title: '千剪和 Descript 对比：Mac 上以批量为主的替代方案 | 千剪',
        description: '如实对比千剪和 Descript：一个是一次精修一条视频、按文字稿剪辑的成熟编辑器，一个是把一条录像剪成一周短片的免费开源 Mac 应用。2026 年 10 月核对。',
        kicker: '对比',
        h1: '千剪和 Descript，放在一起看。',
        intro: 'Descript 是编辑器：通过改文字稿来精修一条视频，音频工具强，适合协作。千剪是批量工具：一条录像剪成发往很多平台的很多条，在你的 Mac 上渲染。很多人两个都用得上。',
        theyT: 'Descript 擅长的',
        they: [
          { t: '改文字稿就是剪视频', b: '成熟好用的编辑器，删一个字就删掉对应画面，还有多轨和录屏。' },
          { t: '音频工具', b: 'Studio Sound、去口头禅；更高套餐还有翻译和配音。' },
          { t: '处处可协作', b: 'Mac 和 Windows 桌面版、网页版，团队可以共享项目。' },
        ],
        weT: '千剪不一样的地方',
        we: [
          { t: '批量，而不是一条时间线', b: '从一条录像规划 24 条片段，并行跑完，只看没通过检查的几条。' },
          { t: '二十个平台的规格', b: '每条按平台各出一版：字幕在安全区内，封面、响度、文案字数都按规矩。' },
          { t: '本机运行，用你自己的 AI', b: '渲染在你的 Mac 上完成；规划用你选的 AI，也可以是本地模型。' },
          { t: '免费、开源', b: '没有媒体时长额度。MIT 协议，引擎也能作为 Claude Code 技能使用。' },
        ],
        chooseT: '该选哪个',
        choose: [
          { t: '选 Descript，如果', b: '你一次精修一条视频、需要认真处理音频、要录屏，或者团队在 Windows 和 Mac 上协作。' },
          { t: '选千剪，如果', b: '你手里有长录像，要剪成很多条发往很多平台（包括国内平台），并希望在自己的 Mac 上完成。' },
        ],
        values: DESCRIPT_V,
        notes: { free: '免费版每月 60 分钟媒体时长，720p 带水印；付费版按年付每月 16 美元起', mac: 'macOS 14 及以上', win: 'Windows 11', post: '可直接发布到 YouTube', pick: 'Underlord 的“Create clips”' },
        faq: [
          { q: '千剪能替代 Descript 吗？', a: '如果是把长录像剪成很多条适配各平台的短片，可以。如果是细致精修一条视频，Descript 能做的更多。千剪也有按文字稿剪的片段编辑器，但重点是批量。' },
          { q: '可以两个一起用吗？', a: '可以。有人先在 Descript 里精修长视频，导出后交给千剪剪出一周的短片。' },
        ],
      },
      fr: {
        name: 'Descript',
        title: 'Reelfold ou Descript : une alternative à Descript pensée pour les lots, sur Mac | Reelfold',
        description: 'Comparaison honnête de Reelfold et de Descript : un éditeur abouti, piloté par la transcription, pour une vidéo à la fois, face à une app Mac gratuite et open source qui tire une semaine de clips d’un enregistrement. Vérifié en octobre 2026.',
        kicker: 'Comparer',
        h1: 'Reelfold et Descript, côte à côte.',
        intro: 'Descript est un éditeur : on façonne une vidéo en modifiant sa transcription, avec de bons outils audio et du travail à plusieurs. Reelfold est un outil de lots : un enregistrement devient de nombreux clips pour de nombreuses plateformes, rendus sur votre Mac. Beaucoup gagneraient à utiliser les deux.',
        theyT: 'Les points forts de Descript',
        they: [
          { t: 'Monter par la transcription', b: 'Un éditeur mûr et soigné où supprimer un mot le supprime de la vidéo, avec multipiste et enregistrement d’écran.' },
          { t: 'Outils audio', b: 'Studio Sound, retrait des hésitations et, sur les offres supérieures, traduction et doublage.' },
          { t: 'Collaboration partout', b: 'Apps pour Mac et Windows, app web, et projets partagés en équipe.' },
        ],
        weT: 'Ce qui distingue Reelfold',
        we: [
          { t: 'Des lots, pas une seule timeline', b: 'Planifiez 24 clips à partir d’un enregistrement, lancez-les en parallèle et ne regardez que ceux que les contrôles signalent.' },
          { t: 'Vingt profils de plateforme', b: 'Chaque clip sort par plateforme : sous-titres dans la zone sûre, couverture, volume réglé, texte dans les limites.' },
          { t: 'En local, avec votre IA', b: 'Le rendu se fait sur votre Mac ; le plan utilise l’IA de votre choix, modèle local compris.' },
          { t: 'Gratuit et open source', b: 'Pas de quota d’heures. Licence MIT, et le moteur existe aussi comme skill Claude Code.' },
        ],
        chooseT: 'Lequel choisir',
        choose: [
          { t: 'Choisissez Descript si', b: 'vous peaufinez une vidéo à la fois, avez besoin d’un vrai nettoyage audio, enregistrez votre écran, ou travaillez en équipe sur Windows et Mac.' },
          { t: 'Choisissez Reelfold si', b: 'vous avez de longs enregistrements à transformer en nombreux clips pour de nombreuses plateformes, chinoises comprises, et voulez le faire sur votre propre Mac.' },
        ],
        values: DESCRIPT_V,
        notes: { free: 'Offre gratuite : 60 minutes par mois, 720p avec filigrane ; payant dès 16 $/mois en annuel', mac: 'macOS 14 ou plus récent', win: 'Windows 11', post: 'Publication directe sur YouTube', pick: 'Underlord « Create clips »' },
        faq: [
          { q: 'Reelfold remplace-t-il Descript ?', a: 'Pour transformer de longs enregistrements en nombreux clips prêts pour chaque plateforme, oui. Pour le montage fin d’une seule vidéo, Descript en fait davantage. Reelfold a un éditeur de clip par transcription, mais son cœur, c’est le lot.' },
          { q: 'Peut-on utiliser les deux ?', a: 'Oui. Certains peaufinent une longue vidéo dans Descript, l’exportent, puis laissent Reelfold en tirer la semaine de clips.' },
        ],
      },
      es: {
        name: 'Descript',
        title: 'Reelfold vs Descript: una alternativa a Descript pensada para lotes, en Mac | Reelfold',
        description: 'Comparación honesta entre Reelfold y Descript: un editor pulido que edita desde la transcripción, un video a la vez, frente a una app gratuita y de código abierto para Mac que saca una semana de clips de una grabación. Revisado en octubre de 2026.',
        kicker: 'Comparar',
        h1: 'Reelfold y Descript, lado a lado.',
        intro: 'Descript es un editor: das forma a un video editando su transcripción, con buenas herramientas de audio y trabajo en equipo. Reelfold es una herramienta de lotes: una grabación se convierte en muchos clips para muchas plataformas, renderizados en tu Mac. Mucha gente podría usar los dos.',
        theyT: 'Dónde destaca Descript',
        they: [
          { t: 'Editar desde la transcripción', b: 'Un editor maduro y pulido en el que borrar una palabra la borra del video, con multipista y grabación de pantalla.' },
          { t: 'Herramientas de audio', b: 'Studio Sound, eliminación de muletillas y, en planes superiores, traducción y doblaje.' },
          { t: 'Colaboración en todas partes', b: 'Apps para Mac y Windows, app web y proyectos compartidos en equipo.' },
        ],
        weT: 'En qué es distinto Reelfold',
        we: [
          { t: 'Lotes, no una sola línea de tiempo', b: 'Planifica 24 clips de una grabación, procésalos en paralelo y mira solo los que marcan los controles.' },
          { t: 'Veinte perfiles de plataforma', b: 'Cada clip sale por plataforma: subtítulos dentro de la zona segura, portada, volumen ajustado y texto dentro de los límites.' },
          { t: 'En local, con tu IA', b: 'El renderizado ocurre en tu Mac; la planificación usa la IA que elijas, incluido un modelo local.' },
          { t: 'Gratis y de código abierto', b: 'Sin cupo de horas. Licencia MIT, y el motor también existe como skill de Claude Code.' },
        ],
        chooseT: 'Cuál elegir',
        choose: [
          { t: 'Elige Descript si', b: 'pules un video a la vez, necesitas limpiar bien el audio, grabas tu pantalla o trabajas en equipo con Windows y Mac.' },
          { t: 'Elige Reelfold si', b: 'tienes grabaciones largas que convertir en muchos clips para muchas plataformas, chinas incluidas, y quieres hacerlo en tu propio Mac.' },
        ],
        values: DESCRIPT_V,
        notes: { free: 'Plan gratuito: 60 minutos al mes, 720p con marca de agua; de pago desde 16 US$/mes con pago anual', mac: 'macOS 14 o posterior', win: 'Windows 11', post: 'Publica directamente en YouTube', pick: 'Underlord “Create clips”' },
        faq: [
          { q: '¿Reelfold sustituye a Descript?', a: 'Para convertir grabaciones largas en muchos clips listos para cada plataforma, sí. Para editar a fondo un solo video, Descript hace más. Reelfold tiene un editor de clips por transcripción, pero su centro es el lote.' },
          { q: '¿Puedo usar los dos?', a: 'Sí. Hay quien pule un video largo en Descript, lo exporta y deja que Reelfold saque de ahí la semana de clips.' },
        ],
      },
    },
  },

  capcut: {
    sources: [
      { label: 'CapCut (platforms and features)', url: 'https://www.capcut.com/' },
      { label: 'CapCut long video to shorts', url: 'https://www.capcut.com/tools/long-video-to-shorts' },
    ],
    byLang: {
      en: {
        name: 'CapCut',
        title: 'Reelfold vs CapCut: batch clips without templates or uploads | Reelfold',
        description: 'An honest comparison of Reelfold and CapCut: a creative editor with templates on every device vs a free, open-source Mac app for turning one recording into many platform-ready clips. Checked October 2026.',
        kicker: 'Compare',
        h1: 'Reelfold and CapCut, side by side.',
        intro: 'CapCut (剪映 in China) is a creative editor on phones, desktops and the web, with a large library of templates and effects. Reelfold is a batch tool for Mac that turns long recordings into many clips for many platforms. They solve different problems.',
        theyT: 'Where CapCut is strong',
        they: [
          { t: 'On every device', b: 'Apps for iPhone and Android, Mac and Windows, and a web editor.' },
          { t: 'Templates and effects', b: 'A large library of templates, effects and text styles for hands-on creative editing.' },
          { t: 'Free to start', b: 'There is a free tier, and its long-video-to-shorts tool is offered for free.' },
        ],
        weT: 'Where Reelfold is different',
        we: [
          { t: 'Many recordings, one plan', b: 'Describe the batch once; Reelfold plans, cuts and renders every clip, then shows you only the flagged ones.' },
          { t: 'Every platform at once', b: 'Each clip is exported for twenty platform profiles, from Xiaohongshu 3:4 to YouTube Shorts 9:16, with covers and copy.' },
          { t: 'Local, your AI', b: 'Rendering on your Mac, planning with the AI you choose. Your recordings stay on your Mac.' },
          { t: 'Open source', b: 'MIT licensed; you can read exactly what it does with your files.' },
        ],
        chooseT: 'Which one to pick',
        choose: [
          { t: 'Pick CapCut if', b: 'you edit by hand, on your phone or a Windows PC, and want templates, effects and music for each video.' },
          { t: 'Pick Reelfold if', b: 'you produce many clips from long recordings every week and want them planned, checked and formatted for each platform on your Mac.' },
        ],
        values: CAPCUT_V,
        notes: { free: 'Free tier; Pro is a paid subscription, prices vary by region', pick: '“Long video to shorts” tool' },
        faq: [
          { q: 'Is Reelfold a CapCut alternative for batches?', a: 'For batch work, yes: many clips from long recordings, formatted for many platforms at once. For hands-on creative editing with templates, CapCut covers more.' },
          { q: 'Can I finish a Reelfold clip in CapCut?', a: 'Yes. Reelfold exports normal video files, so you can open any clip in CapCut or 剪映 for extra effects.' },
        ],
      },
      zh: {
        name: '剪映 / CapCut',
        title: '千剪和剪映（CapCut）对比：不靠模板的批量切片 | 千剪',
        description: '如实对比千剪和剪映（CapCut）：一个是全设备、模板丰富的创意剪辑工具，一个是把一条录像剪成多个平台短片的免费开源 Mac 应用。2026 年 10 月核对。',
        kicker: '对比',
        h1: '千剪和剪映，放在一起看。',
        intro: '剪映（海外版叫 CapCut）是手机、电脑、网页都能用的创意剪辑工具，模板和特效很多。千剪是 Mac 上的批量工具，把长录像剪成发往很多平台的很多条。两者解决的是不同的问题。',
        theyT: '剪映擅长的',
        they: [
          { t: '设备齐全', b: 'iPhone、安卓、Mac、Windows 都有应用，还有网页版。' },
          { t: '模板和特效', b: '大量模板、特效和花字，适合动手做创意剪辑。' },
          { t: '免费起步', b: '有免费版，长视频转短视频工具也标注为免费。' },
        ],
        weT: '千剪不一样的地方',
        we: [
          { t: '多条录像，一份计划', b: '把这一批说清楚一次；千剪规划、剪辑、渲染每一条，只把被标出的给你看。' },
          { t: '一次覆盖所有平台', b: '每条片段按二十个平台规格导出，从小红书 3:4 到 YouTube Shorts 9:16，封面和文案都配好。' },
          { t: '本机运行，用你的 AI', b: '在你的 Mac 上渲染，用你选的 AI 规划。录像留在你的 Mac 上。' },
          { t: '开源', b: 'MIT 协议；它怎么处理你的文件，代码里写得清清楚楚。' },
        ],
        chooseT: '该选哪个',
        choose: [
          { t: '选剪映，如果', b: '你习惯手动剪，用手机或 Windows 电脑，想给每条视频配模板、特效和音乐。' },
          { t: '选千剪，如果', b: '你每周要从长录像里出很多条，希望在 Mac 上自动规划、检查，并按每个平台排好格式。' },
        ],
        values: CAPCUT_V,
        notes: { free: '有免费版；专业版需订阅，价格因地区而异', pick: '“长视频转短视频”工具' },
        faq: [
          { q: '千剪能代替剪映做批量吗？', a: '做批量可以：从长录像出很多条，一次适配很多平台。要动手做带模板的创意剪辑，剪映覆盖得更多。' },
          { q: '千剪剪好的片段能再放进剪映吗？', a: '能。千剪导出的是普通视频文件，任何一条都可以在剪映或 CapCut 里继续加特效。' },
        ],
      },
      fr: {
        name: 'CapCut',
        title: 'Reelfold ou CapCut : des clips par lots, sans modèles ni envoi | Reelfold',
        description: 'Comparaison honnête de Reelfold et de CapCut : un éditeur créatif riche en modèles sur tous les appareils, face à une app Mac gratuite et open source qui transforme un enregistrement en clips pour chaque plateforme. Vérifié en octobre 2026.',
        kicker: 'Comparer',
        h1: 'Reelfold et CapCut, côte à côte.',
        intro: 'CapCut (剪映 en Chine) est un éditeur créatif sur téléphone, ordinateur et web, avec une vaste bibliothèque de modèles et d’effets. Reelfold est un outil de lots pour Mac qui transforme de longs enregistrements en nombreux clips pour de nombreuses plateformes. Ils ne répondent pas au même besoin.',
        theyT: 'Les points forts de CapCut',
        they: [
          { t: 'Sur tous les appareils', b: 'Apps pour iPhone et Android, Mac et Windows, et un éditeur web.' },
          { t: 'Modèles et effets', b: 'Une vaste bibliothèque de modèles, d’effets et de styles de texte pour monter à la main.' },
          { t: 'Gratuit pour commencer', b: 'Une offre gratuite existe, et son outil de vidéo longue vers vidéos courtes est proposé gratuitement.' },
        ],
        weT: 'Ce qui distingue Reelfold',
        we: [
          { t: 'Plusieurs enregistrements, un plan', b: 'Décrivez le lot une fois ; Reelfold planifie, coupe et rend chaque clip, puis ne vous montre que les clips signalés.' },
          { t: 'Toutes les plateformes d’un coup', b: 'Chaque clip est exporté pour vingt profils, du 3:4 de Xiaohongshu au 9:16 de YouTube Shorts, avec couvertures et textes.' },
          { t: 'En local, avec votre IA', b: 'Rendu sur votre Mac, plan avec l’IA de votre choix. Vos enregistrements restent sur votre Mac.' },
          { t: 'Open source', b: 'Licence MIT : vous pouvez lire exactement ce qu’il fait de vos fichiers.' },
        ],
        chooseT: 'Lequel choisir',
        choose: [
          { t: 'Choisissez CapCut si', b: 'vous montez à la main, sur téléphone ou sur PC Windows, et voulez des modèles, des effets et de la musique pour chaque vidéo.' },
          { t: 'Choisissez Reelfold si', b: 'vous produisez chaque semaine de nombreux clips à partir de longs enregistrements et voulez qu’ils soient planifiés, contrôlés et formatés pour chaque plateforme sur votre Mac.' },
        ],
        values: CAPCUT_V,
        notes: { free: 'Offre gratuite ; Pro payant, prix selon la région', pick: 'Outil « Long video to shorts »' },
        faq: [
          { q: 'Reelfold est-il une alternative à CapCut pour les lots ?', a: 'Pour le travail par lots, oui : de nombreux clips tirés de longs enregistrements, formatés pour beaucoup de plateformes à la fois. Pour le montage créatif à la main avec des modèles, CapCut en offre davantage.' },
          { q: 'Puis-je finir un clip Reelfold dans CapCut ?', a: 'Oui. Reelfold exporte des fichiers vidéo ordinaires : vous pouvez ouvrir n’importe quel clip dans CapCut ou 剪映 pour ajouter des effets.' },
        ],
      },
      es: {
        name: 'CapCut',
        title: 'Reelfold vs CapCut: clips por lotes, sin plantillas ni subidas | Reelfold',
        description: 'Comparación honesta entre Reelfold y CapCut: un editor creativo con plantillas en todos los dispositivos frente a una app gratuita y de código abierto para Mac que convierte una grabación en clips para cada plataforma. Revisado en octubre de 2026.',
        kicker: 'Comparar',
        h1: 'Reelfold y CapCut, lado a lado.',
        intro: 'CapCut (剪映 en China) es un editor creativo para móvil, computadora y web, con una gran biblioteca de plantillas y efectos. Reelfold es una herramienta de lotes para Mac que convierte grabaciones largas en muchos clips para muchas plataformas. Resuelven problemas distintos.',
        theyT: 'Dónde destaca CapCut',
        they: [
          { t: 'En todos los dispositivos', b: 'Apps para iPhone y Android, Mac y Windows, y un editor web.' },
          { t: 'Plantillas y efectos', b: 'Una gran biblioteca de plantillas, efectos y estilos de texto para editar a mano.' },
          { t: 'Gratis para empezar', b: 'Tiene un plan gratuito, y su herramienta de video largo a cortos se ofrece gratis.' },
        ],
        weT: 'En qué es distinto Reelfold',
        we: [
          { t: 'Muchas grabaciones, un plan', b: 'Describe el lote una vez; Reelfold planifica, corta y renderiza cada clip, y solo te muestra los marcados.' },
          { t: 'Todas las plataformas a la vez', b: 'Cada clip se exporta para veinte perfiles, del 3:4 de Xiaohongshu al 9:16 de YouTube Shorts, con portadas y textos.' },
          { t: 'En local, con tu IA', b: 'Renderizado en tu Mac, planificación con la IA que elijas. Tus grabaciones se quedan en tu Mac.' },
          { t: 'Código abierto', b: 'Licencia MIT: puedes leer exactamente qué hace con tus archivos.' },
        ],
        chooseT: 'Cuál elegir',
        choose: [
          { t: 'Elige CapCut si', b: 'editas a mano, en el móvil o en un PC con Windows, y quieres plantillas, efectos y música para cada video.' },
          { t: 'Elige Reelfold si', b: 'produces cada semana muchos clips a partir de grabaciones largas y quieres que se planifiquen, se revisen y se adapten a cada plataforma en tu Mac.' },
        ],
        values: CAPCUT_V,
        notes: { free: 'Plan gratuito; Pro de pago, con precios según la región', pick: 'Herramienta “Long video to shorts”' },
        faq: [
          { q: '¿Reelfold es una alternativa a CapCut para lotes?', a: 'Para trabajo por lotes, sí: muchos clips sacados de grabaciones largas, adaptados a muchas plataformas a la vez. Para edición creativa a mano con plantillas, CapCut ofrece más.' },
          { q: '¿Puedo terminar un clip de Reelfold en CapCut?', a: 'Sí. Reelfold exporta archivos de video normales, así que puedes abrir cualquier clip en CapCut o 剪映 para añadir efectos.' },
        ],
      },
    },
  },
};

export const compareEntry = (slug: string): CompareEntry => {
  const d = DATA[slug as CompareSlug];
  if (!d) throw new Error(`unknown comparison ${slug}`);
  return d;
};
export const compare = (slug: string, lang: Lang): ComparePage => compareEntry(slug).byLang[lang];
