// The Mac App Store "Lite" build (BUILD_EDITION=mas, src/shared/edition.ts): what it leaves out and where the full
// version is. Shown only in that build.
export const liteEn = {
  'lite.name': 'Reelfold Lite',
  'lite.badge': 'App Store version',
  'lite.body': 'Everything for editing, captions, covers and publishing is here. The free full version from reelfold.com also lets you sign in with your Claude Code or Codex subscription and watch any folder for new recordings.',
  'lite.cta': 'Get the full version',
  'lite.aiTitle': 'Connect an AI model',
  'lite.aiBody': 'Add an API key (Anthropic, OpenAI, DeepSeek, Qwen and more), or run a model on this Mac with Ollama or LM Studio. Keys stay in your Mac’s keychain.',
  'lite.aiSubs': 'Signing in with a Claude Code or Codex subscription needs the full version.',
  'lite.watchHint': 'This version can only watch folders you choose here.',
  'lite.updates': 'Updates come from the Mac App Store',
  'aiacc.st.unavailable': 'Full version only',
};

type LiteKey = keyof typeof liteEn;

export const liteZh: Record<LiteKey, string> = {
  'lite.name': '千剪 Lite',
  'lite.badge': 'App Store 版',
  'lite.body': '剪辑、字幕、封面和发布都在这里。reelfold.com 上免费的完整版还可以用你的 Claude Code 或 Codex 订阅登录，并监看任意文件夹里的新录像。',
  'lite.cta': '下载完整版',
  'lite.aiTitle': '连接一个 AI 模型',
  'lite.aiBody': '添加 API 密钥（Anthropic、OpenAI、DeepSeek、通义千问等），或用 Ollama、LM Studio 在这台 Mac 上运行模型。密钥只保存在 Mac 的钥匙串里。',
  'lite.aiSubs': '用 Claude Code 或 Codex 订阅登录需要完整版。',
  'lite.watchHint': '这个版本只能监看你在这里选择的文件夹。',
  'lite.updates': '通过 Mac App Store 更新',
  'aiacc.st.unavailable': '仅完整版',
};

export const liteFr: Record<LiteKey, string> = {
  'lite.name': 'Reelfold Lite',
  'lite.badge': 'Version App Store',
  'lite.body': 'Tout pour monter, sous-titrer, créer les couvertures et publier est ici. La version complète gratuite sur reelfold.com permet aussi de se connecter avec un abonnement Claude Code ou Codex et de surveiller n’importe quel dossier.',
  'lite.cta': 'Obtenir la version complète',
  'lite.aiTitle': 'Connecter un modèle d’IA',
  'lite.aiBody': 'Ajoutez une clé API (Anthropic, OpenAI, DeepSeek, Qwen…) ou faites tourner un modèle sur ce Mac avec Ollama ou LM Studio. Les clés restent dans le trousseau du Mac.',
  'lite.aiSubs': 'La connexion avec un abonnement Claude Code ou Codex nécessite la version complète.',
  'lite.watchHint': 'Cette version ne surveille que les dossiers choisis ici.',
  'lite.updates': 'Mises à jour via le Mac App Store',
  'aiacc.st.unavailable': 'Version complète uniquement',
};
