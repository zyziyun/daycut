"""Engine-originated user text with a stable ``code`` + ``params``, so the desk can localise it (en / zh / fr ...)
without parsing English. Every message dict is ``{code, params, message, message_zh}``; the English ``message``
and Chinese ``message_zh`` stay for the CLI and older desks. The code list is documented in
``references/MESSAGES.md`` (keep the two in sync: ``tests/test_messages.py`` checks it).

    from vstudio import messages as M
    M.msg("plan-fallback", frm="claude-code", to="codex", why="auth-expired")
    M.coded("qc-loudness-off", "Loudness -9.1 LUFS (target -14)")   # a code for a text built elsewhere
"""
from __future__ import annotations

CATALOG = {
    # ---- AI providers (vstudio.llm)
    "llm-all-failed": ("Every AI provider failed ({providers})", "所有 AI 模型都失败了（{providers}）"),
    "llm-fallback": ("{frm} failed ({why}); {to} answered instead", "{frm} 没成功（{why}），改用了 {to}"),
    # ---- plan-segments (vstudio.batch.segplan)
    "plan-fallback": ("{frm} failed ({why}); the segments were planned by {to}",
                      "{frm} 没成功（{why}），这次由 {to} 规划切片"),
    "plan-segments-failed": ("Planning the segments failed ({providers}): {error}",
                             "切片规划失败（{providers}）：{error}"),
    "plan-short-filled": ("{provider} returned {n} usable segment(s); {missing} filled by the rule-based ranking",
                          "{provider} 只给出 {n} 条可用切片，另外 {missing} 条由规则补上"),
    "plan-title-too-long": ("{id}: {provider} title over {limit}: {title}",
                            "{id}：{provider} 给的标题超过 {limit} 字：{title}"),
    # ---- intake plan (vstudio.intake): risks / questions / warnings / planner
    "intake.risk.no-source": ("{recipe}: no long recording or screen recording to cut", "{recipe}: 没有找到可切的长录音/录屏"),
    "intake.risk.burned-longform": ("{file} has burned-in captions: vertical slices add a new caption layer; check "
                                    "after picking the segments", "{file} 已有烧录字幕：竖屏切片会再叠一层新字幕，建议在选段后检查"),
    "intake.risk.no-video": ("{recipe}: no video material found", "{recipe}: 没有找到视频素材"),
    "intake.risk.no-photos": ("{recipe}: no photos or videos found", "{recipe}: 没有找到照片或视频"),
    "intake.risk.aigc-credits": ("AI video is paid in credits: it stops at the budget checkpoint for your approval "
                                 "before generating", "AI 视频按积分计费：生成前会在“预算”检查点停下等你批准"),
    "intake.risk.unsupported-platform": ("{platforms}: no export preset yet; exported for the closest platform",
                                         "{platforms} 还没有导出预设：先按最接近的平台导出"),
    "intake.risk.no-projects": ("No runnable project could be made from these materials and the request",
                                "没能从这些素材和描述里拼出可执行的项目"),
    "intake.risk.unused-inputs": ("Not used in any project: {files}. Say which project they belong to if you want them in",
                                  "这些素材没有用在任何项目里：{files}。要用的话告诉我放进哪个项目"),
    "intake.question.mask-faces": ("Whose faces should be hidden? (default: every guest but you)",
                                   "要遮哪几位的脸？（默认：除你以外的所有嘉宾）"),
    "intake.question.narration": ("Narration (AI voice reads your copy) or music only?",
                                  "文艺片要旁白（AI 配音读你的文案）还是纯音乐卡点？"),
    "intake.option.mask.all-but-me": ("Hide everyone but me", "除我以外全部遮"),
    "intake.option.mask.none": ("Hide no one (they agreed)", "都不遮（已获同意）"),
    "intake.option.mask.pick": ("I'll pick", "我来指定"),
    "intake.option.narration.voice": ("Narration", "旁白"),
    "intake.option.narration.music": ("Music only", "纯音乐"),
    "intake.need.footage": ("Add the recordings you want cut - this request edits your own video. Drop them here",
                            "把要剪的录像拖进来：这个请求是剪你自己的视频"),
    "intake.need.notion": ("Which Notion pages? Paste their links (pages shared to the web), or export them in Notion "
                           "(••• › Export › Markdown & CSV), unzip and drop the folder here",
                           "要用哪些 Notion 页面？贴上页面链接（已公开分享到网页的），或在 Notion 里导出（••• › 导出 › "
                           "Markdown & CSV），解压后把文件夹拖进来"),
    "intake.need.notion-private": ("Couldn't read this Notion page ({url}): it isn't shared to the web. Share it, or "
                                   "export it (••• › Export › Markdown & CSV), unzip and drop the folder here",
                                   "读不到这个 Notion 页面（{url}）：它没有公开分享到网页。打开分享，或导出（••• › 导出 › "
                                   "Markdown & CSV），解压后把文件夹拖进来"),
    "intake.need.page-unreadable": ("Couldn't read {url}. Save the page as a PDF or Markdown file and drop it here",
                                    "读不到 {url}。把这个页面存成 PDF 或 Markdown 文件拖进来"),
    "intake.question": ("{text}", "{text}"),
    "intake.risk": ("{text}", "{text}"),
    "intake.warning": ("{text}", "{text}"),
    "intake.warning.unknown-recipe": ("Dropped a sub-project with the unknown recipe {recipe} (only catalog recipes run)",
                                      "去掉了一个未知配方 {recipe} 的子项目（只运行目录里的配方）"),
    "intake.warning.batch-recipe": ("The batch recipe is an engine board; use the deliverable recipe instead (dropped)",
                                    "batch 是引擎看板，不是成品配方（已去掉）"),
    "intake.warning.unknown-input": ("{project} {recipe}: unknown input {key} dropped", "{project} {recipe}：未知输入 {key} 已去掉"),
    "intake.warning.input-not-accepted": ("{project} {recipe}: input {key} does not accept {files}",
                                          "{project} {recipe}：输入 {key} 不接受 {files}"),
    "intake.warning.input-single": ("{project} {recipe}: input {key} takes one file; kept {file}",
                                    "{project} {recipe}：输入 {key} 只要一个文件，保留了 {file}"),
    "intake.warning.input-single-broll": ("{project} {recipe}: input {key} takes one file; kept {file}, the other "
                                          "videos go to {to}", "{project} {recipe}：输入 {key} 只要一个文件，保留了 {file}，"
                                          "其余视频放进 {to}"),
    "intake.warning.range-dropped": ("{project} row {row}: range {range} too short or outside the media, dropped",
                                     "{project} 第 {row} 行：区间 {range} 太短或超出素材，已去掉"),
    "intake.warning.unknown-param": ("{project} {recipe}: unknown param {key} dropped", "{project} {recipe}：未知参数 {key} 已去掉"),
    "intake.warning.platform-unsupported": ("{project} {recipe}: platform {platform} not supported by this recipe "
                                            "(dropped)", "{project} {recipe}：这个配方不支持平台 {platform}（已去掉）"),
    "intake.warning.param-invalid": ("{project} {recipe}: param {key}={value} invalid for the recipe (reset to default)",
                                     "{project} {recipe}：参数 {key}={value} 不合法（已恢复默认）"),
    "intake.warning.required-input-missing": ("{project} {recipe}: required input {key} has no material (sub-project "
                                              "dropped)", "{project} {recipe}：必需的输入 {key} 没有素材（子项目已去掉）"),
    "intake.warning.focus-unmatched": ("{project}: no transcript passage matched the focus; ranges will be chosen at "
                                       "the segments step", "{project}：逐字稿里没找到对应内容，选段步骤再定区间"),
    "intake.warning.revise-not-understood": ("Did not understand this change: {instruction} (plan unchanged)",
                                             "没看懂这条修改：{instruction}（计划未变）"),
    "intake.warning.schema": ("Plan schema: {error}", "计划格式问题：{error}"),
    "intake-burned-subs": ("The video already has captions burned in: the old captions are cropped off and new ones "
                           "go in a band", "视频里已经有烧录字幕：裁掉旧字幕，新字幕放在字幕条里"),
    "intake-no-model": ("No AI model is set up for planning: the rule planner made this plan",
                        "没有配置 AI 规划模型，这份计划由规则生成"),
    "intake-rule-plan": ("The AI plan was not usable ({reason}): the rule planner made this plan",
                         "AI 给的计划不可用（{reason}），这份计划由规则生成"),
    "intake.summary": ("{text}", "{text}"),
    "intake-model-fallback": ("The AI planner was not available ({reason}): the rule planner made this plan",
                              "AI 规划没成功（{reason}），这份计划由规则生成"),
    # ---- model text passed through as is (the desk shows it in the language it came in)
    "ai-summary": ("{text}", "{text}"),
    "ai-why": ("{text}", "{text}"),
    "status-text": ("{text}", "{text}"),
    "qc.other": ("{name}: {reason}", "{name}：{reason}"),
}

