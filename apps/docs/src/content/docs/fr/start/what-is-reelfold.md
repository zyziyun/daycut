---
title: Qu’est-ce que Reelfold
description: Reelfold (千剪) est un outil vidéo libre, gratuit et local qui tire d’un enregistrement tous les montages pour chaque plateforme. Voici comment il fonctionne.
---

Reelfold (千剪) transforme un seul enregistrement en la série de clips que vous publierez cette semaine. Vous décrivez ce que vous voulez avec vos mots et vous déposez vos rushes. Reelfold planifie les clips, les monte sur votre propre Mac, vérifie chaque fichier et ne vous montre que ce qui mérite un coup d’œil. Chaque plateforme reçoit son propre export, sa couverture, son titre, sa légende et ses hashtags.

Il est gratuit, sous licence MIT et open source. Le code se trouve sur [github.com/zyziyun/reelfold](https://github.com/zyziyun/reelfold).

## Deux façons de l’utiliser

Les deux versions font tourner le même moteur : une recette qui marche dans l’une marche aussi dans l’autre.

| | Reelfold pour Mac | Le skill Claude Code |
|---|---|---|
| Ce que c’est | Une app de bureau (`apps/desk`, Electron) | Le moteur sous forme de skill pour [Claude Code](https://claude.com/claude-code) (la racine du dépôt) |
| Comment vous lui parlez | Une zone de demande sur l’Accueil : « On crée quoi aujourd’hui ? » | En langage courant, à Claude, dans votre terminal |
| Idéal pour | Des lots suivis sur un tableau, une grille de relecture, la publication assistée | Travailler dans un dossier, écrire des scripts, des retouches ponctuelles |
| Plateforme | macOS sur Apple Silicon (Windows x64 en préversion) | Partout où tournent Claude Code, Python 3.10+ et ffmpeg |
| Installation | [Installer l’app Mac](/docs/fr/start/install-mac/) | [Installer le skill](/docs/fr/start/install-skill/) |

Côté skill, `SKILL.md` aiguille chaque demande vers un workflow (`workflows/<name>/WORKFLOW.md`) qui s’appuie sur des scripts testés et une bibliothèque Python commune, `vstudio`.

## Le déroulé d’une tâche

1. **Décrire.** Dites ce que vous préparez et ajoutez vos fichiers : un clip face caméra, un cours de 70 minutes, un dossier de rushes de voyage, un script. Par exemple : « Découpe ce cours en 10 clips verticaux pour TikTok et Shorts, moins d’une minute chacun. »
2. **Planifier.** Reelfold analyse les fichiers et propose un plan : quel workflow, combien de clips, quelles plateformes, combien de temps et quel coût éventuel. Vous l’ajustez avec vos mots (« seulement 3 clips », « pas de 9:16 ») avant que quoi que ce soit ne démarre.
3. **Lancer le lot.** Les montages tournent sur votre Mac, plusieurs à la fois. Un clip pilote passe en premier pour que vous validiez le rendu avant que le reste ne soit produit.
4. **Relire.** Chaque fichier passe des contrôles automatiques (mots manquants, images figées, volume sonore, durée). Vous ne voyez que ce qui a été signalé, plus les décisions qui vous reviennent : quelles coupes d’hésitations accepter, quelle ouverture garder, quelle couverture choisir.
5. **Publier.** La publication est assistée. L’app Mac ouvre la page de mise en ligne de chaque plateforme dans son navigateur intégré, puis renseigne le fichier et le texte. C’est vous qui cliquez sur publier. Reelfold ne publie jamais de lui-même.

Pour en savoir plus sur chaque étape : [Projets](/docs/fr/concepts/projects/), [Lots et relecture](/docs/fr/concepts/batch-review/), [Publication](/docs/fr/concepts/publishing/).

## Pour qui

- **Les créateurs qui produisent en série** : vous tournez une fois et publiez toute la semaine, au format, à la durée et au volume sonore attendus par chaque plateforme.
- **Les podcasteurs et intervieweurs** qui veulent tirer de nombreux extraits d’une longue conversation, avec les visages des invités masqués si besoin.
- **Les enseignants et créateurs de formations** qui découpent cours et webinaires en clips verticaux ou en épisodes.
- **Les créateurs face caméra (口播)** qui veulent se débarrasser des blancs, des hésitations et des répétitions, avec sous-titres, panneaux de notes et couverture.
- **Les studios** qui mènent plusieurs lots clients en parallèle, chacun avec son style et son glossaire.

## Ce qui tourne sur votre Mac

La transcription, le découpage, les effets, le rendu et les contrôles qualité tournent tous en local. Côté IA, vous apportez la vôtre : votre Claude Code ou Codex CLI déjà connecté (aucune clé d’API nécessaire), une clé d’API (Anthropic, OpenAI, DeepSeek, Qwen, Kimi, GLM, OpenRouter, Gemini, ElevenLabs) ou un modèle local (Ollama, LM Studio, vLLM, llama.cpp, whisper en local).

Quand un modèle d’IA intervient, il ne reçoit que du texte (transcription, sous-titres et titres), jamais votre vidéo ni votre audio. Lors d’un test interne, un cours de 72 minutes a donné 24 clips pour 4 plateformes (96 fichiers) pour 0,73 $ de coût d’API, soit environ 0,03 $ par clip. Voir [Fournisseurs d’IA](/docs/fr/concepts/ai-providers/) et [Confidentialité](/docs/fr/concepts/privacy/).

## Anciennement video-studio et Daycut

Reelfold est le nouveau nom de ce projet. Le skill et le moteur étaient publiés sous le nom **video-studio**, et l’app de bureau s’appelait **Daycut** (日剪). Certains noms ne changent pas, pour que les installations existantes continuent de fonctionner :

- le skill Claude Code s’appelle toujours `video-studio` et s’installe dans `~/.claude/skills/video-studio`
- le paquet Python s’appelle toujours `vstudio`
- seule l’URL du dépôt a changé : `github.com/zyziyun/reelfold`

## Voir aussi

- [Installer l’app Mac](/docs/fr/start/install-mac/)
- [Installer le skill Claude Code](/docs/fr/start/install-skill/)
- [Votre premier projet](/docs/fr/start/first-project/)
- [Exemples de demandes](/docs/fr/examples/)
