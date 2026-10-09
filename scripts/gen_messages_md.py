#!/usr/bin/env python3
"""Regenerate references/MESSAGES.md from vstudio.messages.CATALOG (+ the French column below).

    python3 scripts/gen_messages_md.py          # write the file
    python3 scripts/gen_messages_md.py --check  # exit 1 when the file is out of date (tests/test_messages.py)
"""
import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "lib"))

from vstudio import messages as M  # noqa: E402

# French for the desk (fr locale). "{text}" codes pass the engine / model text through untranslated.
FR = {
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

HEAD = """# Engine messages: codes for the desk

Generated by `python3 scripts/gen_messages_md.py` from `lib/vstudio/messages.py` (do not edit by hand;
`tests/test_messages.py` fails when this file is out of date).

Every engine text a person reads comes with a stable **code** and **params**, next to the English `message` and
Chinese `message_zh` the CLI and older desks show:

    {"code": "qc.loudness", "params": {"value": -9.1, "lufs": -14, ...}, "message": "...", "message_zh": "..."}

The desk maps `code` to its own copy (en / zh-CN / fr below; `{name}` = a param) and falls back to `message` /
`message_zh` for a code it does not know. Codes whose text is `{text}` carry engine or model text through as is
(`params.text`): show it, do not translate it.

## Where the codes are

| Output | Field |
|---|---|
| `vstudio.llm` errors (`--json` of plan-segments, output ai, project ai) | `code`, `tried`, `errors`, `codes`, `attempts`, `message` (`llm-all-failed`) |
| `llm auth status` rows | `message` (`auth-*`, `key-*`, `local-*`; see `vstudio.llm_auth.MSG`) |
| plan-segments | `notices[]` (`plan-*`), `fallback` |
| intake plan | `risks_info[]`, `warnings_info[]`, `questions[].message`, `projects[].checkpoints[].label_info`, `projects[].recipe_info`, `planner.message`, `summary_info` |
| inbox entries | `label_info` (`checkpoint.<kind>`), `reason` (`inbox.<kind>`) |
| project status | `state_info` (`project-state.*`), `items[].state_info` (`job-state.*`), `items[].qc_info` (`qc-state.*`), `items[].stages[].label_info` (`stage.*`) |
| QC (`qc.json`, job detail) | `checks[].message`, `reasons_info[]`, `warnings_info[]` (`qc.<check>`) |
| `.vstudio/status.json` | `status_info` (`status.*`), `stage_info` (`stage.*`), `message_info` (`status-text` or the writer's `message_code`) |
| publishing calendar | `posts[].state_info`, `states` (`post-state.*`) |
| output ai / project ai | `summary_info`, `groups[].summary_info`, `groups[].proposed[].why_info` (`ai-summary`, `ai-why`); errors and notes already carry `code` + `params` (`vstudio.project.outputs.msg`) |
| recipes (`vstudio.project recipes --json`, project show) | `messages.label`, `messages.description` (`recipe.<id>.label`, `recipe.<id>.description`: the manifest's own zh / en texts) |

## Codes
"""


def render():
    rows = ["| Code | en | zh-CN | fr |", "|---|---|---|---|"]
    esc = lambda t: str(t).replace("|", "\\|")  # noqa: E731
    for code, (en, zh) in M.CATALOG.items():
        rows.append(f"| `{code}` | {esc(en)} | {esc(zh)} | {esc(FR.get(code, en if en == '{text}' else ''))} |")
    fam = "\n".join(f"- `{f}`" for f in M.FAMILIES)
    return HEAD + "\n" + "\n".join(rows) + "\n\nCode families with an id (texts come from the recipe manifest):\n\n" + \
        fam + "\n"


def main(argv):
    out = ROOT / "references" / "MESSAGES.md"
    txt = render()
    if "--check" in argv:
        missing = [c for c, (en, _) in M.CATALOG.items() if en != "{text}" and c not in FR]
        if missing:
            print("no French for: " + ", ".join(missing))
            return 1
        if not out.exists() or out.read_text(encoding="utf-8") != txt:
            print("references/MESSAGES.md is out of date: python3 scripts/gen_messages_md.py")
            return 1
        return 0
    out.write_text(txt, encoding="utf-8")
    print(out)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