# French (the desk's fr locale, the engine's ``lang="fr"``). "{text}" codes pass the text through untranslated.
FR = {
    "intake.need.footage": "Ajoutez les enregistrements à monter - cette demande monte votre propre vidéo. Déposez-les ici",
    "intake.need.notion": "Quelles pages Notion ? Collez leurs liens (pages partagées sur le web), ou exportez-les dans "
                          "Notion (••• › Exporter › Markdown & CSV), décompressez et déposez le dossier ici",
    "intake.need.notion-private": "Impossible de lire cette page Notion ({url}) : elle n'est pas partagée sur le web. "
                                  "Partagez-la, ou exportez-la (••• › Exporter › Markdown & CSV), décompressez et déposez "
                                  "le dossier ici",
    "intake.need.page-unreadable": "Impossible de lire {url}. Enregistrez la page en PDF ou en Markdown et déposez-la ici",
    "llm-all-failed": "Tous les fournisseurs d'IA ont échoué ({providers})",
    "llm-fallback": "{frm} a échoué ({why}) ; {to} a répondu à la place",
    "plan-fallback": "{frm} a échoué ({why}) ; les extraits ont été choisis par {to}",
    "plan-segments-failed": "Le choix des extraits a échoué ({providers}) : {error}",
    "plan-short-filled": "{provider} a donné {n} extrait(s) utilisable(s) ; {missing} complété(s) par les règles",
    "plan-title-too-long": "{id} : titre de {provider} au-delà de {limit} : {title}",
    "intake.risk.no-source": "{recipe} : aucun long enregistrement ou enregistrement d'écran à découper",
    "intake.risk.burned-longform": "{file} a des sous-titres incrustés : les extraits verticaux ajoutent une "
                                   "nouvelle couche ; vérifiez après le choix des extraits",
    "intake.risk.no-video": "{recipe} : aucune vidéo trouvée",
    "intake.risk.no-photos": "{recipe} : aucune photo ni vidéo trouvée",
    "intake.risk.aigc-credits": "La vidéo IA se paie en crédits : elle s'arrête au point de contrôle du budget "
                                "pour votre accord avant de générer",
    "intake.risk.unsupported-platform": "{platforms} : pas encore de préréglage d'export ; exporté pour la "
                                        "plateforme la plus proche",
    "intake.risk.no-projects": "Impossible de composer un projet à partir de ces fichiers et de cette demande",
    "intake.risk.unused-inputs": "Utilisé dans aucun projet : {files}. Dites dans quel projet les mettre si vous "
                                 "les voulez",
    "intake.question.mask-faces": "Quels visages masquer ? (par défaut : tous les invités sauf vous)",
    "intake.question.narration": "Narration (voix IA qui lit votre texte) ou musique seule ?",
    "intake.option.mask.all-but-me": "Masquer tout le monde sauf moi",
    "intake.option.mask.none": "Ne masquer personne (accord donné)",
    "intake.option.mask.pick": "Je choisis",
    "intake.option.narration.voice": "Narration",
    "intake.option.narration.music": "Musique seule",
    "intake.warning.unknown-recipe": "Sous-projet à la recette inconnue {recipe} retiré (seules les recettes du "
                                     "catalogue s'exécutent)",
    "intake.warning.batch-recipe": "La recette batch est un tableau du moteur ; utilisez la recette du livrable "
                                   "(retiré)",
    "intake.warning.unknown-input": "{project} {recipe} : entrée inconnue {key} retirée",
    "intake.warning.input-not-accepted": "{project} {recipe} : l'entrée {key} n'accepte pas {files}",
    "intake.warning.input-single": "{project} {recipe} : l'entrée {key} prend un seul fichier ; {file} gardé",
    "intake.warning.input-single-broll": "{project} {recipe} : l'entrée {key} prend un seul fichier ; {file} gardé, "
                                         "les autres vidéos vont dans {to}",
    "intake.warning.range-dropped": "{project} ligne {row} : plage {range} trop courte ou hors du média, retirée",
    "intake.warning.unknown-param": "{project} {recipe} : paramètre inconnu {key} retiré",
    "intake.warning.platform-unsupported": "{project} {recipe} : plateforme {platform} non prise en charge par "
                                           "cette recette (retirée)",
    "intake.warning.param-invalid": "{project} {recipe} : paramètre {key}={value} invalide (valeur par défaut "
                                    "rétablie)",
    "intake.warning.required-input-missing": "{project} {recipe} : l'entrée requise {key} n'a pas de fichier "
                                             "(sous-projet retiré)",
    "intake.warning.focus-unmatched": "{project} : aucun passage de la transcription ne correspond ; les plages "
                                      "seront choisies à l'étape des extraits",
    "intake.warning.revise-not-understood": "Modification non comprise : {instruction} (plan inchangé)",
    "intake.warning.schema": "Schéma du plan : {error}",
    "intake-burned-subs": "La vidéo a déjà des sous-titres incrustés : ils sont rognés et les nouveaux vont dans "
                          "une bande",
    "intake-no-model": "Aucun modèle d'IA n'est configuré pour la planification : ce plan vient des règles",
    "intake-rule-plan": "Le plan de l'IA n'était pas utilisable ({reason}) : ce plan vient des règles",
    "intake-model-fallback": "Le planificateur IA n'était pas disponible ({reason}) : ce plan vient des règles",
    "qc.other": "{name} : {reason}",
    "stage.plan": "Planification", "stage.probe": "Lecture du fichier", "stage.extract": "Extraction de l'audio",
    "stage.asr": "Transcription", "stage.hooks": "Recherche d'accroches", "stage.cleanup": "Recherche des pauses et "
    "tics", "stage.apply": "Découpe", "stage.face": "Suivi du visage",
    "stage.notes": "Notes et mots-clés", "stage.compose": "Composition",
    "stage.cover_frames": "Couvertures candidates", "stage.verify": "Vérification à l'écoute",
    "stage.glossary": "Glossaire", "stage.proofread": "Relecture des sous-titres", "stage.export": "Export",
    "stage.qc": "Contrôle qualité", "stage.preview": "Aperçu", "stage.render": "Rendu",
    "stage.geometry": "Détection de l'écran", "stage.package": "Empaquetage", "stage.segments": "Choix des extraits",
    "stage.ai": "Demande à l'IA", "stage.ask": "Demande à l'IA", "stage.read": "Lecture des vidéos",
    "stage.check": "Vérification", "stage.other": "{stage}",
    "status.running": "En cours", "status.waiting": "À vous de jouer", "status.done": "Terminé",
    "status.failed": "Échec", "status.interrupted": "Interrompu",
    "checkpoint.filler-confirm": "Confirmer les coupes de tics", "inbox.filler-confirm": "Des coupes de tics "
    "attendent votre accord", "checkpoint.hook-pick": "Choisir l'accroche", "inbox.hook-pick": "Choisissez "
    "l'ouverture", "checkpoint.segment-approval": "Valider les extraits", "inbox.segment-approval": "Vérifiez les "
    "extraits proposés", "checkpoint.script-lock": "Verrouiller le script", "inbox.script-lock": "Verrouillez le "
    "script avant la génération", "checkpoint.storyboard-approval": "Valider le storyboard",
    "inbox.storyboard-approval": "Vérifiez le storyboard", "checkpoint.budget-approval": "Valider le budget",
    "inbox.budget-approval": "Validez la dépense avant toute génération payante",
    "checkpoint.take-selection": "Choisir les prises", "inbox.take-selection": "Choisissez les prises à utiliser",
    "checkpoint.keywords": "Vérifier les mots-clés en couleur", "inbox.keywords": "Vérifiez les mots colorés dans "
    "les sous-titres",
    "checkpoint.cover-pick": "Choisir la couverture", "inbox.cover-pick": "Choisissez une couverture",
    "checkpoint.privacy-masks": "Vérifier les masques", "inbox.privacy-masks": "Vérifiez qui est masqué",
    "checkpoint.consent": "Confirmer le consentement", "inbox.consent": "Confirmez l'accord des personnes filmées",
    "checkpoint.publish": "Relire avant publication", "inbox.publish": "Relisez la publication avant l'envoi",
    "checkpoint.author": "Écrire ou valider le texte", "inbox.author": "Écrivez ou validez le texte",
    "checkpoint.music-pick": "Choisir la musique", "inbox.music-pick": "Choisissez la musique",
    "checkpoint.voice-pick": "Choisir la voix", "inbox.voice-pick": "Choisissez la voix",
    "checkpoint.media-selection": "Choisir les médias", "inbox.media-selection": "Choisissez les médias à utiliser",
    "checkpoint.review": "Relecture", "inbox.review": "Regardez le résultat",
    "job-state.planned": "À faire", "job-state.running": "En cours", "job-state.waiting": "À vous de jouer",
    "job-state.done": "Terminé", "job-state.failed": "Échec", "job-state.interrupted": "Interrompu",
    "job-state.packaged": "Empaqueté", "job-state.skipped": "Ignoré", "job-state.unverified": "Pas encore vérifié",
    "job-state.approved": "Validé", "job-state.rejected": "Refusé",
    "project-state.new": "Nouveau", "project-state.planned": "À faire", "project-state.running": "En cours",
    "project-state.needs-you": "À vous de jouer", "project-state.error": "Échec", "project-state.paused": "En pause",
    "project-state.interrupted": "Interrompu", "project-state.done": "Terminé",
    "qc-state.green": "Contrôles réussis", "qc-state.red": "Contrôles échoués", "qc-state.none": "Pas encore vérifié",
    "post-state.planned": "Prévu", "post-state.approved": "Validé", "post-state.scheduled": "Programmé",
    "post-state.posted": "Publié", "post-state.skipped": "Ignoré",
    "qc.loudness": "Volume {value} LUFS (cible {lufs})", "qc.true-peak": "Crête {value} dBTP au-dessus de {tp}",
    "qc.av-sync": "Décalage son / image de {value} s", "qc.black-frames": "Images noires à {spans}",
    "qc.frozen-frames": "Image figée à {spans}", "qc.length": "Durée {value} s : {reason}",
    "qc.length-sweet-spot": "Durée {value} s hors de la zone idéale", "qc.length-plan": "Trop long pour la "
    "plateforme : {reason}", "qc.max-len": "{value} s au-delà de la durée maximale",
    "qc.title": "Titre trop long pour {platform}", "qc.canvas": "Mauvaise taille de canevas {value}",
    "qc.safe-zone": "Sous-titres hors de la zone sûre", "qc.caption-hallucination": "{value} ligne(s) de "
    "sous-titres inventée(s)", "qc.lost-words": "{value} mot(s) perdu(s) à la coupe", "qc.exports": "Aucun export",
    "qc.caption-edit-missed": "{value} correction(s) de sous-titres non appliquée(s)",
    "qc.export-warning": "Avertissement d'export : {reason}", "qc.privacy": "Contrôle de confidentialité : {reason}",
}

