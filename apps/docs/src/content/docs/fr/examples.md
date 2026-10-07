---
title: Exemples de demandes
description: Des demandes qui marchent bien dans Reelfold, classées par usage, de la coupe des blancs d’un face caméra au découpage d’un cours, aux lots et aux retouches.
---

Vous parlez à Reelfold comme vous briefez un monteur. Ces demandes fonctionnent dans la zone de demande de l’app Mac comme avec le skill Claude Code, et vous pouvez les écrire en français. Désignez vos fichiers (déposez-les dans l’app, ou nommez-les à Claude) et adaptez les détails.

## Bien formuler une demande

Une bonne demande précise trois choses :

1. **La matière** : « ce clip face caméra », « ce cours de 70 minutes », « ces plans de drone et ces photos ».
2. **Le résultat attendu** : combien de clips, quelle durée, ce qu’ils contiennent (sous-titres, panneaux de notes, couverture, texte de publication).
3. **La plateforme** : TikTok, YouTube Shorts, Instagram Reels, Xiaohongshu, Douyin, etc. La plateforme fixe le format, les zones de sécurité, le volume sonore et les limites de texte : vous avez rarement besoin d’indiquer des dimensions.

Tout ce que vous ne précisez pas vient de vos réglages par défaut (votre persona) ou de la matière elle-même. Quand un choix ne peut pas être deviné et changerait le résultat, par exemple quel visage masquer ou narration contre musique, le planificateur vous pose la question avant de démarrer.

## Face caméra

<div class="rf-prompts">

| Vous voulez | Dites par exemple | Workflow |
|---|---|---|
| Un short serré | « Resserre ce clip face caméra : coupe les blancs, les hésitations et les répétitions, accélère à 1,1×, ajoute des sous-titres, des panneaux de notes et une barre de progression, export pour TikTok » | [talkinghead](/docs/fr/reference/workflows/talkinghead/) |
| Une accroche d’ouverture | « Ouvre avec trois phrases fortes tirées du clip, fais ressortir les mots-clés à l’écran, et prépare une version TikTok et une version Shorts » | [talkinghead](/docs/fr/reference/workflows/talkinghead/) |
| Un style plus nerveux | « Passe en style coupes rapides : zooms punch-in, mots qui surgissent, tampons et effets sonores » | [talkinghead](/docs/fr/reference/workflows/talkinghead/) |
| Une retouche | « Lisse ma peau et ajoute un maquillage léger et naturel ; affine un peu le visage sur la couverture » | [talkinghead](/docs/fr/reference/workflows/talkinghead/), [cover](/docs/fr/reference/workflows/cover/) |
| Des plans de coupe | « Quand je parle du tableau de bord, montre cet enregistrement d’écran sans couper le son » | [talkinghead](/docs/fr/reference/workflows/talkinghead/) |

</div>

## Nettoyage de la parole uniquement

<div class="rf-prompts">

| Vous voulez | Dites par exemple | Workflow |
|---|---|---|
| Une parole propre, rien d’autre | « Coupe les blancs, les euh et les répétitions de cet enregistrement, et liste ce dont tu n’es pas sûr pour que je confirme » | [cleanup](/docs/fr/reference/engine/cleanup/) |
| Nettoyer un montage exporté | « J’ai exporté ça depuis CapCut. Enlève les temps morts et les hésitations, corrige la première image noire et règle le volume sonore » | [polish](/docs/fr/reference/workflows/polish/) |
| Un passage en douceur | « Nettoyage léger seulement : raccourcis les longs blancs mais garde mes respirations et le rythme naturel » | [cleanup](/docs/fr/reference/engine/cleanup/) |

</div>

## Enregistrements longs, formations et appels

<div class="rf-prompts">

