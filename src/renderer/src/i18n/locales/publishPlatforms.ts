// Publishing to X, Instagram, 视频号 and B站 (platform names, publish-page guide / checks, calendar platform chips):
// English + 简体中文.

export const publishPlatformsEn = {
  'pf.x': 'X',
  'pf.instagram': 'Instagram',
  'pf.wechat-channels': 'Channels',
  'pub.guide': 'What you do',
  'pub.herChoices': 'Left for you (never filled)',
  'pub.checks': 'Before you post',
  'pub.check.text-over': '{field} is {n} / {max} - the platform will ask you to shorten it',
  'pub.check.text-over-x': 'Post text is {n} / {max} weighted characters (Chinese and emoji count 2, a link 23). Standard X accounts stop at 280; Premium can post more.',
  'pub.check.hashtags-over': '{n} hashtags, {max} are used - the rest are left out',
  'pub.check.hashtags-hard': '{n} hashtags: {platform} allows {max} per post (caption + comments). Only the first {max} are filled; remove extra #tags from the text.',
  'pub.check.ok': 'Length and hashtags are within the limits.',
  'pub.schedTo': 'Schedule to',
  'pub.schedToHint': 'New posts and AI fill go to this platform',
};

export const publishPlatformsZh: Record<keyof typeof publishPlatformsEn, string> = {
  'pf.x': 'X',
  'pf.instagram': 'Instagram',
  'pf.wechat-channels': '视频号',
  'pub.guide': '你要做的',
  'pub.herChoices': '留给你选（不会自动填）',
  'pub.checks': '发布前检查',
  'pub.check.text-over': '{field} {n} / {max}，平台会要求缩短',
  'pub.check.text-over-x': '正文按加权计 {n} / {max}（中文、emoji 算 2，链接算 23）。普通 X 账号上限 280，Premium 可以更长。',
  'pub.check.hashtags-over': '共 {n} 个话题标签，只用前 {max} 个',
  'pub.check.hashtags-hard': '共 {n} 个话题标签：{platform} 每条最多 {max} 个（说明文字和评论合计）。只会填前 {max} 个，请删掉正文里多余的 #标签。',
  'pub.check.ok': '字数和话题标签都在限制内。',
  'pub.schedTo': '排到',
  'pub.schedToHint': '新排的帖子和 AI 排期都发到这个平台',
};
