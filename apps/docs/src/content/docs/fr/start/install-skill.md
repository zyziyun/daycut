---
title: Installer le skill Claude Code
description: Installez le skill video-studio pour Claude Code en trois commandes, voyez ce que télécharge install.sh, utilisez Whisper hors ligne, mettez à jour et vérifiez.
---

Le skill Claude Code, c’est le moteur de Reelfold empaqueté pour [Claude Code](https://claude.com/claude-code). Une fois installé, vous parlez de vos rushes à Claude (« coupe les blancs et accélère à 1,1× ») et le skill indique à Claude quel workflow lancer, avec des scripts testés et une bibliothèque commune derrière. Le skill s’appelle toujours `video-studio`.

## Configuration requise

**Indispensable**

- Claude Code
- Python 3.10+
- `ffmpeg` (`brew install ffmpeg` ou `apt install ffmpeg`)

**Facultatif, selon le workflow**

| Vous voulez | À installer |
|---|---|
| Des vidéos explicatives et des remontages promo (HyperFrames) | Node 18+ avec `npx hyperframes` |
| Des couvertures et diapositives en HTML | Chrome / Chromium, ou Playwright |
| Une narration par IA (OpenAI TTS) | `OPENAI_API_KEY` |
| Le catalogue musical | La CLI HeyGen |
| Une meilleure détection du tempo | `librosa` |
| Les photos HEIC | `pillow-heif` (sur macOS, `sips` prend le relais) |
| Votre propre voix clonée | `mlx-audio` et un modèle Qwen3-TTS |

## Installation

Lancez ces trois lignes :

```bash
git clone https://github.com/zyziyun/reelfold ~/.claude/skills/video-studio
~/.claude/skills/video-studio/install.sh
cp ~/.claude/skills/video-studio/persona.example.yaml ~/.claude/skills/video-studio/persona.local.yaml
```

1. Le clone place le skill là où Claude Code va chercher ses skills.
2. `install.sh` installe les dépendances Python et télécharge les polices et les modèles (voir plus bas). Vous pouvez le relancer sans risque : les fichiers déjà présents sont ignorés.
3. `persona.local.yaml` contient vos préférences : vitesses par défaut, volume sonore, couleurs de marque, règles de titres, hashtags, corrections de termes, polices et l’IA chargée de chaque tâche. Il est ignoré par git, vos réglages ne finissent donc jamais dans le dépôt. Toutes les options : [options de persona.yaml](/docs/fr/reference/persona/).

Ouvrez ensuite une nouvelle session Claude Code pour qu’elle prenne en compte le skill.

## Ce que télécharge install.sh

Tout atterrit dans un seul dossier de cache, `~/.cache/video-studio` (définissez `VSTUDIO_CACHE` pour le déplacer) :

| Quoi | Où | Licence |
|---|---|---|
| Noto Sans SC, Noto Serif SC, STIX Two Text, JetBrains Mono | `fonts/` | SIL OFL 1.1 |
| MediaPipe face landmarker, selfie segmenter, selfie multiclass segmenter (utilisés pour la retouche) | `models/` | Apache-2.0 |
| Les paquets Python de `requirements.txt`, plus `mlx-whisper` sur Apple Silicon ou `faster-whisper` ailleurs | votre environnement Python | diverses |

À la fin, le script vous avertit si `ffmpeg` ou `npx` manque. Définissez `SKIP_PIP=1` pour sauter les paquets Python et ne récupérer que les polices et les modèles.

Ce même cache conserve aussi les transcriptions, les prises TTS et d’autres résultats réutilisables. L’app Mac utilise ce dossier elle aussi : rien n’est téléchargé deux fois.

## Modèles Whisper et usage hors ligne

La première transcription télécharge un modèle Whisper dans le cache Hugging Face (`~/.cache/huggingface/hub`, ou `$HF_HOME/hub`) :

- `mlx-community/whisper-large-v3-turbo` pour mlx-whisper (Apple Silicon)
- `large-v3-turbo` (`Systran/faster-whisper-large-v3-turbo`) pour faster-whisper

Pour utiliser un modèle que vous avez déjà, ou pour travailler sur une machine hors ligne, indiquez-le au moteur :

```bash
export VSTUDIO_WHISPER_MLX=/path/to/whisper-large-v3-turbo-mlx    # MLX folder (config.json + weights) or an HF repo id
export VSTUDIO_WHISPER_FW=/path/to/faster-whisper-large-v3-turbo  # CTranslate2 folder, or a size name such as small
export HF_HUB_OFFLINE=1                                           # never touch the network
```

Le moteur de transcription est choisi automatiquement : mlx-whisper, sinon faster-whisper, sinon OpenAI `whisper-1` si `OPENAI_API_KEY` est défini.

## Choisir votre IA

Chaque étape d’IA (planification des segments, relecture des sous-titres, glossaire, texte de publication) peut tourner sur votre Claude Code ou Codex CLI déjà connecté, sans clé d’API, sur une clé d’API ou sur un modèle local. Réglez-le dans `persona.local.yaml` :

```yaml
llm:
  default: {provider: claude-code}
```

Routage par tâche, solutions de repli et coûts : [Fournisseurs d’IA](/docs/fr/concepts/ai-providers/).

## Vérifier l’installation

Affichez les fournisseurs d’IA, les moteurs de transcription et de TTS disponibles sur cette machine (rien n’est envoyé) :

```bash
cd ~/.claude/skills/video-studio/lib && python3 -m vstudio.llm providers
```

Vous pouvez aussi lancer la suite de tests sur des médias synthétiques (nécessite `pytest` ; aucun accès réseau) :

```bash
cd ~/.claude/skills/video-studio && python3 -m pytest tests -q
```

## Migrer depuis l’ancienne URL du dépôt

Si vous avez cloné le skill à l’époque où il s’appelait video-studio, faites-le pointer vers le nouveau dépôt. Le nom du dossier, le nom du skill et le paquet `vstudio` ne changent pas :

```bash
git -C ~/.claude/skills/video-studio remote set-url origin https://github.com/zyziyun/reelfold
```

Les anciennes versions écrivaient une partie du cache dans `~/.cache/vstudio`. Ce dossier est encore lu mais plus alimenté ; supprimez-le quand vous n’en avez plus besoin.

## Mettre à jour

```bash
git -C ~/.claude/skills/video-studio pull
~/.claude/skills/video-studio/install.sh
```

Relancer `install.sh` récupère les nouvelles dépendances Python ainsi que les nouvelles polices ou les nouveaux modèles. Votre `persona.local.yaml` n’est pas modifié.

## Voir aussi

- [Votre premier projet](/docs/fr/start/first-project/)
- [Exemples de demandes](/docs/fr/examples/)
- [Référence de la CLI](/docs/fr/reference/cli/)
- [Installer l’app Mac](/docs/fr/start/install-mac/)
