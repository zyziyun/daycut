<p align="center">
  <a href="README.md">English</a> · <a href="README.zh-CN.md">简体中文</a> · <a href="README.fr.md">Français</a>
</p>

<p align="center">
  <picture>
    <source media="(prefers-color-scheme: dark)" srcset="docs/brand/wordmark-on-dark.svg">
    <img alt="Reelfold" src="docs/brand/wordmark-on-light.svg" width="360">
  </picture>
</p>

<p align="center"><b>Décrivez. Déposez les rushes. Chaque montage, pour chaque plateforme.</b><br>
Un enregistrement, déplié sur toutes les plateformes.</p>

<p align="center">
  <a href="https://reelfold.com/fr/">reelfold.com</a> ·
  <a href="https://github.com/zyziyun/reelfold/releases/latest">Télécharger pour macOS</a> ·
  <a href="https://github.com/zyziyun/reelfold">Star sur GitHub</a> ·
  <a href="#installation">Installer le skill Claude Code</a> ·
  <a href="LICENSE">MIT</a>
</p>

<p align="center"><sub>Gratuit et open source (MIT). La première version macOS arrive bientôt ; en attendant, compilez depuis les sources (voir <a href="#installation">Installation</a>).</sub></p>

**Reelfold** (千剪 en chinois) est un orchestrateur vidéo gratuit, open source et local, pour celles et ceux qui montent en
série. Dites ce que vous voulez avec vos mots et déposez un enregistrement : Reelfold choisit les extraits, lance les
montages en parallèle sur votre propre ordinateur, vérifie chaque fichier automatiquement et ne vous montre que les
exceptions. Chaque plateforme reçoit son export, sa couverture, son titre, sa description et ses hashtags. La
publication est assistée : Reelfold remplit la page de mise en ligne de la plateforme, et c'est vous qui cliquez sur
publier. Il ne publie jamais tout seul.

Deux façons de l'utiliser, sur le même moteur :

- **Reelfold pour Mac** (`apps/desk`) : l'application. Lots sur un tableau, grille de relecture, coupes par la
  transcription, publication assistée. Gratuit, MIT, Apple Silicon pour l'instant ; Windows plus tard.
- **Le skill `video-studio` pour Claude Code** (racine du dépôt) : le moteur sous forme de skill. Parlez à Claude
  (« retire les pauses et accélère à 1,3× », « découpe ce cours de 70 minutes en 3 épisodes verticaux ») ; le skill
  indique à Claude quel workflow lancer et lui fournit des scripts testés et une bibliothèque partagée.

![Face caméra · extraits de cours · récit photo · vlog rythmé · podcast masqué · vidéo explicative](docs/demos/strip.jpg)
<sub>Images de six montages réalisés de bout en bout avec le moteur ; planches ci-dessous.</sub>

## Usages

| Pour qui | Ce que fait Reelfold |
|---|---|
| **Créateurs en série** | Enregistrez une fois, publiez toute la semaine : une session devient une série de clips, chacun au format, à la durée et au volume sonore attendus par chaque plateforme (`batch`). |
| **Interviews et podcasts** | De nombreux clips tirés d'une longue conversation, avec sous-titres, cadrage sur l'intervenant, visages des invités masqués et noms floutés, exportés par plateforme (`call-clips`, `batch` `podcast-clips`). |
| **Studios et lots clients** | Les lots de plusieurs clients en parallèle, le style et le glossaire de chaque client conservés, un rapport de contrôle pour chaque lot (`batch`, projets). |
| **Face caméra** | Pauses, tics de langage et répétitions retirés ; sous-titres, mots-clés animés, panneaux de notes, barre de progression, couverture et texte de publication (`talkinghead`). |
| **Découpage de cours** | Cours et webinaires longs → extraits verticaux ou épisodes, avec bandeaux titres, recadrages lisibles du code et cartons de chapitre ; la voix des étudiants peut être modifiée (`longform-to-short`). |
| **Vidéo IA** | Vidéos explicatives façon 3Blue1Brown avec narration IA et sous-titres bilingues, ou séries générées par IA (Kling, Seedance, MiniMax) avec un budget de crédits (`explainer`, `ai-video`). |

Local et économe : la transcription et le rendu tournent sur votre machine ; seuls le texte de la transcription,
quelques images clés et les titres partent vers le fournisseur d'IA de votre choix (ou aucun, avec un modèle local ou
votre propre CLI Claude Code / Codex connectée). Dans notre lot de test interne (un cours de 72 minutes → 24 clips ×
4 plateformes = 96 fichiers), le coût d'API IA a été de 0,73 $, soit environ 0,03 $ par clip.

## Installation

