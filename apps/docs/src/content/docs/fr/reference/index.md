---
title: Vue d’ensemble de la référence
description: Ce que couvre chaque page de référence de Reelfold, de la CLI, des options persona et des specs des plateformes aux 13 workflows et aux notes sur le moteur.
---

La section référence est la couche détaillée sous les guides : chaque commande, option, valeur de plateforme et procédure de workflow. Ces pages sont générées à partir des fichiers du [dépôt Reelfold](https://github.com/zyziyun/reelfold) (les profils et catalogues du moteur, les procédures `WORKFLOW.md` et les notes de `references/`) : elles correspondent donc au code. Elles sont rédigées en anglais.

Si vous débutez, commencez par les [guides](/docs/fr/guides/talking-head/) et les [exemples de demandes](/docs/fr/examples/) ; revenez ici quand il vous faut la valeur ou l’option exacte.

## Référence principale

| Page | Contenu |
|---|---|
| [CLI](/docs/fr/reference/cli/) | Les commandes du moteur (`python -m vstudio.*`) : intake, project, batch, cleanup, export, reframe, platform, effects, llm, retouch |
| [Options de persona.yaml](/docs/fr/reference/persona/) | Toutes les options de `persona.local.yaml` : vitesses, volume sonore, couleurs de marque et thème, réglages par plateforme, hashtags, règles de ton, corrections de termes, polices, routage de l’IA |
| [Specs des plateformes](/docs/fr/reference/platforms/) | Le profil de chaque plateforme : format, tailles de couverture, durée, limites de titre, volume sonore |
| [Effets et thèmes](/docs/fr/reference/effects/) | Le catalogue d’effets, les moteurs de rendu de chaque effet et les thèmes graphiques |
| [Règles de sous-titrage](/docs/fr/reference/captions/) | Les règles pour les sous-titres, les cartons et les textes de publication : noms, longueur de ligne, mise en valeur, contraste |
| [Messages et codes d’erreur](/docs/fr/reference/messages/) | Chaque code de message du moteur, avec son texte et l’endroit où il apparaît |

## Workflows

Chaque workflow est à la fois une procédure que suit le skill et une recette qu’exécute l’app Mac.

| Workflow | Transforme… en… |
|---|---|
| [talkinghead](/docs/fr/reference/workflows/talkinghead/) | Un enregistrement face caméra en short serré et sous-titré : nettoyage, vitesse, accroches, panneaux de notes, retouche, couverture, texte de publication |
| [promo-recut](/docs/fr/reference/workflows/promo-recut/) | Un face caméra accompagné de captures, de liens ou d’une autre vidéo en promo haut de gamme, avec écran partagé et cartes mises en valeur |
| [longform-to-short](/docs/fr/reference/workflows/longform-to-short/) | Un cours, un webinaire ou un live en vidéo de formation montée et/ou en épisodes courts ou extraits verticaux |
| [call-clips](/docs/fr/reference/workflows/call-clips/) | Des appels, interviews et podcasts en extraits, avec masquage des visages et floutage des noms affichés |
| [photo-story](/docs/fr/reference/workflows/photo-story/) | Des photos et un texte de narration (ou seulement de la musique) en récit riche en effets |
| [vlog](/docs/fr/reference/workflows/vlog/) | Des plans d’illustration en vlog posé et étalonné, ou rapide et calé sur le tempo |
| [explainer](/docs/fr/reference/workflows/explainer/) | Un sujet en vidéo explicative animée façon 3Blue1Brown, avec narration IA et sous-titres bilingues |
| [polish](/docs/fr/reference/workflows/polish/) | N’importe quel montage exporté, prêt à publier : image de couverture, volume sonore, vitesse, nettoyage optionnel |
| [ai-video](/docs/fr/reference/workflows/ai-video/) | Un script ou une idée en vidéo générée par IA (Kling, Seedance, MiniMax), dans un budget de crédits |
| [cover](/docs/fr/reference/workflows/cover/) | Des couvertures et miniatures aux dimensions de chaque plateforme |
| [slides](/docs/fr/reference/workflows/slides/) | Des diapositives carrées ou plein cadre pour les vidéos verticales |
| [preproduction](/docs/fr/reference/workflows/preproduction/) | Écriture de scripts, vérification des scripts par plateforme et exercices de prononciation |
| [batch](/docs/fr/reference/workflows/batch/) | De nombreux shorts à la fois : plan, pilote, exécution en parallèle, contrôles automatiques, relecture, kits de publication |

## Notes sur le moteur

Des notes approfondies sur le fonctionnement du moteur commun. Utiles quand vous scriptez le moteur, déboguez un résultat ou contribuez au projet.

| Page | Sujet |
|---|---|
| [Intake](/docs/fr/reference/engine/intake/) | Comment une demande en langage courant et une pile de fichiers deviennent un plan |
| [Projets](/docs/fr/reference/engine/projects/) | Recettes, éléments, points de contrôle, boîte de réception, séries et calendrier de publication |
| [Lots](/docs/fr/reference/engine/batch/) | Spécifications de lot, listes de tâches, ordonnanceur, contrôles qualité, relecture et kits |
| [Nettoyage de la parole](/docs/fr/reference/engine/cleanup/) | Blancs, hésitations, répétitions et reprises : détection, réponse à la relecture, vérification |
| [Retouches de clips](/docs/fr/reference/engine/output-edit/) | Retouches des clips terminés : opérations, retouches par IA, annulation et retour en arrière sélectif |
| [Fournisseurs d’IA](/docs/fr/reference/engine/providers/) | Router chaque tâche d’IA vers une API, un modèle local ou votre compte Claude Code / Codex |
| [Publication](/docs/fr/reference/engine/publishing/) | Comment une publication arrive sur chaque plateforme, et pourquoi rien n’est publié automatiquement |
| [Règles de style](/docs/fr/reference/engine/style-rules/) | Les thèmes graphiques derrière les bandeaux titre, sous-titres, notes et cartons |
| [Checklist esthétique](/docs/fr/reference/engine/aesthetics/) | Les vérifications à faire sur tout montage avant livraison |
| [Son](/docs/fr/reference/engine/sound/) | Tempo, placement des effets sonores et niveaux |
| [Retouche](/docs/fr/reference/engine/retouch/) | Lissage de la peau, maquillage et remodelage, pour les couvertures et la vidéo |
| [Procédure short vidéo](/docs/fr/reference/engine/sop-short-video/) | Un short face caméra, du sujet à la publication, de bout en bout |
| [Ajouter des effets](/docs/fr/reference/engine/adding-effects/) | Ajouter un effet au catalogue et le porter d’un moteur de rendu à l’autre |
| [Validation](/docs/fr/reference/engine/validation/) | Ce qui a été testé sur de vrais rushes, et les limites connues |

## Voir aussi

- [Qu’est-ce que Reelfold](/docs/fr/start/what-is-reelfold/)
- [Exemples de demandes](/docs/fr/examples/)
- [Contribuer](/docs/fr/contributing/)
