<p align="center">
  <a href="README.md">English</a> · <a href="README.zh-CN.md">简体中文</a> · <b>Français</b> · <a href="README.es.md">Español</a>
</p>

<p align="center">
  <picture>
    <source media="(prefers-color-scheme: dark)" srcset="docs/brand/wordmark-on-dark.svg">
    <img alt="Reelfold" src="docs/brand/wordmark-on-light.svg" width="340">
  </picture>
</p>

<p align="center"><b>Un enregistrement, chaque montage, pour chaque plateforme.</b><br>
Un outil vidéo gratuit et open source pour celles et ceux qui montent en série.</p>

<p align="center">
  <a href="https://reelfold.com/docs/fr/">Documentation</a> ·
  <a href="https://github.com/zyziyun/reelfold/releases/latest">Télécharger pour macOS</a> ·
  <a href="https://reelfold.com/fr/">reelfold.com</a> ·
  <a href="LICENSE">MIT</a>
</p>

- **Décrivez, déposez les rushes.** Dites ce que vous voulez avec vos mots ; Reelfold choisit les extraits et les monte
  en parallèle sur votre propre Mac.
- **Ne relisez que les exceptions.** Chaque fichier est vérifié automatiquement ; vous ne regardez que ce qui est signalé.
- **Chaque plateforme dans son format.** 20 plateformes, chacune avec sa taille, ses sous-titres, son volume sonore, sa
  couverture et son texte. La publication est assistée : Reelfold remplit la page de mise en ligne, vous cliquez sur publier.

![Face caméra · extraits de cours · récit photo · vlog rythmé · podcast masqué · vidéo explicative](docs/demos/strip.jpg)

## Installation

**Application Mac** (Apple Silicon, gratuite). À télécharger depuis
[Releases](https://github.com/zyziyun/reelfold/releases/latest) dès la première version (bientôt) ; en attendant,
[compilez depuis les sources](https://reelfold.com/docs/fr/start/install-mac/).

**Skill Claude Code** (le même moteur, toujours nommé `video-studio`) :

```bash
git clone https://github.com/zyziyun/reelfold ~/.claude/skills/video-studio
~/.claude/skills/video-studio/install.sh
cp ~/.claude/skills/video-studio/persona.example.yaml ~/.claude/skills/video-studio/persona.local.yaml
```

L'IA tourne avec ce que vous avez déjà : votre connexion Claude Code ou Codex, votre propre clé d'API, ou un modèle local.

**Documentation → [reelfold.com/docs/fr](https://reelfold.com/docs/fr/)**

## Dites-le comme ça

| Vous voulez | Dites par exemple |
|---|---|
| Un face caméra bien serré | « Retire les pauses, les tics de langage et les répétitions, accélère à 1,1×, ajoute des sous-titres et une barre de progression, exporte pour TikTok et Shorts » |
| Un cours en extraits verticaux | « Découpe ce cours de 70 minutes en 3 épisodes verticaux, une idée par épisode, zoome sur le code, avec couvertures et textes de publication » |
| Un extrait de podcast | « Trouve la meilleure minute de ce podcast Zoom, masque le visage et le nom de l'invité, en vertical » |
| Un vlog de voyage rythmé | « Fais un vlog rapide, calé sur le rythme, avec ces photos et vidéos de Disneyland : jours, lieux, effets sonores, 9:16 » |
| Une vidéo, plusieurs plateformes | « Exporte-la pour Instagram Reels, TikTok et YouTube Shorts, chacune avec ses zones de sécurité et son volume » |

Plus d'exemples : [exemples de demandes](https://reelfold.com/docs/fr/examples/).

## En savoir plus

[Premiers pas](https://reelfold.com/docs/fr/start/what-is-reelfold/) ·
[Guides](https://reelfold.com/docs/fr/guides/talking-head/) ·
[Concepts](https://reelfold.com/docs/fr/concepts/projects/) ·
[Référence](https://reelfold.com/docs/fr/reference/) ·
[Dépannage](https://reelfold.com/docs/fr/help/troubleshooting/) ·
[Contribuer](https://reelfold.com/docs/fr/contributing/)

## Licence

MIT, y compris l'application (`apps/desk`), le site (`apps/site`) et la documentation (`apps/docs`). Les polices et les
modèles sont téléchargés à l'installation sous leurs propres licences (SIL OFL 1.1, Apache-2.0). Les workflows
HTML-vers-vidéo reposent sur [HyperFrames](https://hyperframes.heygen.com).

Anciennement **video-studio** (le skill et le moteur) et **Daycut** (l'application). Les installations existantes dans
`~/.claude/skills/video-studio` continuent de fonctionner ; pointez-les vers la nouvelle adresse avec
`git -C ~/.claude/skills/video-studio remote set-url origin https://github.com/zyziyun/reelfold`.