# status.json stages (vstudio.batch.livestatus) and batch stages: stage.<id>
STAGES = {
    "plan": ("Planning", "规划中"), "probe": ("Reading the file", "读取文件"), "extract": ("Extracting audio", "提取音频"),
    "asr": ("Transcribing", "语音转文字"), "hooks": ("Finding hooks", "找开场"), "cleanup": ("Finding pauses and fillers", "找气口和口癖"),
    "apply": ("Cutting", "剪辑中"), "face": ("Tracking the face", "跟踪人脸"),
    "notes": ("Drafting notes and keywords", "起草笔记和关键词"), "compose": ("Composing", "合成中"),
    "cover_frames": ("Cover candidates", "封面候选"), "verify": ("Checking the cut by ear", "回听检查"),
    "glossary": ("Building the glossary", "整理术语表"), "proofread": ("Proofreading captions", "校对字幕"),
    "export": ("Exporting", "导出中"), "qc": ("Quality check", "质量检查"), "preview": ("Preview", "预览"),
    "render": ("Rendering", "渲染中"), "geometry": ("Finding the screen", "识别屏幕区域"), "package": ("Packaging", "打包中"),
    "segments": ("Picking segments", "选段中"), "ai": ("Asking the AI", "AI 处理中"), "ask": ("Asking the AI", "AI 处理中"),
    "read": ("Reading the outputs", "读取成片"), "check": ("Checking", "检查中"), "other": ("{stage}", "{stage}"),
}
STATUS = {"running": ("Running", "进行中"), "waiting": ("Needs you", "需要你"), "done": ("Done", "已完成"),
          "failed": ("Failed", "失败"), "interrupted": ("Interrupted", "已中断")}
