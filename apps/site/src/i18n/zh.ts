// 中文文案。写作规则见 README「Copy rules」，`npm run check:copy` 会检查。
export const zh = {
  lang: 'zh-CN',
  htmlLang: 'zh-CN',
  meta: {
    title: '千剪 Reelfold · 一条素材，千条成片，一次发到各个平台',
    description:
      '千剪 Reelfold 是免费开源（MIT）的 Mac 桌面应用：一句话描述这批视频，AI 规划，在你的 Mac 上批量剪辑，只看质检拦下的例外，按 YouTube、TikTok、Instagram、X、小红书、抖音、视频号、B站等平台分别出成片、封面和文案，发布按钮由你自己点。',
  },
  nav: {
    how: '流程',
    uses: '适合谁',
    app: 'Mac 版',
    proof: '真实数据',
    local: '本地与隐私',
    oss: '开源',
    faq: '常见问题',
    langGroup: '语言',
    skip: '跳到正文',
  },
  cta: {
    download: '下载 macOS 版',
    soon: 'macOS 版即将发布',
    soonNote: 'macOS 正式版即将发布。在那之前，可以从源码构建，或者把引擎当 Claude Code 技能用。',
    star: '在 GitHub 上 Star',
    source: '从源码构建',
    windows: 'Windows 版：之后推出',
  },
  hero: {
    eyebrow: '免费开源（MIT）· macOS 桌面应用 · Apple 芯片',
    titleA: '一条素材，千条成片，',
    titleB: '一次发到各个平台。',
    sub: '用一句话说清楚要什么，放进一段录制。AI 规划选段，整批在你的 Mac 上剪完，自动质检只把有问题的拦给你看；每个平台的成片、封面和文案都准备好，发布按钮由你自己点。',
    points: ['素材留在你的 Mac 上，不上传', '只看被质检拦下的例外', '辅助发布：帮你填好，你来点发布'],
    stickerA: '小红书 3:4',
    stickerB: '质检通过',
    stickerC: '1 段素材 → 96 个文件',
    frameAlts: [
      '口播短视频画面：字幕和记笔记面板',
      '长视频切片画面：代码讲解，标题条写着混合检索',
      'AI 越用越笨的知识类视频画面，双人对话和记笔记面板',
    ],
  },
  how: {
    kicker: '流程',
    title: '一次处理一整段素材，而不是一条一条剪',
    steps: [
      {
        title: '描述',
        body: '放进一段录制（访谈、播客、讲座、直播回放或客户的素材），用大白话说这批要几条、发哪些平台、什么风格。',
      },
      {
        title: 'AI 规划',
        body: 'AI 按话题选段，生成一份你能看懂、能改的方案：每条剪哪段、标题是什么、发到哪里。',
      },
      {
        title: '批量剪辑',
        body: '整批在你的 Mac 上并行跑：去气口、口头禅和重复，加字幕、标题条、代码放大和记笔记面板。',
      },
      {
        title: '只看例外',
        body: '每个文件都自动检查响度、音画同步、字幕丢词、是否挡住平台按钮、时长和标题长度。只有红灯的进审片网格，按逐字稿改完只重渲染这几条。',
      },
      {
        title: '辅助发布',
        body: '每个平台单独导出，配好封面、标题、正文、标签和 AI 内容声明提醒。千剪帮你填好上传页面，发布按钮由你自己点，它不会自动发。',
      },
    ],
    platformsLabel: '支持平台',
    platforms: ['YouTube 16:9 + Shorts 9:16', 'TikTok 9:16', 'Instagram Reels 9:16 + 动态 4:5', 'X 16:9 / 1:1 / 9:16', 'Facebook Reels 9:16 + 动态 4:5', 'LinkedIn 16:9 / 1:1', 'Threads 9:16', 'Reddit 16:9', 'Pinterest 9:16', 'Snapchat Spotlight 9:16', '小红书 3:4', '抖音 9:16', '视频号 9:16', 'B站 16:9', '快手 9:16', '微博 16:9', '知乎 16:9', 'Dailymotion 16:9', 'Kwai 9:16'],
  },
  uses: {
    kicker: '适合谁',
    title: '给需要批量剪辑、多平台发布的人',
    lede: '同一套引擎，处理各种素材。每个流程都在真实素材上测过。',
    items: [
      { title: '批量创作者', body: '录一次，发一周。一次录制拆成一组短视频，每条按你要发的平台导出对应比例、时长和响度。' },
      { title: '访谈和播客', body: '从一段长对话里切出多条片段，带字幕和说话人构图，每个平台单独导出。嘉宾可以遮脸、名字打码。' },
      { title: '做客户批次的工作室', body: '在同一个看板上并行跑多个客户的批次，每个客户保留自己的风格和术语表，每批附质检报告。' },
      { title: '口播', body: '去气口、口头禅和重复，再加字幕、关键词弹字、章节进度条和封面。' },
      { title: '课程切片', body: '把长课切成竖屏片段或分集，带标题条、跟随文字的代码裁切和章节卡，学员声音可以变声。' },
      { title: '讲解短片', body: '从脚本或一个主题做 3Blue1Brown 风格讲解：AI 配音、动画场景、中英双语字幕。' },
    ],
  },
  app: {
    kicker: '桌面应用',
    title: '千剪 Mac 版',
    lede: '一句话描述这批任务，千剪生成方案，在你自己的电脑上并行剪辑，看板上看进度；网格审片，按逐字稿删改。发布时在内置浏览器里帮你填好各平台的内容，发布按钮由你自己点。',
    note: '免费开源（MIT），目前只支持 Apple 芯片的 Mac。AI 用你自己的 Claude Code / Codex 订阅、API key 或本地模型。',
    board: {
      cols: ['排队', '渲染', '质检', '待审', '已批准'],
      cards: ['ep03 · RRF 只看排名', 'ep06 · 检索用小块', 'ep11 · 指标掉了先修哪个', 'ep14 · 父子分块', 'ep19 · 重排序'],
      green: '绿灯',
      red: '红灯 · 接缝处疑似丢字',
      caption: '示意图：批次看板的样子（不是截图）。',
    },
  },
  proof: {
    kicker: '真实数据',
    title: '用这套开源工具跑的一次真实批次',
    lede: '我们用自己的一节 72 分钟讲座跑了一整批。好的和不够好的都写在这里。',
    stats: [
      { value: '96', label: '个成品文件', note: '24 条切片 × 4 种平台格式，每条含封面和发布文案' },
      { value: '$0.73', label: '整批 AI API 费用', note: '约 $0.03 / 条；语音转写在本机完成' },
      { value: '21 / 24', label: '条通过自动质检', note: '3 条红灯都在剪辑接缝处，进了审片网格' },
      { value: '3–4 小时', label: '首轮机器时间', note: '修复后增量重跑 13 条用了 18 分钟' },
    ],
    caveatsTitle: '还没做好的地方',
    caveats: [
      '中文字幕仍会听错词。术语表能纠正一部分，剩下的要你在审片时改。',
      '去口头禅的剪辑点里，需要你确认的还偏多（这批平均每条约 15 处）。我们正在让低风险的类型自动通过。',
      '原画面文字很小的时候，竖屏里读起来吃力。',
    ],
    stripCaption: '同一套工具做的六种成片画面：口播、长视频切片、文艺片、旅行 vlog、播客遮脸、讲解短片。',
    stripAlts: [
      '口播短视频：字幕与记笔记面板',
      '长视频切片：代码讲解与标题条',
      '文艺片：草稿与成品对比',
      '旅行 vlog：地点标签与彩色纸屑特效',
      '播客剪辑：双人画面与记笔记面板',
      '讲解短片：CUDA 线程索引动画与中英字幕',
    ],
    sheets: [
      {
        img: 'longform-slices',
        alt: '长视频切片的样片缩略图：标题条、代码截图裁切、记笔记面板和章节卡',
        caption: '长视频切片：从 72 分钟讲座里切出的竖屏片段。标题条、跟随文字的代码区域裁切、记笔记面板、章节卡。',
      },
      {
        img: 'talkinghead',
        alt: '口播精剪的样片缩略图：章节进度条、记笔记面板、关键词弹字',
        caption: '口播精剪：章节进度条、记笔记面板、关键词弹字。',
      },
      {
        img: 'explainer-vertical',
        alt: '讲解短片的样片缩略图：动画场景和中英双语字幕',
        caption: '讲解短片：AI 配音、中英字幕、动画场景。',
      },
    ],
  },
  deliverables: {
    kicker: '每批产出',
    title: '每一条都带齐这些',
    items: [
      { title: '各平台成片', body: 'YouTube 长视频 16:9、Shorts 9:16；TikTok、Instagram 和 Facebook Reels、Snapchat、Pinterest 9:16；X、LinkedIn、Reddit 按视频比例选；小红书 3:4；抖音、视频号、快手 9:16；B站、微博、知乎、Dailymotion 16:9。每个平台单独导出，响度按平台要求，文案按各平台规则调整。' },
      { title: '字幕', body: '烧录字幕，位置避开各平台的按钮和标题区。也可以导出 SRT 字幕文件。' },
      { title: '封面', body: '每条一张，按平台尺寸和信息流裁切出图。' },
      { title: '发布文案', body: '每条的标题、正文和标签，按平台字数限制写好，你可以直接改。' },
      { title: '质检报告', body: '每个文件的检查结果：哪些通过，红灯原因是什么，你改了什么。' },
      { title: '发布清单', body: '建议的发布节奏，加上在平台勾选 AI 内容声明的提醒。' },
    ],
  },
  local: {
    kicker: '本地与隐私',
    title: '在你的 Mac 上跑，用你自己的 AI',
    items: [
      { title: '素材不出本机', body: '视频和音频文件留在你的电脑上，语音转写和渲染都在本机完成。我们收不到你的素材。' },
      { title: 'AI 你自己选', body: '用你已有的 Claude Code 或 Codex 订阅，或者 Anthropic、OpenAI、DeepSeek、通义、Kimi 等的 API key，也可以用 Ollama 等本地模型。只有逐字稿文本、少量关键帧和标题会发给你选的 AI。' },
      { title: '成本可控', body: '我们的测试批次约 $0.03 / 条 AI 费用。用订阅或本地模型时，没有额外的 API 账单。' },
    ],
  },
  create: {
    kicker: '创作',
    badge: '即将推出',
    title: '从一句话到 AI 视频',
    body: '下一步是「创作」页：从脚本或想法生成视频（可灵、即梦 / Seedance、MiniMax），带分镜、积分预算和选条，然后和剪辑一样按平台出片。引擎里的 ai-video 流程已经可以用。',
  },
  oss: {
    kicker: '开源',
    title: '全部开源，MIT 许可',
    lede: '桌面应用、这个网站和剪辑引擎都在同一个仓库里。引擎也可以单独当 Claude Code 技能用，名字叫 video-studio：用中文或英文说需求就能剪，包括口播精剪、长视频切片、播客遮脸、讲解短片、vlog 等 12 种流程，以及封面、字幕、响度和多平台导出。',
    tested: '每个流程都在真实素材上测过，已知问题写在仓库的 VALIDATION.md 里。',
    button: '在 GitHub 查看',
    skillLabel: '当 Claude Code 技能用',
    sourceLabel: '从源码运行 Mac 版',
  },
  faq: {
    kicker: '常见问题',
    title: '常见问题',
    items: [
      {
        q: '免费吗？',
        a: '免费。千剪按 MIT 许可开源，桌面应用、引擎和网站都在 GitHub 上。你只需要为自己选的 AI 服务付费（或者用已有的订阅、本地模型）。',
      },
      {
        q: '用哪个 AI？',
        a: '你自己选：已登录的 Claude Code 或 Codex 订阅（不需要 API key），Anthropic、OpenAI、DeepSeek、通义、Kimi、GLM、OpenRouter、Gemini 等的 API key，或者 Ollama、LM Studio、vLLM 等本地模型。可以按任务分别指定。',
      },
      {
        q: '我的素材会去哪里？',
        a: '视频和音频默认留在你的电脑上，转写和渲染都在本机完成。为了选段、写标题和校对字幕，逐字稿文本、少量关键帧截图和标题会发给你配置的 AI 服务，按它的数据政策处理。用 AI 配音或 AI 视频生成时，文本和参考图会发给对应厂商。引擎用到的 MediaPipe 组件可能会向 Google 上报匿名使用统计，应用里会说明怎么关闭。',
      },
      {
        q: '它会自动帮我发帖吗？',
        a: '不会。千剪在内置浏览器里打开平台自己的上传页面，帮你填好视频、封面、标题、正文和标签，发布按钮由你自己点。',
      },
      {
        q: '支持 Windows 吗？',
        a: '目前只有 Apple 芯片的 Mac 版，Windows 版之后推出。引擎本身（Claude Code 技能）在 macOS 和 Linux 上都能用。',
      },
      {
        q: '发布时需要标注 AI 生成吗？',
        a: 'YouTube、TikTok、Instagram、Facebook、小红书、抖音、视频号、B站等平台对 AI 生成或 AI 处理过的内容有声明要求，具体以各平台当时的规则为准。发布清单默认提醒你勾选 AI 内容声明。',
      },
      {
        q: '视频里有别人（嘉宾、学员）怎么办？',
        a: '请先得到他们对出镜和声音使用的同意。没有同意的部分，可以给脸加贴纸遮挡、给名字标签打码、给学员变声，或者直接不用这一段。',
      },
    ],
  },
  footer: {
    feedback: '反馈 · GitHub Discussions',
    privacy: '隐私政策',
    terms: '使用条款',
    note: '本站不使用 cookie、统计脚本或第三方字体。',
  },
  legal: {
    draft: '草稿，发布前请审阅',
    draftBody: '这是一份初稿，还没有经过法律审阅，正式发布前需要核对和修改。',
    updated: '更新日期',
    back: '返回首页',
    privacyTitle: '隐私政策',
    termsTitle: '使用条款',
  },
} as const;
