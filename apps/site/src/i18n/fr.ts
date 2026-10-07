// Textes en français. Règles d'écriture : README « Copy rules » ; `npm run check:copy` les vérifie.
// Même structure que zh.ts (vérifiée par le typage). Les pages légales /fr/privacy et /fr/terms affichent la version
// anglaise pour l'instant (voir Privacy.astro / Terms.astro).
import type { zh } from './zh';

type Widen<T> = T extends string
  ? string
  : T extends readonly (infer U)[]
    ? readonly Widen<U>[]
    : T extends object
      ? { readonly [K in keyof T]: Widen<T[K]> }
      : T;

export const fr: Widen<typeof zh> = {
  lang: 'fr',
  htmlLang: 'fr',
  meta: {
    title: 'Reelfold · Un enregistrement, déplié sur toutes les plateformes',
    description:
      'Reelfold est une application Mac gratuite et open source (MIT) qui transforme un enregistrement en clips prêts pour chaque plateforme. Décrivez le lot, l’IA le planifie, le montage tourne sur votre Mac, vous ne relisez que ce que les contrôles signalent, et il remplit chaque publication pour YouTube, TikTok, Instagram, X, LinkedIn, Xiaohongshu, Douyin, Bilibili et d’autres. C’est vous qui publiez.',
  },
  nav: {
    how: 'Fonctionnement',
    uses: 'Pour qui',
    app: 'App Mac',
    proof: 'Chiffres réels',
    local: 'En local',
    oss: 'Open source',
    faq: 'FAQ',
    langGroup: 'Langue',
    skip: 'Aller au contenu',
  },
  cta: {
    download: 'Télécharger pour macOS',
    soon: 'App macOS : bientôt',
    soonNote: 'La première version macOS arrive bientôt. En attendant, compilez-la depuis les sources ou utilisez le moteur comme skill Claude Code.',
    star: 'Star sur GitHub',
    source: 'Compiler depuis les sources',
    windows: 'Windows : plus tard',
  },
  hero: {
    eyebrow: 'Gratuit et open source (MIT) · app macOS · Apple Silicon',
    titleA: 'Décrivez. Déposez les rushes.',
    titleB: 'Chaque montage, pour chaque plateforme.',
    sub: 'Un enregistrement, déplié sur toutes les plateformes. Dites ce que vous voulez avec vos mots et déposez une interview, un podcast, un cours ou le lot d’un client. L’IA choisit les extraits, tout le lot tourne sur votre Mac, et vous ne relisez que ce que les contrôles signalent. Chaque plateforme reçoit sa vidéo, sa couverture et son texte ; c’est vous qui publiez.',
    points: [
      'Vos rushes restent sur votre Mac',
      'Vous ne relisez que les clips signalés par les contrôles',
      'Publication assistée : il remplit, vous publiez',
    ],
    stickerA: 'Xiaohongshu 3:4',
    stickerB: 'Contrôle OK',
    stickerC: '1 enregistrement → 96 fichiers',
    frameAlts: [
      'Format face caméra avec sous-titres et panneau de notes',
      'Extrait de cours montrant du code, avec un bandeau titre sur la recherche hybride',
      'Vidéo pédagogique avec deux intervenants et un panneau de notes',
    ],
  },
  how: {
    kicker: 'Fonctionnement',
    title: 'Un enregistrement en entrée, un lot complet en sortie',
    steps: [
      {
        title: 'Décrire',
        body: 'Déposez un enregistrement (interview, podcast, cours, rediffusion de live ou rushes d’un client) et dites avec vos mots combien de clips, pour quelles plateformes, dans quel style.',
      },
      {
        title: 'L’IA planifie',
        body: 'L’IA choisit les passages par sujet et rédige un plan lisible et modifiable : quel passage devient quel clip, son titre, et sa destination.',
      },
      {
        title: 'Le lot tourne',
        body: 'Tout le lot tourne en parallèle sur votre Mac : pauses, tics de langage et répétitions retirés ; sous-titres, bandeaux titres, zooms sur le code et panneaux de notes ajoutés.',
      },
      {
        title: 'Relire les exceptions',
        body: 'Chaque fichier est vérifié : volume sonore, synchro audio/vidéo, mots manquants dans les sous-titres, texte sous les boutons de l’app, durée et longueur du titre. Seuls les rouges arrivent dans votre grille de relecture ; corrigez-les dans la transcription et refaites le rendu de ceux-là seulement.',
      },
      {
        title: 'Publication assistée',
        body: 'Chaque plateforme reçoit son export, sa couverture, son titre, sa description, ses hashtags et un rappel pour la mention de contenu IA. Reelfold remplit la page de mise en ligne ; vous vérifiez et publiez. Il ne publie jamais tout seul.',
      },
    ],
    platformsLabel: 'Plateformes',
    platforms: ['YouTube 16:9 + Shorts 9:16', 'TikTok 9:16', 'Instagram Reels 9:16 + fil 4:5', 'X 16:9 / 1:1 / 9:16', 'Facebook Reels 9:16 + fil 4:5', 'LinkedIn 16:9 / 1:1', 'Threads 9:16', 'Reddit 16:9', 'Pinterest 9:16', 'Snapchat Spotlight 9:16', 'Xiaohongshu 3:4', 'Douyin 9:16', 'WeChat Channels 9:16', 'Bilibili 16:9', 'Kuaishou 9:16', 'Weibo 16:9', 'Zhihu 16:9', 'Dailymotion 16:9', 'Kwai 9:16'],
  },
  uses: {
    kicker: 'Pour qui',
    title: 'Pour celles et ceux qui montent en série et publient partout',
    lede: 'Un seul moteur, plein de types de rushes. Chaque workflow a été testé sur de vrais enregistrements.',
    items: [
      { title: 'Créateurs en série', body: 'Enregistrez une fois, publiez toute la semaine. Une session devient une série de clips, chacun au format, à la durée et au volume sonore attendus par chaque plateforme.' },
      { title: 'Interviews et podcasts', body: 'Tirez de nombreux clips d’une longue conversation, avec sous-titres et cadrage sur l’intervenant, et un export distinct par plateforme. Visages des invités masqués et noms floutés si besoin.' },
      { title: 'Studios et lots clients', body: 'Menez les lots de plusieurs clients en parallèle sur un même tableau. Gardez le style et le glossaire de chaque client, avec un rapport de contrôle pour chaque lot.' },
      { title: 'Face caméra', body: 'Retirez pauses, tics de langage et répétitions, puis ajoutez sous-titres, mots-clés animés, barre de progression des chapitres et couverture.' },
      { title: 'Découpage de cours', body: 'Transformez un long cours en extraits verticaux ou en épisodes, avec bandeaux titres, recadrages du code qui suivent le texte et cartons de chapitre. La voix des étudiants peut être modifiée.' },
      { title: 'Vidéos explicatives', body: 'Vidéos façon 3Blue1Brown avec narration IA, scènes animées et sous-titres bilingues, à partir d’un script ou d’un sujet.' },
    ],
  },
  app: {
    kicker: 'Application',
    title: 'Reelfold pour Mac',
    lede: 'Décrivez le lot avec vos mots. Reelfold le planifie, lance les tâches en parallèle sur votre propre ordinateur et les suit sur un tableau. Relisez les clips dans une grille et coupez en éditant la transcription. Au moment de publier, il remplit la page de mise en ligne de chaque plateforme dans un navigateur intégré, et c’est vous qui publiez.',
    note: 'Gratuit et open source (MIT). Mac Apple Silicon uniquement pour l’instant. L’IA passe par votre abonnement Claude Code ou Codex, vos clés d’API ou un modèle local.',
    board: {
      cols: ['En attente', 'Rendu', 'Contrôle', 'Relecture', 'Validé'],
      cards: ['ep03 · RRF ne voit que les rangs', 'ep06 · petits blocs', 'ep11 · quelle métrique d’abord', 'ep14 · parent-enfant', 'ep19 · reclassement'],
      green: 'vert',
      red: 'rouge · mot peut-être perdu au raccord',
      caption: 'Illustration du tableau de lots (pas une capture d’écran).',
    },
  },
  proof: {
    kicker: 'Chiffres réels',
    title: 'Un vrai lot avec l’outil open source',
    lede: 'Nous y avons passé l’un de nos propres cours de 72 minutes, en un seul lot. Voici ce qui a marché, et ce qui n’a pas marché.',
    stats: [
      { value: '96', label: 'fichiers finis', note: '24 clips × 4 formats de plateforme, chacun avec couverture et texte de publication' },
      { value: '0,73 $', label: 'coût d’API IA pour le lot', note: 'Environ 0,03 $ par clip ; transcription en local' },
      { value: '21 / 24', label: 'clips validés par le contrôle', note: 'Les 3 clips rouges étaient sur des raccords et sont allés dans la grille de relecture' },
      { value: '3–4 h', label: 'temps machine au premier passage', note: 'Après correction, relancer seulement les 13 clips concernés a pris 18 minutes' },
    ],
    caveatsTitle: 'Ce qui n’est pas encore assez bon',
    caveats: [
      'Les sous-titres chinois contiennent encore des erreurs de mots. Un glossaire en corrige une partie ; vous rattrapez le reste à la relecture.',
      'Les coupes de tics de langage vous posent encore trop de questions oui/non (environ 15 par clip dans ce lot). Nous travaillons à laisser passer automatiquement les cas sans risque.',
      'Quand le texte à l’écran est petit dans la source, il devient difficile à lire après un recadrage vertical.',
    ],
    stripCaption: 'Images de six types de montage réalisés avec les mêmes outils : face caméra, extraits de cours, récit photo, vlog de voyage, podcast avec visages masqués et vidéo explicative.',
    stripAlts: [
      'Format face caméra avec sous-titres et panneau de notes',
      'Extrait de cours avec code et bandeau titre',
      'Récit photo comparant une esquisse et le tableau fini',
      'Vlog de voyage avec étiquette de lieu et effet confettis',
      'Clip de podcast avec deux intervenants et panneau de notes',
      'Vidéo explicative animant l’indexation des threads CUDA, sous-titres bilingues',
    ],
    sheets: [
      {
        img: 'longform-slices',
        alt: 'Planche d’extraits de cours : bandeaux titres, captures de code recadrées, panneaux de notes et cartons de chapitre',
        caption: 'Extraits de cours : clips verticaux tirés du cours de 72 minutes. Bandeaux titres, recadrages du code qui suivent le texte, panneaux de notes, cartons de chapitre.',
      },
      {
        img: 'talkinghead',
        alt: 'Planche d’un montage face caméra : barre de progression des chapitres, panneaux de notes, mots-clés animés',
        caption: 'Montage face caméra : barre de progression des chapitres, panneaux de notes, mots-clés animés.',
      },
      {
        img: 'explainer-vertical',
        alt: 'Planche d’une vidéo explicative : scènes animées avec sous-titres anglais et chinois',
        caption: 'Vidéo explicative : narration IA, sous-titres anglais et chinois, scènes animées.',
      },
    ],
  },
  deliverables: {
    kicker: 'Chaque lot',
    title: 'Ce que chaque clip contient',
    items: [
      { title: 'Vidéos par plateforme', body: 'YouTube long format 16:9 et Shorts 9:16 ; TikTok, Reels Instagram et Facebook, Snapchat et Pinterest 9:16 ; X, LinkedIn et Reddit au format le plus proche de votre vidéo ; Xiaohongshu 3:4 ; Douyin, WeChat Channels et Kuaishou 9:16 ; Bilibili, Weibo, Zhihu et Dailymotion 16:9. Chaque export est fait séparément au niveau sonore de la plateforme, avec un texte qui respecte ses règles.' },
      { title: 'Sous-titres', body: 'Sous-titres incrustés qui évitent les boutons et la zone de titre de chaque app. Fichiers SRT aussi, si vous les voulez.' },
      { title: 'Couvertures', body: 'Une par clip, dimensionnée et recadrée pour le fil de chaque plateforme.' },
      { title: 'Textes de publication', body: 'Un titre, une description et des hashtags pour chaque clip, dans les limites de chaque plateforme et prêts à être modifiés.' },
      { title: 'Rapport de contrôle', body: 'Le résultat de chaque fichier : ce qui est passé, pourquoi un fichier est rouge, et ce que vous avez changé.' },
      { title: 'Liste de publication', body: 'Un calendrier de publication suggéré et un rappel pour cocher la mention de contenu IA sur chaque plateforme.' },
    ],
  },
  local: {
    kicker: 'En local',
    title: 'Tourne sur votre Mac, avec l’IA de votre choix',
    items: [
      { title: 'Les rushes restent chez vous', body: 'Les fichiers vidéo et audio restent sur votre ordinateur ; la transcription et le rendu s’y font aussi. Vos rushes ne nous parviennent jamais.' },
      { title: 'Votre propre IA', body: 'Utilisez l’abonnement Claude Code ou Codex que vous avez déjà, des clés d’API Anthropic, OpenAI, DeepSeek, Qwen, Kimi et d’autres, ou un modèle local via Ollama. Seuls le texte de la transcription, quelques images clés et les titres partent vers l’IA choisie.' },
      { title: 'Des coûts visibles', body: 'Environ 0,03 $ d’IA par clip dans notre lot de test. Avec un abonnement ou un modèle local, pas de facture d’API en plus.' },
    ],
  },
  create: {
    kicker: 'Créer',
    badge: 'Bientôt',
    title: 'D’une idée à une vidéo IA',
    body: 'Prochaine étape : une page Créer pour générer de la vidéo à partir d’un script ou d’une idée (Kling, Seedance, MiniMax), avec découpage, budget de crédits et sélection des prises, puis un export par plateforme comme pour tout autre lot. Le workflow ai-video du moteur fonctionne déjà.',
  },
  oss: {
    kicker: 'Open source',
    title: 'Entièrement open source, MIT',
    lede: 'L’application, ce site et le moteur de montage sont dans un seul dépôt. Le moteur fonctionne aussi seul comme skill Claude Code, appelé video-studio : décrivez le montage en anglais ou en chinois. Il couvre 12 workflows, dont formats face caméra, extraits de cours, clips de podcast avec visages masqués, vidéos explicatives et vlogs, plus couvertures, sous-titres, volume sonore et export multiplateforme.',
    tested: 'Chaque workflow a été testé sur de vrais rushes. Les problèmes connus sont listés dans VALIDATION.md dans le dépôt.',
    button: 'Voir sur GitHub',
    skillLabel: 'Comme skill Claude Code',
    sourceLabel: 'Lancer l’app Mac depuis les sources',
  },
  faq: {
    kicker: 'FAQ',
    title: 'Questions',
    items: [
      {
        q: 'C’est gratuit ?',
        a: 'Oui. Reelfold est open source sous licence MIT : l’application, le moteur et ce site sont sur GitHub. Vous ne payez que le service d’IA que vous choisissez, ou rien de plus avec un abonnement existant ou un modèle local.',
      },
      {
        q: 'Quelle IA utilise-t-il ?',
        a: 'Celle que vous voulez : votre abonnement Claude Code ou Codex connecté (sans clé d’API), des clés d’API Anthropic, OpenAI, DeepSeek, Qwen, Kimi, GLM, OpenRouter, Gemini et d’autres, ou des modèles locaux via Ollama, LM Studio ou vLLM. Vous pouvez en choisir un différent par tâche.',
      },
      {
        q: 'Où vont mes rushes ?',
        a: 'La vidéo et l’audio restent sur votre ordinateur ; transcription et rendu se font en local. Pour choisir les extraits, écrire les titres et relire les sous-titres, la transcription, quelques captures d’images clés et les titres sont envoyés au service d’IA que vous configurez, selon sa politique de données. La voix IA ou la génération de vidéo IA envoie du texte et des images de référence au fournisseur concerné. Le composant MediaPipe utilisé par le moteur peut envoyer des statistiques d’usage anonymes à Google ; l’application explique comment le désactiver.',
      },
      {
        q: 'Publie-t-il à ma place ?',
        a: 'Non. Reelfold ouvre la page de mise en ligne de chaque plateforme dans un navigateur intégré et remplit la vidéo, la couverture, le titre, la description et les hashtags. C’est vous qui publiez.',
      },
      {
        q: 'Et Windows ?',
        a: 'Mac Apple Silicon uniquement pour l’instant ; Windows viendra plus tard. Le moteur seul (le skill Claude Code) fonctionne sous macOS et Linux.',
      },
      {
        q: 'Dois-je signaler le contenu IA en publiant ?',
        a: 'YouTube, TikTok, Instagram, Facebook, Xiaohongshu, Douyin, WeChat Channels, Bilibili et d’autres ont des règles de mention pour les contenus générés ou modifiés par IA ; suivez les règles en vigueur de chaque plateforme. La liste de publication vous rappelle par défaut de cocher la mention.',
      },
      {
        q: 'Et les autres personnes dans mes vidéos (invités, étudiants) ?',
        a: 'Obtenez d’abord leur accord pour utiliser leur visage et leur voix. Sinon, vous pouvez couvrir les visages avec des autocollants, flouter les noms, modifier la voix des étudiants ou retirer le passage.',
      },
    ],
  },
  footer: {
    feedback: 'Retours · GitHub Discussions',
    privacy: 'Confidentialité',
    terms: 'Conditions',
    note: 'Ce site n’utilise ni cookies, ni scripts de mesure d’audience, ni polices tierces.',
  },
  legal: {
    draft: 'Brouillon, à relire avant publication',
    draftBody: 'Ceci est un premier brouillon qui n’a pas été relu par un juriste. Il doit être vérifié et révisé avant la mise en ligne du site.',
    updated: 'Mis à jour',
    back: 'Retour à l’accueil',
    privacyTitle: 'Politique de confidentialité',
    termsTitle: 'Conditions d’utilisation',
  },
};