# checkpoint kinds (inbox / plan "needs you"): checkpoint.<kind> = the label, inbox.<kind> = the reason line
CHECKPOINTS = {
    "filler-confirm": ("Confirm filler cuts", "确认去口癖", "Filler cuts need your yes", "有口癖剪辑等你确认"),
    "hook-pick": ("Pick the hook", "选开头", "Pick the cold open", "从候选里选开场"),
    "segment-approval": ("Approve the segments", "确认选段", "Check the proposed segments", "看一下选段"),
    "script-lock": ("Lock the script", "锁定剧本", "Lock the script before generating", "生成前先锁定剧本"),
    "storyboard-approval": ("Approve the storyboard", "确认分镜", "Check the storyboard", "看一下分镜"),
    "budget-approval": ("Approve the budget", "批准预算", "Approve the spend before anything paid runs",
                        "付费生成前请批准预算"),
    "take-selection": ("Pick the takes", "选镜头", "Pick the takes to use", "选要用的镜头"),
    "keywords": ("Check the highlighted keywords", "确认高亮关键词", "Check the words coloured in the captions",
                 "看一下字幕里变色的关键词"),
    "cover-pick": ("Pick the cover", "选封面", "Pick a cover", "从候选里选封面"),
    "privacy-masks": ("Check the privacy masks", "检查打码", "Check who is masked", "确认打码的人和区域"),
    "consent": ("Confirm consent", "确认授权", "Confirm the people shown agreed", "确认出镜的人已同意"),
    "publish": ("Review before publishing", "发布前确认", "Review the post before it goes out", "发布前看一眼"),
    "author": ("Write or approve the text", "写 / 确认文字", "Write or approve the text", "写或确认文字"),
    "music-pick": ("Pick the music", "选音乐", "Pick the music", "选配乐"),
    "voice-pick": ("Pick the voice", "选声音", "Pick the voice", "选配音"),
    "media-selection": ("Pick the media", "选素材", "Pick the media to use", "选要用的素材"),
    "review": ("Review", "审片", "Review the result", "看一下成片"),
}
JOB_STATES = {"planned": ("To do", "待做"), "running": ("Running", "进行中"), "waiting": ("Needs you", "需要你"), "done": ("Done", "已完成"),
              "failed": ("Failed", "失败"), "interrupted": ("Interrupted", "已中断"), "packaged": ("Packaged", "已打包"),
              "skipped": ("Skipped", "已跳过"), "unverified": ("Not checked yet", "未验证"),
              "approved": ("Approved", "已通过"), "rejected": ("Rejected", "已退回")}