**Application (macOS, Apple Silicon).** Gratuite, MIT. Téléchargez-la sur [GitHub Releases](https://github.com/zyziyun/reelfold/releases/latest) dès la
première version (bientôt). L'IA passe par votre abonnement Claude Code ou Codex, vos clés d'API ou un modèle local.

En attendant, compilez-la depuis les sources (macOS, Apple Silicon ; Node 22+, Python 3.10+, `ffmpeg`) :

```bash
git clone https://github.com/zyziyun/reelfold && cd reelfold
./install.sh && npm install
npm run desk
```

**Skill Claude Code.** Le skill s'appelle toujours `video-studio` et se trouve dans `~/.claude/skills/video-studio` :

```bash
git clone https://github.com/zyziyun/reelfold ~/.claude/skills/video-studio
~/.claude/skills/video-studio/install.sh
cp ~/.claude/skills/video-studio/persona.example.yaml ~/.claude/skills/video-studio/persona.local.yaml
```

Déjà cloné depuis l'ancien dépôt ? Pointez-le vers le nouveau :
`git -C ~/.claude/skills/video-studio remote set-url origin https://github.com/zyziyun/reelfold`.

Prérequis : Python 3.10+, `ffmpeg`. Optionnel : Node 18+ avec `npx hyperframes` (explainer, promo-recut), Chrome ou
Playwright (couvertures et diapositives HTML), une `OPENAI_API_KEY` (narration IA). La transcription utilise
`mlx-whisper` sur Apple Silicon et `faster-whisper` ailleurs. Modèles Whisper, fournisseurs d'IA, caches et encodeur
H.264 : voir [Engine setup](README.md#engine-setup-skill) dans le README anglais et
[references/PROVIDERS.md](references/PROVIDERS.md).

## Workflows du moteur

| Workflow | Transforme… en… |
|---|---|
| `talkinghead` | enregistrements face caméra → format court resserré : pauses / tics / répétitions retirés, vitesse, sous-titres, zooms, mots animés, panneaux de notes, barre de progression, accroches, B-roll, retouche, couverture, texte de publication |
| `promo-recut` | face caméra + captures / liens / autre vidéo → promo soignée : écran partagé, cartes 3D surlignées, arrêt sur image agrandi, extraits insérés |
| `longform-to-short` | cours, webinaires, lives, partages d'écran → vidéo de cours et / ou N épisodes courts, extraits verticaux (3:4 / 9:16), zooms sur le code, couvertures |
| `call-clips` | Zoom / Meet / Teams / interviews → clips verticaux, en trio ou en paysage, visages masqués (autocollants) et noms floutés |
| `photo-story` | photos + texte de narration → récit riche en effets ; mode musique seule calé sur les mesures ; narration TTS ou votre voix clonée |
| `vlog` | B-roll (drone, voyage, téléphone) → `calm` (étalonnage, vitesse, fondus, musique) ou `fun` (cut sur le rythme, rampes de vitesse, textes animés, effets sonores) |
| `explainer` | un sujet → vidéo explicative animée façon 3Blue1Brown, narration IA et sous-titres bilingues, 16:9 ou vertical |
| `polish` | un montage exporté → nettoyage optionnel, couverture en première image, volume sonore, accélération, une ou plusieurs plateformes |
| `ai-video` | un script ou une idée → vidéo générée par IA : bible des personnages, prompts, plan de crédits, sélection des prises, assemblage, paquets de publication |
| `batch` | des dizaines à des centaines de clips : pilote, exécutions parallèles reprenables, contrôles qualité, page de relecture des seules exceptions, paquets de publication |
| `cover`, `slides`, `preproduction` | couvertures par plateforme, diapositives, écriture de script et exercices de prononciation |

Détails techniques, exemples de demandes, profils de plateformes, `persona.local.yaml` et structure du dépôt : voir le
[README anglais](README.md). Tests sur de vrais rushes et limites connues :
[references/VALIDATION.md](references/VALIDATION.md).

## Résultats

| | |
|---|---|
| **Face caméra** (`talkinghead`) ![](docs/demos/talkinghead.jpg) | **Extraits de cours** (`longform-to-short`) ![](docs/demos/longform-slices.jpg) |
| **Récit photo** (`photo-story`) ![](docs/demos/photo-story.jpg) | **Vlog de voyage rythmé** (`vlog` fun) ![](docs/demos/fun-vlog.jpg) |
| **Podcast + visages masqués** (`call-clips`) ![](docs/demos/call-clips.jpg) | **Vidéo explicative** (`explainer` vertical) ![](docs/demos/explainer-vertical.jpg) |

## Anciennement video-studio / Daycut

Reelfold est le nouveau nom de ce projet. Le skill et le moteur open source étaient publiés sous le nom
**video-studio**, et l'application s'appelait **Daycut** (日剪 / 日更剪). Le skill Claude Code garde le nom
`video-studio`, le paquet Python reste `vstudio`, et les installations existantes dans `~/.claude/skills/video-studio`
continuent de fonctionner ; seule l'adresse du dépôt passe à `github.com/zyziyun/reelfold`.

## Licence

Code sous licence MIT (voir `LICENSE`), y compris `apps/desk` et `apps/site`. Les polices et modèles sont téléchargés à
l'installation depuis leurs projets d'origine, sous leurs propres licences (SIL OFL 1.1 ; Apache-2.0), et ne sont pas
redistribués ici. Le moteur de détourage RVM optionnel de `workflows/cover` est sous GPL-3.0 et n'est récupéré que si
vous le choisissez. Les workflows HTML vers vidéo s'appuient sur [HyperFrames](https://hyperframes.heygen.com).
