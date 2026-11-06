"""Tables d'export des organisations candidates, du reste à classer et des expériences proches.

Voir ``core/doc/exports_design.md``. Les lignes suivent l'ordre des CSV actuels ; les
événements sont désignés par l'identifiant stable de la table ``evenements``.
"""

from typing import List, Sequence, Set, Tuple

from ...core.event_to_organization import event_ref
from ...core.genealogy import Genealogy
from ...core.shared_experiences import SharedExperienceIndex
from ...formats.tables import Column, Row, Table, TableSpec
from .organization_candidates import (
    DEFAULT_IGNORED_WORDS,
    CandidateIndex,
    build_unmatched,
    shared_experience_persons,
)
from .organization_exports import (
    NAMED_FROM_LABELS,
    SOURCE_LABELS,
    TYPE_LABELS,
    _reason_label,
    _sorted,
    _years,
)


def _text(name: str, description: str) -> Column:
    return Column(name, "text", description)


def _int(name: str, description: str) -> Column:
    return Column(name, "int", description)


def _bool(name: str, description: str) -> Column:
    return Column(name, "bool", description)


ORGANISATIONS = TableSpec(
    "organisations",
    (
        _text("organisation_id", "Identifiant de l'organisation candidate."),
        _text("nom", "Nom de l'organisation."),
        _text("type", "Code du type (company, school, association…)."),
        _text("type_libelle", "Libellé français du type."),
        _text("lieu", "Lieu de l'organisation."),
        _text("source_du_nom", "Origine du nom (lieu, profession, tag…)."),
        _text("mot_declencheur", "Mot qui a déclenché la détection."),
        Column("confiance", "real", "Confiance de la détection, entre 0 et 1."),
        _bool("a_revoir", "Organisation à vérifier."),
        _bool(
            "collectif",
            "Organisation collective (plusieurs personnes au même événement).",
        ),
        _int("nb_personnes", "Nombre de personnes liées."),
        _int("nb_evenements", "Nombre d'événements liés."),
        _int("premiere_annee", "Première année connue."),
        _int("derniere_annee", "Dernière année connue."),
    ),
    primary_key="organisation_id",
)

LIENS = TableSpec(
    "liens",
    (
        _text("organisation_id", "Organisation (table organisations)."),
        _text("organisation", "Nom de l'organisation."),
        _text("personne_id", "Personne (table personnes)."),
        _text("personne", "Nom affiché de la personne."),
        _text("role", "Rôle de la personne."),
        _text("date", "Date de l'événement, telle qu'écrite."),
        _int("annee", "Année de l'événement."),
        _text("lieu", "Lieu de l'événement."),
        _text("type_evenement", "Code du type d'événement d'origine."),
        _text("type_evenement_libelle", "Libellé français du type d'événement."),
        _text("evenement_id", "Événement d'origine (table evenements)."),
        _text("evenement", "Libellé de l'événement."),
        _bool("temoin", "La personne est témoin de l'événement, non son porteur."),
        _int("nb_temoins", "Nombre de témoins de l'événement."),
        _text("statut", "À remplir : statut du lien après vérification."),
        _text("nom_retenu", "À remplir : nom retenu pour l'organisation."),
    ),
)

RESTE_A_CLASSER = TableSpec(
    "reste_a_classer",
    (
        _text("evenement_id", "Événement « Autre » non classé (table evenements)."),
        _text("mot", "Mot partagé qui regroupe l'événement (« autres » sinon)."),
    ),
)

EXPERIENCES_PROCHES = TableSpec(
    "experiences_proches",
    (
        _text("experience_id", "Identifiant de l'expérience proche."),
        _text("theme", "Thème de l'expérience."),
        _text("periode", "Période (année ou intervalle)."),
        _text("lieux", "Lieux de l'expérience."),
        _text("raison", "Raison du rapprochement."),
        _text("personne_id", "Personne (table personnes)."),
        _text("personne", "Nom affiché de la personne."),
        _text("evenement_id", "Événement (table evenements)."),
        _text("evenement", "Libellé de l'événement."),
        _text("annee", "Année ou intervalle de l'événement."),
        _text("lieu", "Lieu de l'événement."),
    ),
)