PROJECT_STATES = {"new": ("New", "新建"), "planned": ("To do", "待做"), "running": ("Running", "进行中"),
                  "needs-you": ("Needs you", "需要你"), "error": ("Failed", "失败"), "paused": ("Paused", "已暂停"),
                  "interrupted": ("Interrupted", "已中断"), "done": ("Done", "已完成")}
QC_STATES = {"green": ("Checks passed", "检查通过"), "red": ("Checks failed", "检查没通过"),
             None: ("Not checked yet", "未验证")}
POST_STATES = {"planned": ("Planned", "计划中"), "approved": ("Approved", "已确认"), "scheduled": ("Scheduled", "已排期"),
               "posted": ("Posted", "已发布"), "skipped": ("Skipped", "已跳过")}
# QC checks (vstudio.batch.qc): qc.<name>
QC = {
    "loudness": ("Loudness {value} LUFS (target {lufs})", "响度 {value} LUFS（目标 {lufs}）"),
    "true-peak": ("True peak {value} dBTP over {tp}", "真峰值 {value} dBTP，超过 {tp}"),
    "av-sync": ("Sound and picture drift by {value} s", "音画差 {value} 秒"),
    "black-frames": ("Black frames at {spans}", "{spans} 有黑帧"),
    "frozen-frames": ("Frozen picture at {spans}", "{spans} 画面卡住"),
    "length": ("Length {value} s: {reason}", "时长 {value} 秒：{reason}"),
    "length-sweet-spot": ("Length {value} s is outside the sweet spot", "时长 {value} 秒不在最佳区间"),
    "length-plan": ("Too long for the platform: {reason}", "比平台建议时长长：{reason}"),
    "max-len": ("{value} s over the max length", "{value} 秒超过最长限制"),
    "title": ("Title too long for {platform}", "标题超过 {platform} 的长度限制"),
    "canvas": ("Wrong canvas size {value}", "画布尺寸不对 {value}"),
    "safe-zone": ("Captions outside the safe zone", "字幕超出安全区"),
    "caption-hallucination": ("{value} invented caption line(s)", "有 {value} 行字幕是识别瞎编的"),
    "lost-words": ("{value} word(s) lost in the cut", "剪掉了 {value} 个词"),
    "exports": ("No exports", "没有导出文件"),
    "caption-edit-missed": ("{value} caption edit(s) could not be applied", "{value} 处字幕修改没能应用"),
    "export-warning": ("Export warning: {reason}", "导出提醒：{reason}"),
    "privacy": ("Privacy check: {reason}", "隐私检查：{reason}"),
}
for _k, (_en, _zh) in STAGES.items():
    CATALOG[f"stage.{_k}"] = (_en, _zh)
