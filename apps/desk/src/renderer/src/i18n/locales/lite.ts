// The Mac App Store "Lite" build (BUILD_EDITION=mas, src/shared/edition.ts): what this edition does, said neutrally.
// No other download, website or "full version" is named (App Review 3.1.1 / 2.3). Shown only in that build.
export const liteEn = {
  'lite.name': 'Reelfold Lite',
  'lite.badge': 'App Store version',
  'lite.body': 'Everything for editing, captions, covers and publishing is here. This edition uses API keys or local models for AI, and works with the folders and files you choose.',
  'lite.aiTitle': 'Connect an AI model',
  'lite.aiBody': 'Add an API key (Anthropic, OpenAI, DeepSeek, Qwen and more), or run a model on this Mac with Ollama or LM Studio. Keys stay in your Mac’s keychain.',
  'lite.watchHint': 'This version can only watch folders you choose here.',
  'lite.updates': 'Updates come from the Mac App Store',
  'aiacc.st.unavailable': 'Not in this edition',
};

type LiteKey = keyof typeof liteEn;

export const liteZh: Record<LiteKey, string> = {
  'lite.name': '千剪 Lite',
  'lite.badge': 'App Store 版',
  'lite.body': '剪辑、字幕、封面和发布都在这里。这个版本通过 API 密钥或本地模型使用 AI，并使用你选择的文件夹和文件。',
  'lite.aiTitle': '连接一个 AI 模型',
  'lite.aiBody': '添加 API 密钥（Anthropic、OpenAI、DeepSeek、通义千问等），或用 Ollama、LM Studio 在这台 Mac 上运行模型。密钥只保存在 Mac 的钥匙串里。',
  'lite.watchHint': '这个版本只能监看你在这里选择的文件夹。',
  'lite.updates': '通过 Mac App Store 更新',
  'aiacc.st.unavailable': '此版本不提供',
};

export const liteFr: Record<LiteKey, string> = {
  'lite.name': 'Reelfold Lite',
  'lite.badge': 'Version App Store',
  'lite.body': 'Tout pour monter, sous-titrer, créer les couvertures et publier est ici. Cette édition utilise des clés API ou des modèles locaux pour l’IA, et travaille avec les dossiers et fichiers que vous choisissez.',
  'lite.aiTitle': 'Connecter un modèle d’IA',
  'lite.aiBody': 'Ajoutez une clé API (Anthropic, OpenAI, DeepSeek, Qwen…) ou faites tourner un modèle sur ce Mac avec Ollama ou LM Studio. Les clés restent dans le trousseau du Mac.',
  'lite.watchHint': 'Cette version ne surveille que les dossiers choisis ici.',
  'lite.updates': 'Mises à jour via le Mac App Store',
  'aiacc.st.unavailable': 'Absent de cette édition',
};
