---
title: 'Confidentialité : ce que Reelfold envoie'
description: L’app Mac peut partager des statistiques d’usage anonymes, seulement si vous l’activez. Chaque champ envoyé, comment le désactiver et comment supprimer les données.
---

L’app Mac Reelfold peut nous envoyer quelques compteurs anonymes, par exemple « un lot de 12 clips terminé ». C’est **désactivé tant que vous ne l’activez pas** (au premier lancement, ou dans **Réglages › Général › Confidentialité**). Désactivé, rien n’est envoyé et aucun identifiant n’est créé.

**Champs envoyés** (en HTTPS vers `https://t.reelfold.com/api/v1/ping`) : un identifiant aléatoire créé sur votre ordinateur (remplaçable), la version de l’app, le système et le processeur, la langue de l’app, le nom de l’événement (`app_open` au plus une fois par jour, `first_batch_done`, `batch_done`, `export_done`, `publish_package`), le jour (sans l’heure) et quelques petits entiers (nombre de clips, de formats, de minutes, de plateformes). Jamais de noms de fichiers, chemins, textes, transcriptions, consignes, clés ni vidéo.

**Côté serveur** : l’adresse IP n’est ni stockée ni journalisée ; les champs inconnus sont ignorés ; les événements bruts sont supprimés après 13 mois (seuls des totaux quotidiens sans identifiant sont conservés).

**Désactiver** : Réglages › Général › Confidentialité. **Supprimer** : le bouton « Supprimer mes données d’usage » efface tout ce que votre identifiant a envoyé, puis en crée un nouveau.

Détails complets (en anglais) : [Privacy: what Reelfold sends](/docs/concepts/usage-counts/).