for _k, (_en, _zh) in STATUS.items():
    CATALOG[f"status.{_k}"] = (_en, _zh)
for _k, (_l, _lz, _r, _rz) in CHECKPOINTS.items():
    CATALOG[f"checkpoint.{_k}"] = (_l, _lz)
    CATALOG[f"inbox.{_k}"] = (_r, _rz)
for _k, (_en, _zh) in JOB_STATES.items():
    CATALOG[f"job-state.{_k}"] = (_en, _zh)
for _k, (_en, _zh) in PROJECT_STATES.items():
    CATALOG[f"project-state.{_k}"] = (_en, _zh)
for _k, (_en, _zh) in QC_STATES.items():
    CATALOG[f"qc-state.{_k or 'none'}"] = (_en, _zh)
for _k, (_en, _zh) in POST_STATES.items():
    CATALOG[f"post-state.{_k}"] = (_en, _zh)
for _k, (_en, _zh) in QC.items():
    CATALOG[f"qc.{_k}"] = (_en, _zh)
# families whose code carries an id (documented as a pattern in references/MESSAGES.md)
FAMILIES = ("recipe.<id>.label", "recipe.<id>.description")


def _fmt(t, params):
    try:
        return t.format(**{k: ("" if v is None else v) for k, v in params.items()})
    except (KeyError, IndexError, ValueError):
        return t