| Vous voulez | Dites par exemple | Workflow |
|---|---|---|
| Des épisodes tirés d’un cours | « Découpe ce cours de 70 minutes en 3 shorts verticaux, une idée chacun, zoom sur le code, avec couvertures et textes de publication » | [longform-to-short](/docs/fr/reference/workflows/longform-to-short/) |
| Des extraits verticaux d’un webinaire | « Découpe ce webinaire en 10 clips verticaux de moins d’une minute pour TikTok et Shorts, bandeau titre en haut, recadrage lisible de l’écran » | [longform-to-short](/docs/fr/reference/workflows/longform-to-short/) |
| Une vidéo de formation propre | « Transforme cet enregistrement d’écran en vidéo de formation : masque la barre du navigateur, ajoute des chapitres et des sous-titres, modifie la voix des élèves » | [longform-to-short](/docs/fr/reference/workflows/longform-to-short/) |
| Un extrait de podcast ou d’appel | « Trouve la minute la plus intéressante de ce podcast enregistré sur Zoom, masque le visage de l’invité, floute les noms affichés, en vertical » | [call-clips](/docs/fr/reference/workflows/call-clips/) |
| Un extrait d’un montage fini | « Sors le passage sur les projets perso, vers la fin de cette vidéo, et fais-en un short à part » | [talkinghead](/docs/fr/reference/workflows/talkinghead/) |

</div>

## Promo, récits et vlogs

<div class="rf-prompts">

| Vous voulez | Dites par exemple | Workflow |
|---|---|---|
| Une promo haut de gamme | « Écran partagé, moi à gauche et les captures à droite en cartes 3D avec surlignage ; arrêt sur image de 2 secondes sur le prompt, agrandi ; puis un best-of à 1,1× » | [promo-recut](/docs/fr/reference/workflows/promo-recut/) |
| Un récit photo | « Fais un récit façon film d’auteur avec ces photos d’exposition : musique seule, trois chapitres, révélations avant/après, une loupe et un grain argentique » | [photo-story](/docs/fr/reference/workflows/photo-story/) |
| Un récit narré | « Transforme ces photos de voyage et ce texte en récit narré avec ma propre voix, en 9:16 » | [photo-story](/docs/fr/reference/workflows/photo-story/) |
| Un vlog rythmé | « Monte un vlog rapide, calé sur le tempo, avec ces clips et photos de Disneyland : étiquettes JOUR, épingles de lieu, effets sonores, textes qui surgissent, en 9:16 » | [vlog](/docs/fr/reference/workflows/vlog/) (rythmé) |
| Un vlog posé | « Fais un vlog posé avec ces plans de drone : étalonnage, ralentis, musique douce » | [vlog](/docs/fr/reference/workflows/vlog/) (posé) |

</div>

## Vidéos explicatives et vidéo IA

<div class="rf-prompts">

| Vous voulez | Dites par exemple | Workflow |
|---|---|---|
| Une vidéo explicative | « Fais une vidéo explicative façon 3Blue1Brown sur le fonctionnement de CUDA sur un GPU, en short vertical, sous-titres bilingues » | [explainer](/docs/fr/reference/workflows/explainer/) |
| Des vidéos tirées d’un document | « Fais cinq courtes vidéos explicatives à partir des sections de ce PDF » | [explainer](/docs/fr/reference/workflows/explainer/) |
| Un épisode généré par IA | « Fais l’épisode 3 de ma mini-série IA à partir de ce script avec Kling, garde les mêmes personnages, budget de 200 crédits » | [ai-video](/docs/fr/reference/workflows/ai-video/) |

</div>

## Couvertures, habillage et plateformes

<div class="rf-prompts">

