// Copy for the /platforms/ spec page. The numbers come from src/data/platforms.json
// (exported from lib/vstudio/platform.py by scripts/export-platforms.py).
import type { Lang } from '../i18n';

export interface PlatformsCopy {
  title: string; description: string; kicker: string; h1: string; intro: string;
  groups: Record<'global' | 'zh' | 'other', string>;
  cols: { platform: string; canvas: string; cover: string; length: string; sweet: string; text: string; links: string };
  orient: Record<string, string>;
  unit: { s: string; min: string; h: string };
  titleChars: string; textChars: string; noTitle: string; yes: string; no: string;
  note: string; sourceLabel: string;
  faq: { q: string; a: string }[];
}

export const PLATFORMS_COPY: Record<Lang, PlatformsCopy> = {
  en: {
    title: 'Video sizes for 20 platforms: Xiaohongshu, Douyin, Shorts, TikTok | Reelfold',
    description: 'Video dimensions, aspect ratios, cover sizes, length limits and caption limits for YouTube, Shorts, TikTok, Instagram, Xiaohongshu, Douyin, WeChat Channels, Bilibili and 12 more. Checked October 2026.',
    kicker: 'Platform specs',
    h1: 'Video sizes for twenty platforms.',
    intro: 'The canvas, cover, length and text limits Reelfold uses when it exports a clip, platform by platform. Platforms change these often, so each value was checked against official help pages or several agreeing guides, with the date below.',
    groups: { global: 'English and global', zh: 'Chinese platforms', other: 'Other languages' },
    cols: { platform: 'Platform', canvas: 'Canvas (px)', cover: 'Cover (px)', length: 'Max length', sweet: 'Typical length', text: 'Title / text limit', links: 'Clickable links' },
    orient: { vertical: 'vertical', full: 'full screen', horizontal: 'landscape', square: 'square', reels: 'Reels', feed: 'feed' },
    unit: { s: 's', min: 'min', h: 'h' },
    titleChars: 'title {n}', textChars: 'text {n}', noTitle: 'no title field', yes: 'Yes', no: 'No',
    note: 'Loudness: Reelfold masters every platform at −14 LUFS (true peak −1.5 dB); only YouTube documents its normalisation. Safe areas for captions and buttons are in the full profile file.',
    sourceLabel: 'Full profiles, sources and safe areas (references/PLATFORMS.md)',
    faq: [
      { q: 'What size is a Xiaohongshu video?', a: 'Xiaohongshu’s native vertical format is 3:4, 1080 × 1440 px, with a 3:4 cover of the same size. Full-screen 9:16 (1080 × 1920) also works; landscape posts are shown with a centre 4:3 crop in the feed.' },
      { q: 'What size is a Douyin video?', a: 'Douyin uses 9:16 vertical video at 1080 × 1920 px. Landscape 16:9 is accepted too. The profile grid shows a 3:4 crop of the cover.' },
      { q: 'What are YouTube Shorts dimensions?', a: 'Shorts are vertical or square, typically 1080 × 1920 px (9:16), and can be up to 3 minutes long.' },
      { q: 'What aspect ratio does TikTok use?', a: 'TikTok uses 9:16 vertical video at 1080 × 1920 px. Keep captions above the bottom area, where the caption text and buttons sit.' },
    ],
  },
  zh: {
    title: '各平台视频尺寸：小红书、抖音、视频号、B站、Shorts | 千剪',
    description: '小红书、抖音、视频号、B站、快手、YouTube Shorts、TikTok 等 20 个平台的视频尺寸、画幅、封面尺寸、时长上限和文案字数限制。2026 年 10 月核对。',
    kicker: '平台规格',
    h1: '二十个平台的视频尺寸。',
    intro: '千剪导出片段时用的画面尺寸、封面、时长和文案字数，按平台列出。平台经常调整这些数字，所以每一项都对照了官方帮助页或几份一致的指南，核对日期见下方。',
    groups: { global: '英文与全球平台', zh: '国内平台', other: '其他语言平台' },
    cols: { platform: '平台', canvas: '画面（像素）', cover: '封面（像素）', length: '时长上限', sweet: '常见时长', text: '标题 / 文案字数', links: '链接可点' },
    orient: { vertical: '竖屏', full: '全屏竖屏', horizontal: '横屏', square: '方形', reels: 'Reels', feed: '信息流' },
    unit: { s: '秒', min: '分钟', h: '小时' },
    titleChars: '标题 {n}', textChars: '正文 {n}', noTitle: '无标题栏', yes: '可以', no: '不行',
    note: '响度：千剪把每个平台都做到 −14 LUFS（真峰值 −1.5 dB）；只有 YouTube 公开了响度标准化的做法。字幕和按钮的安全区见完整规格文件。',
    sourceLabel: '完整规格、来源和安全区（references/PLATFORMS.md）',
    faq: [
      { q: '小红书视频尺寸是多少？', a: '小红书竖屏推荐 3:4，1080 × 1440 像素，封面同样是 3:4、1080 × 1440。9:16 全屏（1080 × 1920）也可以；横屏视频在信息流里会被裁成居中的 4:3。' },
      { q: '抖音视频尺寸是多少？', a: '抖音用 9:16 竖屏，1080 × 1920 像素，也接受 16:9 横屏。主页网格里封面会被裁成 3:4。' },
      { q: '视频号视频尺寸是多少？', a: '视频号推荐 9:16 竖屏（1080 × 1920）或 16:9 横屏（1920 × 1080），文件不超过 2 GB。' },
      { q: 'B站视频比例是多少？', a: 'B站以 16:9 横屏为主，1920 × 1080 像素，封面 16:10；也支持 9:16 竖屏。' },
    ],
  },
  fr: {
    title: 'Formats vidéo de 20 plateformes : Shorts, TikTok, Xiaohongshu, Douyin | Reelfold',
    description: 'Dimensions vidéo, formats d’image, tailles de couverture, durées maximales et limites de texte pour YouTube, Shorts, TikTok, Instagram, Xiaohongshu, Douyin, WeChat Channels, Bilibili et 12 autres. Vérifié en octobre 2026.',
    kicker: 'Formats des plateformes',
    h1: 'Les formats vidéo de vingt plateformes.',
    intro: 'Taille d’image, couverture, durée et limites de texte que Reelfold applique à l’export, plateforme par plateforme. Les plateformes les modifient souvent : chaque valeur a été vérifiée sur les pages d’aide officielles ou plusieurs guides concordants, à la date indiquée plus bas.',
    groups: { global: 'Plateformes internationales', zh: 'Plateformes chinoises', other: 'Autres langues' },
    cols: { platform: 'Plateforme', canvas: 'Image (px)', cover: 'Couverture (px)', length: 'Durée max.', sweet: 'Durée courante', text: 'Limite titre / texte', links: 'Liens cliquables' },
    orient: { vertical: 'vertical', full: 'plein écran', horizontal: 'paysage', square: 'carré', reels: 'Reels', feed: 'fil' },
    unit: { s: 's', min: 'min', h: 'h' },
    titleChars: 'titre {n}', textChars: 'texte {n}', noTitle: 'pas de champ titre', yes: 'Oui', no: 'Non',
    note: 'Volume sonore : Reelfold masterise chaque plateforme à −14 LUFS (crête vraie −1,5 dB) ; seul YouTube documente sa normalisation. Les zones sûres pour les sous-titres et les boutons figurent dans le fichier de profils complet.',
    sourceLabel: 'Profils complets, sources et zones sûres (references/PLATFORMS.md, en anglais)',
    faq: [
      { q: 'Quel format pour une vidéo Xiaohongshu ?', a: 'Xiaohongshu affiche le mieux la vidéo verticale en 3:4, 1080 × 1440 px, avec une couverture 3:4 de même taille. Le plein écran 9:16 (1080 × 1920) fonctionne aussi ; les vidéos en paysage sont recadrées en 4:3 au centre dans le fil.' },
      { q: 'Quel format pour une vidéo Douyin ?', a: 'Douyin utilise la vidéo verticale 9:16 en 1080 × 1920 px. Le paysage 16:9 est aussi accepté. La grille du profil montre la couverture recadrée en 3:4.' },
      { q: 'Quelles dimensions pour YouTube Shorts ?', a: 'Les Shorts sont verticaux ou carrés, en général 1080 × 1920 px (9:16), et peuvent durer jusqu’à 3 minutes.' },
      { q: 'Quel format d’image pour TikTok ?', a: 'TikTok utilise la vidéo verticale 9:16 en 1080 × 1920 px. Gardez les sous-titres au-dessus de la zone du bas, où se trouvent la légende et les boutons.' },
    ],
  },
  es: {
    title: 'Tamaños de video para 20 plataformas: Shorts, TikTok, Xiaohongshu, Douyin | Reelfold',
    description: 'Dimensiones de video, relaciones de aspecto, tamaños de portada, duraciones máximas y límites de texto para YouTube, Shorts, TikTok, Instagram, Xiaohongshu, Douyin, WeChat Channels, Bilibili y 12 más. Revisado en octubre de 2026.',
    kicker: 'Formatos por plataforma',
    h1: 'Tamaños de video para veinte plataformas.',
    intro: 'El lienzo, la portada, la duración y los límites de texto que usa Reelfold al exportar, plataforma por plataforma. Las plataformas los cambian a menudo, así que cada valor se comprobó en páginas de ayuda oficiales o en varias guías coincidentes, con la fecha que verás abajo.',
    groups: { global: 'Plataformas globales', zh: 'Plataformas chinas', other: 'Otros idiomas' },
    cols: { platform: 'Plataforma', canvas: 'Lienzo (px)', cover: 'Portada (px)', length: 'Duración máx.', sweet: 'Duración habitual', text: 'Límite título / texto', links: 'Enlaces clicables' },
    orient: { vertical: 'vertical', full: 'pantalla completa', horizontal: 'horizontal', square: 'cuadrado', reels: 'Reels', feed: 'feed' },
    unit: { s: 's', min: 'min', h: 'h' },
    titleChars: 'título {n}', textChars: 'texto {n}', noTitle: 'sin campo de título', yes: 'Sí', no: 'No',
    note: 'Volumen: Reelfold masteriza cada plataforma a −14 LUFS (pico real −1,5 dB); solo YouTube documenta su normalización. Las zonas seguras para subtítulos y botones están en el archivo completo de perfiles.',
    sourceLabel: 'Perfiles completos, fuentes y zonas seguras (references/PLATFORMS.md, en inglés)',
    faq: [
      { q: '¿Qué tamaño tiene un video de Xiaohongshu?', a: 'Xiaohongshu muestra mejor el video vertical en 3:4, 1080 × 1440 px, con una portada 3:4 del mismo tamaño. También sirve la pantalla completa 9:16 (1080 × 1920); los videos horizontales se recortan a 4:3 centrado en el feed.' },
      { q: '¿Qué tamaño tiene un video de Douyin?', a: 'Douyin usa video vertical 9:16 de 1080 × 1920 px. También acepta horizontal 16:9. La cuadrícula del perfil muestra la portada recortada a 3:4.' },
      { q: '¿Qué dimensiones tienen los YouTube Shorts?', a: 'Los Shorts son verticales o cuadrados, normalmente de 1080 × 1920 px (9:16), y pueden durar hasta 3 minutos.' },
      { q: '¿Qué relación de aspecto usa TikTok?', a: 'TikTok usa video vertical 9:16 de 1080 × 1920 px. Deja los subtítulos por encima de la zona inferior, donde van el texto de la publicación y los botones.' },
    ],
  },
};