def msg(code, message=None, message_zh=None, **params):
    """{code, params, message, message_zh}: the catalog texts (``message`` / ``message_zh`` override them)."""
    en, zh = CATALOG.get(code, (message or code, message_zh or message or code))
    return dict(code=code, params=params, message=message if message is not None else _fmt(en, params),
                message_zh=message_zh if message_zh is not None else _fmt(zh, params))


def coded(code, text, text_zh=None, **params):
    """A message for a text that is already built (e.g. a QC reason): the text rides in ``params.text``."""
    return msg(code, text, text_zh if text_zh is not None else text, text=text, **params)


def text(code, **params):
    return msg(code, **params)["message"]


class Coded(str):
    """A plain string (what older readers get) that also carries its message dict (``.info``)."""

    def __new__(cls, value, info):
        o = str.__new__(cls, value)
        o.info = info
        return o

    def __reduce__(self):
        return (Coded, (str(self), self.info))


def cs(code, lang="zh", **params):
    """A ``Coded`` string in ``lang`` (zh | en | fr: the language the list is read in) for catalog ``code``; French
    falls back to English for a code with no French."""
    m = msg(code, **params)
    if lang == "fr" and code in FR:
        return Coded(_fmt(FR[code], params), m)
    return Coded(m["message_zh"] if lang == "zh" else m["message"], m)