| Vous voulez | Dites par exemple | Workflow |
|---|---|---|
| Un kit de publication | « Fais une couverture, un titre, une description et des hashtags pour cette vidéo, pour YouTube et Instagram » | [cover](/docs/fr/reference/workflows/cover/), [polish](/docs/fr/reference/workflows/polish/) |
| Juste une miniature | « Fais une miniature YouTube à partir de ce clip, avec un grand titre sur deux lignes » | [cover](/docs/fr/reference/workflows/cover/) |
| Plusieurs plateformes | « Exporte cette vidéo pour Instagram Reels, TikTok et YouTube Shorts, chacune avec sa zone de sécurité et son volume sonore » | [export](/docs/fr/reference/cli/#vstudioexport) |
| D’abord un script | « Écris un script de 90 secondes sur ce sujet pour Shorts, puis donne-moi un exercice de prononciation pour les mots difficiles » | [preproduction](/docs/fr/reference/workflows/preproduction/) |

</div>

## Lots et planification

<div class="rf-prompts">

| Vous voulez | Dites par exemple | Workflow |
|---|---|---|
| Un lot complet | « Transforme ce dossier de 30 clips face caméra en shorts nettoyés pour TikTok et Shorts, et montre-moi seulement ceux qui échouent à un contrôle » | [batch](/docs/fr/reference/workflows/batch/) |
| Une semaine à partir d’un enregistrement | « Découpe ce live en 14 clips de moins de 60 secondes et prépare-les pour TikTok et Instagram Reels » | [batch](/docs/fr/reference/workflows/batch/) |
| Un planning de publication | « Programme ces clips à raison de deux par jour à partir de lundi, à 12 h et à 19 h » | [batch](/docs/fr/reference/workflows/batch/) |

</div>

Rien n’est publié à votre place. Un planning vous donne un calendrier de publication et des fichiers prêts à poster ; au moment de publier, l’app Mac remplit la page de mise en ligne et c’est vous qui cliquez sur publier. Voir [Planification et publication](/docs/fr/guides/scheduling-publishing/).

## Retouches sur un clip terminé

Chaque clip terminé peut être retouché avec vos mots. Dans l’app Mac, vous pouvez d’abord sélectionner un passage sur la timeline ou un sous-titre : « ça » désigne alors votre sélection.

<div class="rf-prompts">

| Vous voulez | Dites par exemple | Workflow |
|---|---|---|
| Couper le début et accélérer | « Coupe les deux premières secondes et accélère l’ensemble à 1,2× » | [output edit](/docs/fr/reference/engine/output-edit/) |
| Supprimer un passage | « Coupe ce passage » (avec un passage sélectionné) | [output edit](/docs/fr/reference/engine/output-edit/) |
| Sous-titres | « Agrandis les sous-titres et surligne les mots-clés en jaune » | [output edit](/docs/fr/reference/engine/output-edit/) |
| Un autre look | « Passe au thème editorial » | [output edit](/docs/fr/reference/engine/output-edit/) |
| Des effets | « Ajoute un mot qui surgit sur “trois étapes” à 0:12 et un carton de chapitre à 0:40 » | [output edit](/docs/fr/reference/engine/output-edit/) |
| Un autre format | « Ajoute une version 16:9 pour YouTube » | [output edit](/docs/fr/reference/engine/output-edit/) |
| Annuler une modification | « Annule le changement de musique, garde tout ce qui a suivi » | [output edit](/docs/fr/reference/engine/output-edit/) |
| Tous les clips d’un coup | « Enlève l’étiquette de série de tous les clips » | [output edit](/docs/fr/reference/engine/output-edit/) |

</div>

## Conseils pour les demandes de suivi

- **Modifiez le plan avant qu’il ne démarre.** Les relances courtes marchent bien : « seulement TikTok », « moins de 60 secondes chacun », « 5 clips », « vitesse 1,2× », « vitesse d’origine », « en anglais », « plus propre » ou « nettoyage plus léger », « masque les visages » ou « ne masque pas les visages », « ajoute une accroche » ou « sans accroche », « horizontal » ou « vertical », « calé sur le tempo » ou « posé ». Le plan conserve tout ce que vous n’avez pas mentionné.
- **Une modification à la fois** une fois le clip produit. Chaque demande devient une étape d’annulation : facile de comparer et de revenir en arrière.
- **Désignez le moment.** Donnez un horodatage (« à 0:12 »), citez les mots (« là où je dis “trois étapes” ») ou sélectionnez le passage dans l’app.
- **Le texte incrusté dans la vidéo d’origine** (un filigrane ou des sous-titres présents dans votre fichier source) ne peut pas être restylé ni supprimé par une retouche. Reelfold vous prévient quand un clip doit être régénéré à partir de sa source.
- **Dites ce qui vous plaît.** « Garde les sous-titres tels quels, change seulement la couverture » évite qu’une demande touche plus que prévu.

## Voir aussi

- [Votre premier projet](/docs/fr/start/first-project/)
- [Recettes](/docs/fr/concepts/recipes/)
- [Retouches de clips](/docs/fr/concepts/output-edits/)
- [Référence des workflows](/docs/fr/reference/)