def _organisations(index: CandidateIndex) -> List[Row]:
    return [
        {
            "organisation_id": c.id,
            "nom": c.name,
            "type": c.type,
            "type_libelle": TYPE_LABELS.get(c.type, c.type),
            "lieu": c.place,
            "source_du_nom": (
                NAMED_FROM_LABELS.get(c.named_from, c.named_from)
                if c.named_from
                else None
            ),
            "mot_declencheur": c.trigger,
            "confiance": c.confidence,
            "a_revoir": c.needs_review,
            "collectif": c.collective,
            "nb_personnes": c.person_count,
            "nb_evenements": c.event_count,
            "premiere_annee": c.first_year,
            "derniere_annee": c.last_year,
        }
        for c in _sorted(index)
    ]


def _liens(index: CandidateIndex) -> List[Row]:
    return [
        {
            "organisation_id": c.id,
            "organisation": c.name,
            "personne_id": m.person_id,
            "personne": m.person_name,
            "role": m.role,
            "date": m.date,
            "annee": m.year,
            "lieu": m.place,
            "type_evenement": m.source_event_type,
            "type_evenement_libelle": SOURCE_LABELS.get(
                m.source_event_type, m.source_event_type
            ),
            "evenement_id": m.source_event_id,
            "evenement": m.event_label.replace("_", " "),
            "temoin": m.witness,
            "nb_temoins": m.witness_count,
            "statut": "",
            "nom_retenu": "",
        }
        for c in _sorted(index)
        for m in sorted(
            c.members, key=lambda m: (m.person_name.casefold(), m.year or 0)
        )
    ]


def _reste_a_classer(
    genealogy: Genealogy,
    index: CandidateIndex,
    shared: SharedExperienceIndex,
    ignored_words: Sequence[str],
) -> List[Row]:
    exclude: Set[Tuple[str, int]] = set(index.matched)
    for exp in shared.items:
        exclude.update((ev.person_id, ev.event_index) for ev in exp.events)
    _, groups = build_unmatched(genealogy, exclude, ignored_words, capped=False)
    return [
        {"evenement_id": event_ref(e.person_id, e.event_index), "mot": group.word}
        for group in groups
        for e in group.events
    ]


def _experiences_proches(
    genealogy: Genealogy, shared: SharedExperienceIndex
) -> List[Row]:
    rows: List[Row] = []
    for e in shared.items:
        period = _years(e.year_min, e.year_max)
        places = ", ".join(e.places)
        reasons = " ; ".join(_reason_label(r.kind, r.place, r.words) for r in e.reasons)
        for p in shared_experience_persons(genealogy, e):
            rows.append(
                {
                    "experience_id": e.id,
                    "theme": e.label,
                    "periode": period,
                    "lieux": places,
                    "raison": reasons,
                    "personne_id": p["person_id"],
                    "personne": p["person_name"],
                    "evenement_id": event_ref(p["person_id"], p["event_index"]),
                    "evenement": p["label"],
                    "annee": _years(p["year_start"], p["year_end"]),
                    "lieu": p["place"],
                }
            )
    return rows


def build_organization_tables(
    genealogy: Genealogy,
    index: CandidateIndex,
    shared: SharedExperienceIndex,
    ignored_words: Sequence[str] = DEFAULT_IGNORED_WORDS,
) -> List[Table]:
    """Tables ``organisations``, ``liens``, ``reste_a_classer``, ``experiences_proches``.

    Le reste à classer est celui de la webapp (sans organisations ni expériences
    proches), mais sans plafond par groupe ; ``ignored_words`` doit être celui de
    la session qui a construit ``index``.
    """
    return [
        Table(ORGANISATIONS, _organisations(index)),
        Table(LIENS, _liens(index)),
        Table(
            RESTE_A_CLASSER,
            _reste_a_classer(genealogy, index, shared, ignored_words),
        ),
        Table(EXPERIENCES_PROCHES, _experiences_proches(genealogy, shared)),
    ]