def join(items, lang="zh"):
    """A list inside a message, punctuated for ``lang`` (、 in Chinese, a comma otherwise)."""
    return ("、" if lang == "zh" else ", ").join(str(x) for x in items)


def info_of(x, family="status-text"):
    """The message dict of a list entry: its own (``Coded``), else the text under the generic ``family`` code."""
    if isinstance(x, dict) and "code" in x and "message" in x:
        return x
    return getattr(x, "info", None) or coded(family, str(x))


def stage(stage_id, **params):
    s = str(stage_id or "")
    return msg(f"stage.{s}", stage=s, **params) if f"stage.{s}" in CATALOG else msg("stage.other", stage=s, **params)


def checkpoint(kind, **params):
    p = dict(n=params.pop("n", None) or "", **params)
    return dict(label=msg(f"checkpoint.{kind}", **p) if f"checkpoint.{kind}" in CATALOG else coded("status-text", kind),
                reason=msg(f"inbox.{kind}", **p) if f"inbox.{kind}" in CATALOG else coded("status-text", kind))


def state(family, value):
    """job-state / post-state / status message for ``value`` (unknown -> the generic text code)."""
    c = f"{family}.{'none' if value is None else value}"
    return msg(c) if c in CATALOG else coded("status-text", str(value))


def recipe(m):
    """{label, description} messages of a recipe manifest (its own zh / en texts, code recipe.<id>.*)."""
    rid = m.get("id")
    lab, desc = m.get("labels") or {}, m.get("description") or {}
    return dict(label=dict(code=f"recipe.{rid}.label", params={}, message=lab.get("en") or rid,
                           message_zh=lab.get("zh") or lab.get("en") or rid),
                description=dict(code=f"recipe.{rid}.description", params={}, message=desc.get("en") or "",
                                 message_zh=desc.get("zh") or desc.get("en") or ""))


__all__ = ["CATALOG", "STAGES", "STATUS", "CHECKPOINTS", "JOB_STATES", "POST_STATES", "QC", "msg", "coded", "text",
           "Coded", "cs", "info_of", "stage", "checkpoint", "state", "recipe"]
