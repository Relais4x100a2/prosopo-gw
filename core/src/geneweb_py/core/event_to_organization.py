"""Déduction d'organisations à partir des événements personnalisés (``#strng``).

Deux étages :

1. règles déterministes sur le tag (``Membre_Academie``, ``Eleve_BeauxArts``) et sur le
   lieu décomposé (``[Atelier_Rose]_-_Lyon`` -> organisation « Atelier Rose ») ;
2. hook optionnel (``LLMExtractorProtocol``) appelé seulement quand les règles sont
   absentes ou peu fiables (notes à exploiter, confiance basse).

Sans hook, seules les règles s'appliquent. Le module n'importe aucun client LLM.
"""

import re
import unicodedata
from dataclasses import dataclass, field, replace
from typing import (
    TYPE_CHECKING,
    Dict,
    FrozenSet,
    List,
    Mapping,
    Optional,
    Set,
    Tuple,
)

from typing_extensions import Protocol

from .date import Date
from .event import Event, EventType, WitnessKind
from .organization import Organization, OrganizationType

if TYPE_CHECKING:
    from .genealogy import Genealogy

# En dessous, une organisation est marquée ``needs_review`` et le hook est sollicité
REVIEW_THRESHOLD = 0.7

_CONF_STRONG = 0.8
_CONF_OCCUPATION_TEXT = 0.7
_CONF_WEAK = 0.5


@dataclass
class OrganizationProposal:
    """Organisation proposée pour un événement (règles ou hook)"""

    name: str
    type: OrganizationType = OrganizationType.OTHER
    role: Optional[str] = None
    place: Optional[str] = None
    confidence: float = _CONF_WEAK
    # ``None`` : déduit de ``confidence`` (< REVIEW_THRESHOLD => à revoir)
    needs_review: Optional[bool] = None
    aliases: List[str] = field(default_factory=list)
    notes: List[str] = field(default_factory=list)
    # Source du nom : "tag", "place", "typed_event" ou "occupation_text"
    named_from: Optional[str] = None
    # Mot (replié) d'établissement ou de relation qui a décidé du type
    trigger: Optional[str] = None
    relation: bool = False
    # Nom pris faute de mieux (complément sans mot d'établissement, tag sans nom)
    to_determine: bool = False
    # Source écartée, recopiée dans ``Organization.metadata`` (``complement`` / ``tag``)
    extra: Dict[str, str] = field(default_factory=dict)

    @property
    def review_required(self) -> bool:
        if self.needs_review is not None:
            return self.needs_review
        return self.confidence < REVIEW_THRESHOLD


@dataclass
class EventContext:
    """Ce que le hook reçoit : l'événement et la proposition des règles (ou None)"""

    person_id: str
    event_type_raw: str
    date: Optional[str]
    place: Optional[str]
    notes: List[str]
    heuristic: Optional[OrganizationProposal]


class LLMExtractorProtocol(Protocol):
    """Hook d'enrichissement : renvoie une proposition, ou ``None`` si rien à dire"""

    def __call__(self, context: EventContext) -> Optional[OrganizationProposal]: ...


@dataclass(frozen=True)
class PrefixRule:
    """Règle d'un préfixe de tag : rôle déduit, type d'organisation"""

    role: str
    type: OrganizationType
    # Le reste du tag nomme l'organisation (``Membre_Academie``) ; faux pour
    # ``Cours_peinture`` où il désigne une matière
    remainder_is_name: bool = True


DEFAULT_PREFIX_RULES: Dict[str, PrefixRule] = {
    "membre": PrefixRule("Membre", OrganizationType.ASSOCIATION),
    "eleve": PrefixRule("Élève", OrganizationType.SCHOOL),
    "cours": PrefixRule("Élève", OrganizationType.SCHOOL, remainder_is_name=False),
    "professeur": PrefixRule("Professeur", OrganizationType.SCHOOL),
    "employe": PrefixRule("Employé", OrganizationType.COMPANY),
    "ouvrier": PrefixRule("Ouvrier", OrganizationType.COMPANY),
    "directeur": PrefixRule("Directeur", OrganizationType.OTHER),
    "soldat": PrefixRule("Soldat", OrganizationType.MILITARY),
    "officier": PrefixRule("Officier", OrganizationType.MILITARY),
    "pretre": PrefixRule("Prêtre", OrganizationType.RELIGIOUS),
}


def _fold(text: str) -> str:
    stripped = unicodedata.normalize("NFKD", text).encode("ascii", "ignore")
    return stripped.decode("ascii").lower()


def _split_tag_ex(
    tag: str, rules: Dict[str, PrefixRule]
) -> Tuple[Optional[PrefixRule], Optional[str], Optional[str]]:
    """Sépare un tag en (règle de rôle, nom candidat, reste du tag).

    Le reste est le tag privé de son préfixe de rôle (le tag entier sans préfixe) ;
    le nom candidat en est une copie, sauf quand le reste désigne une matière
    (``Cours_peinture``) et non une organisation.
    """
    parts = [p for p in re.split(r"[_-]+", tag) if p]
    if not parts:
        return None, None, None
    rule = rules.get(_fold(parts[0]))
    remainder_parts = parts[1:] if rule else parts
    words: List[str] = []
    for part in remainder_parts:
        if part.isdigit():
            continue
        words.extend(re.sub(r"(?<=[a-z])(?=[A-Z])", " ", part).split())
    rest = " ".join(words) or None
    if rule is not None and not rule.remainder_is_name:
        return rule, None, rest
    return rule, rest, rest


def _split_tag(
    tag: str, rules: Dict[str, PrefixRule]
) -> Tuple[Optional[PrefixRule], Optional[str]]:
    """Sépare un tag en (règle de rôle, nom d'organisation candidat)."""
    rule, name, _ = _split_tag_ex(tag, rules)
    return rule, name


# Mots d'établissement (repliés par ``_fold``) -> type d'organisation.
# « compagnie » vaut ``company``, sauf suivi d'un numéro (``_establishment_in``).
ESTABLISHMENT_WORDS: Dict[str, OrganizationType] = {
    **dict.fromkeys(
        (
            "usine",
            "societe",
            "entreprise",
            "compagnie",
            "manufacture",
            "atelier",
            "magasin",
            "maison",
            "banque",
            "etablissement",
            # Lieux d'activité, qui tenaient lieu de raison sociale avant 1900
            "agence",
            "boutique",
            "comptoir",
            "fabrique",
            "filature",
            "bureau",
            # Singulier seulement : « Études de droit » n'est pas une étude notariale
            "etude",
            # Formes de société (« et Cie », « & Cie. »)
            "commandite",
            "cie",
        ),
        OrganizationType.COMPANY,
    ),
    **dict.fromkeys(
        (
            "ecole",
            "college",
            "lycee",
            "universite",
            "institut",
            "academie",
            "conservatoire",
        ),
        OrganizationType.SCHOOL,
    ),
    **dict.fromkeys(
        (
            "association",
            "club",
            "cercle",
            "syndicat",
            "federation",
            "comite",
            "amicale",
            "loge",
        ),
        OrganizationType.ASSOCIATION,
    ),
    **dict.fromkeys(
        (
            "mairie",
            "conseil",
            "chambre",
            "tribunal",
            "prefecture",
            "ministere",
            "hopital",
            "hospice",
        ),
        OrganizationType.INSTITUTION,
    ),
    **dict.fromkeys(
        (
            "paroisse",
            "diocese",
            "abbaye",
            "couvent",
            "consistoire",
            "synagogue",
            "temple",
        ),
        OrganizationType.RELIGIOUS,
    ),
    **dict.fromkeys(
        ("regiment", "bataillon", "armee", "garde"), OrganizationType.MILITARY
    ),
}

# Un tag qui en contient un désigne un cercle de relations, pas une institution
RELATION_WORDS: FrozenSet[str] = frozenset(
    {"amitie", "collaboration", "correspondance", "rencontre", "voisinage"}
)

# Prépositions qui séparent le métier de l'employeur (les plus longues d'abord)
OCCUPATION_PREPOSITIONS: Tuple[str, ...] = (
    "à la",
    "à l'",
    "de la",
    "de l'",
    "chez",
    "pour",
    "aux",
    "des",
    "au",
    "du",
    "à",
)


@dataclass(frozen=True)
class TypedEventRule:
    """Événement typé dont le complément de lieu est un établissement"""

    type: OrganizationType
    # ``None`` : rôle dérivé du texte du métier (``occu``)
    role: Optional[str]


TYPED_EVENT_RULES: Dict[EventType, TypedEventRule] = {
    EventType.OCCUPATION: TypedEventRule(OrganizationType.COMPANY, None),
    EventType.EDUCATION: TypedEventRule(OrganizationType.SCHOOL, "élève"),
    EventType.GRADUATION: TypedEventRule(OrganizationType.SCHOOL, "diplômé"),
    EventType.DIPLOMA: TypedEventRule(OrganizationType.SCHOOL, "diplômé"),
    EventType.ADHESION: TypedEventRule(OrganizationType.ASSOCIATION, "membre"),
    EventType.HOSPITALISATION: TypedEventRule(OrganizationType.INSTITUTION, "patient"),
    EventType.MILITARY_SERVICE: TypedEventRule(OrganizationType.MILITARY, "soldat"),
    EventType.DEMOBILISATION: TypedEventRule(OrganizationType.MILITARY, "soldat"),
    EventType.ELECTION: TypedEventRule(OrganizationType.INSTITUTION, "élu"),
    EventType.ORDINATION: TypedEventRule(OrganizationType.RELIGIOUS, "ordonné"),
}

_DEFAULT_OCCUPATION_ROLE = "employé"

_EVENT_REF_RE = re.compile(r"^pevt:(?P<person>.+):(?P<index>\d+)$")


def event_ref(person_id: str, index: int) -> str:
    """Référence stable d'un événement personnel (``OrganizationLink.source_event_id``)."""
    return f"pevt:{person_id}:{index}"


def parse_event_ref(ref: Optional[str]) -> Optional[Tuple[str, int]]:
    """Inverse de ``event_ref`` ; ``None`` si le format est inattendu."""
    if not ref:
        return None
    match = _EVENT_REF_RE.match(ref)
    if match is None:
        return None
    return match.group("person"), int(match.group("index"))


# Formes juridiques reconnues telles qu'écrites (capitales, « Et. » avec son point)
LEGAL_FORMS: FrozenSet[str] = frozenset({"SNC", "SARL", "SA", "SAS", "Et."})

# Mots qui désignent à eux seuls une société : un tag qui en contient un suffit,
# même porté par une seule personne sans témoin (« Formation société X et Cie »)
COMPANY_NAME_TRIGGERS: FrozenSet[str] = frozenset(
    {"societe", "cie", "commandite", "snc", "sarl", "sa", "sas", "et."}
)

_QUOTES = '"«»“”„'


def _company_name(tag_name: str, trigger: str) -> str:
    """Nom de la société lue dans un tag.

    Les mots qui précèdent « société » décrivent l'acte (« Formation »,
    « Dissolution », « Président de la ») : ils sont retirés, pour que tous les
    actes d'une même société désignent la même organisation.
    """
    words = tag_name.split()
    if trigger == "societe":
        folded = [_fold(w).strip(_QUOTES) for w in words]
        if "societe" in folded:
            words = words[folded.index("societe") :]
    name = " ".join(w.strip(_QUOTES) for w in words).strip()
    name = " ".join(name.split())
    return name[:1].upper() + name[1:] if name else tag_name


# Témoins d'un événement retenu comme organisation : membres ou acteurs de celle-ci
WITNESS_ROLE = "Témoin"
WITNESS_NOTE = "witness"
WITNESS_KIND_ROLES: Dict[WitnessKind, str] = {
    WitnessKind.GODPARENT: "Parrain ou marraine",
    WitnessKind.OFFICER: "Officier",
}


def _witness_ids(event: Event, genealogy: "Genealogy") -> Set[str]:
    """Témoins de l'événement présents dans la généalogie."""
    return {
        w["person_id"]
        for w in event.witnesses
        if w.get("person_id") in genealogy.persons
    }


def _words(text: str) -> List[str]:
    """Mots repliés (sans casse ni accents), séparés par ``_ - espace`` et apostrophes."""
    return [w for w in re.split(r"[_\-\s'’]+", _fold(text)) if w]


def _establishment_in(text: str) -> Optional[Tuple[str, OrganizationType]]:
    """Premier mot d'établissement du texte : (mot replié, type)."""
    # Formes juridiques sensibles à la casse : « sa », « et » sont des mots courants
    for raw in re.split(r"[_\-\s'’]+", text):
        if raw in LEGAL_FORMS:
            return _fold(raw), OrganizationType.COMPANY
    words = [w.strip(_QUOTES).rstrip(".") for w in _words(text)]
    for i, word in enumerate(words):
        org_type = ESTABLISHMENT_WORDS.get(word)
        if org_type is None:
            continue
        if word == "compagnie" and i + 1 < len(words) and words[i + 1].isdigit():
            return word, OrganizationType.MILITARY
        return word, org_type
    return None


CIVIL_STATUS_WORDS: FrozenSet[str] = frozenset(
    {
        "naissance",
        "bapteme",
        "mariage",
        "divorce",
        "separation",
        "fiancailles",
        "bans",
        "reconnaissance",
        "legitimation",
        "adoption",
        "deces",
        "inhumation",
        "sepulture",
        "recensement",
        "domicile",
    }
)

STREET_WORDS: FrozenSet[str] = frozenset(
    {
        "rue",
        "passage",
        "avenue",
        "boulevard",
        "place",
        "impasse",
        "quai",
        "chemin",
        "allee",
        "cours",
        "square",
        "villa",
        "cite",
    }
)

MONTH_WORDS: FrozenSet[str] = frozenset(
    {
        "janvier",
        "fevrier",
        "mars",
        "avril",
        "mai",
        "juin",
        "juillet",
        "aout",
        "septembre",
        "octobre",
        "novembre",
        "decembre",
    }
)

_BIS_WORDS = frozenset({"bis", "ter", "quater"})


def is_civil_status(tag: Optional[str]) -> bool:
    """Vrai si un mot du tag relève de l'état civil (``CIVIL_STATUS_WORDS``)."""
    return bool(tag) and any(w in CIVIL_STATUS_WORDS for w in _words(tag or ""))


def _is_number(word: str) -> bool:
    return word.isdigit() and len(word) <= 4


def address_in(text: Optional[str]) -> bool:
    """Vrai si le texte est une adresse : mot de voie et numéro en tête ou en fin.

    Un nombre au milieu fait partie du nom de la voie (« rue du 14 Juillet »).
    Un numéro en tête est refusé si le mot suivant est un mois ; un numéro en fin
    est refusé si le mot précédent est un mois et que le nombre a 4 chiffres
    (une année).
    """
    if not text:
        return False
    words = [w for w in re.split(r"[_,\s]+", _fold(text)) if w]
    if not any(w in STREET_WORDS for w in words):
        return False
    # numéro en tête
    if _is_number(words[0]):
        nxt = words[1] if len(words) > 1 else ""
        if nxt in _BIS_WORDS:
            nxt = words[2] if len(words) > 2 else ""
        if nxt not in MONTH_WORDS:
            return True
    # numéro en fin (éventuellement suivi de bis/ter/quater)
    end = len(words) - 1
    if end > 0 and words[end] in _BIS_WORDS:
        end -= 1
    if end > 0 and _is_number(words[end]):
        before = words[end - 1]
        if not (before in MONTH_WORDS and len(words[end]) == 4):
            return True
    return False


def _relation_in(text: str) -> Optional[str]:
    """Premier mot de relation du texte (replié), ``None`` sinon."""
    for word in _words(text):
        if word in RELATION_WORDS:
            return word
    return None


def _extra(key: str, value: Optional[str]) -> Dict[str, str]:
    """Source écartée à recopier dans les métadonnées (vide si absente)."""
    return {key: value} if value else {}


def _occupation_split_re() -> "re.Pattern[str]":
    alternatives = []
    for prep in OCCUPATION_PREPOSITIONS:
        pattern = re.escape(prep).replace(r"\ ", r"\s+")
        alternatives.append(pattern if prep.endswith("'") else pattern + r"(?=\s)")
    return re.compile(
        r"(?:^|\s)(?P<prep>" + "|".join(alternatives) + ")", re.IGNORECASE
    )


_OCCUPATION_SPLIT_RE = _occupation_split_re()


class EventToOrganizationMapper:
    """Convertit les événements personnalisés d'une généalogie en organisations."""

    def __init__(
        self,
        llm: Optional[LLMExtractorProtocol] = None,
        custom_rules: Optional[Dict[str, PrefixRule]] = None,
    ) -> None:
        """
        Args:
            llm: hook d'enrichissement optionnel (étage 2).
            custom_rules: règles de préfixe ajoutées à ``DEFAULT_PREFIX_RULES`` ou les
                remplaçant ; clés insensibles à la casse et aux accents.
        """
        self.llm = llm
        self.rules: Dict[str, PrefixRule] = dict(DEFAULT_PREFIX_RULES)
        for prefix, rule in (custom_rules or {}).items():
            self.rules[_fold(prefix)] = rule

    # -- Étage 1 : règles ---------------------------------------------------
    def propose(
        self,
        event: Event,
        tag_person_counts: Optional[Mapping[str, int]] = None,
        person_occupation: Optional[str] = None,
        tag_member_counts: Optional[Mapping[str, int]] = None,
    ) -> Optional[OrganizationProposal]:
        """Proposition déterministe pour un événement, ``None`` sans signal.

        Args:
            event: événement personnel.
            tag_person_counts: nombre de personnes distinctes par tag replié
                (nom d'organisation), pour les tags sans préfixe de rôle.
            person_occupation: attribut profession, rôle de repli d'un ``occu``.
            tag_member_counts: comme ``tag_person_counts``, témoins compris ;
                seul un tag à mot d'établissement s'en sert (une société portée
                par une personne et ses associés témoins).
        """
        parts = event.place_parts
        complement = parts.complement if parts else None
        city = parts.city if parts else None

        typed = TYPED_EVENT_RULES.get(event.event_type)
        if typed is not None:
            return self._propose_typed(
                event, typed, complement, city, person_occupation
            )

        tag = event.event_type_raw
        if event.event_type is not EventType.OTHER or not tag:
            return None

        rule, tag_name, tag_rest = _split_tag_ex(tag, self.rules)
        role = rule.role if rule else None
        rule_type = rule.type if rule else OrganizationType.OTHER

        # 0. tag qui nomme une société : prime sur le complément (« Dissolution
        # société X » enregistrée au tribunal reste rattachée à la société)
        company = _establishment_in(tag_name) if rule is None and tag_name else None
        if tag_name and company is not None and company[0] in COMPANY_NAME_TRIGGERS:
            return OrganizationProposal(
                name=_company_name(tag_name, company[0]),
                type=OrganizationType.COMPANY,
                place=city,
                confidence=_CONF_STRONG,
                named_from="tag",
                trigger=company[0],
                extra=_extra("complement", complement),
            )

        # 1. complément contenant un mot d'établissement
        if complement:
            found = _establishment_in(complement)
            if found is not None:
                extra = _extra("tag", tag_name or tag_rest)
                return OrganizationProposal(
                    name=complement,
                    type=found[1],
                    role=role,
                    place=city,
                    confidence=_CONF_STRONG,
                    named_from="place",
                    trigger=found[0],
                    extra=extra,
                )

        # 2. tag qui dit plus qu'un rôle
        extra = _extra("complement", complement)
        found_tag = _establishment_in(tag_name) if tag_name else None
        tag_key = _fold(tag_name or "")
        shared = bool(tag_name) and (tag_person_counts or {}).get(tag_key, 0) >= 2
        shared_with_witnesses = shared or (
            bool(tag_name) and (tag_member_counts or {}).get(tag_key, 0) >= 2
        )
        if tag_name and rule is not None:
            return OrganizationProposal(
                name=tag_name,
                type=found_tag[1] if found_tag else rule.type,
                role=role,
                place=city,
                confidence=_CONF_STRONG,
                named_from="tag",
                trigger=found_tag[0] if found_tag else None,
                extra=extra,
            )
        if tag_name and shared_with_witnesses and found_tag is not None:
            return OrganizationProposal(
                name=tag_name,
                type=found_tag[1],
                place=city,
                confidence=_CONF_STRONG,
                named_from="tag",
                trigger=found_tag[0],
                extra=extra,
            )

        # 2 bis. adresse (numéro + mot de voie) dans le tag, sinon dans le complément ;
        # le numéro est écarté de ``tag_name`` : l'adresse se lit dans le tag brut ;
        # un préfixe de rôle reconnu (``Cours_anglais_1``) exclut l'adresse sur le tag
        if rule is None and address_in(tag):
            address_name, address_extra = tag.replace("_", " "), extra
        elif address_in(complement):
            address_name, address_extra = complement or "", _extra("tag", tag_name)
        else:
            address_name, address_extra = None, extra
        if address_name is not None:
            return OrganizationProposal(
                name=address_name,
                type=OrganizationType.OTHER,
                role=role,
                place=city,
                confidence=_CONF_OCCUPATION_TEXT,
                named_from="address",
                extra=address_extra,
            )

        if tag_name and shared:
            relation = _relation_in(tag_name)
            if relation is not None:
                return OrganizationProposal(
                    name=tag_name,
                    type=OrganizationType.OTHER,
                    place=city,
                    confidence=_CONF_WEAK,
                    notes=["relation"],
                    relation=True,
                    named_from="tag",
                    trigger=relation,
                    extra=extra,
                )
            return OrganizationProposal(
                name=tag_name,
                type=OrganizationType.OTHER,
                place=city,
                confidence=_CONF_WEAK,
                named_from="tag",
                extra=extra,
            )

        # 3. à déterminer : le complément restant sert de nom
        if complement:
            discarded = tag_name or tag_rest
            return OrganizationProposal(
                name=complement,
                type=rule_type,
                role=role,
                place=city,
                confidence=_CONF_WEAK,
                named_from="place",
                to_determine=True,
                extra=_extra("tag", discarded),
            )
        return None

    def _propose_typed(
        self,
        event: Event,
        typed: TypedEventRule,
        complement: Optional[str],
        city: Optional[str],
        person_occupation: Optional[str],
    ) -> Optional[OrganizationProposal]:
        """Événement typé : l'établissement est le complément de lieu (§ 3.6)."""
        if not complement:
            return None
        role = typed.role
        if role is None:
            role = (
                (event.notes[0] if event.notes else None)
                or person_occupation
                or _DEFAULT_OCCUPATION_ROLE
            )
        found = _establishment_in(complement)
        return OrganizationProposal(
            name=complement,
            type=found[1] if found else typed.type,
            role=role,
            place=city,
            confidence=_CONF_STRONG,
            named_from="typed_event",
            trigger=found[0] if found else None,
        )

    def propose_from_occupation(
        self, text: str, place: Optional[str] = None
    ) -> Optional[OrganizationProposal]:
        """Employeur lu dans un texte de métier « métier à / chez X » (§ 3.7)."""
        first = text.replace("_", " ").split(",")[0].strip()
        match = _OCCUPATION_SPLIT_RE.search(first)
        if match is None:
            return None
        role = first[: match.start()].strip()
        name = first[match.end() :].strip()
        if not role or not name:
            return None
        found = _establishment_in(name)
        if found is not None:
            return OrganizationProposal(
                name=name,
                type=found[1],
                role=role,
                place=place,
                confidence=_CONF_OCCUPATION_TEXT,
                named_from="occupation_text",
                trigger=found[0],
            )
        if _fold(match.group("prep")).strip() == "chez":
            return OrganizationProposal(
                name=name,
                type=OrganizationType.COMPANY,
                role=role,
                place=place,
                confidence=_CONF_WEAK,
                named_from="occupation_text",
            )
        return None

    # -- Étage 2 : hook -----------------------------------------------------
    def _refine(
        self,
        person_id: str,
        event: Event,
        heuristic: Optional[OrganizationProposal],
    ) -> Optional[OrganizationProposal]:
        if self.llm is None:
            return heuristic
        uncertain = (heuristic is None and bool(event.notes)) or (
            heuristic is not None and heuristic.confidence < REVIEW_THRESHOLD
        )
        if not uncertain:
            return heuristic

        context = EventContext(
            person_id=person_id,
            event_type_raw=event.event_type_raw or "",
            date=event.date.display_text if event.date else None,
            place=event.place,
            notes=list(event.notes),
            heuristic=heuristic,
        )
        try:
            answer = self.llm(context)
        except Exception:  # un hook défaillant ne doit pas casser l'inférence
            return heuristic
        if answer is None:
            return heuristic
        if heuristic is None:
            return answer

        merged = replace(
            answer,
            role=answer.role or heuristic.role,
            place=answer.place or heuristic.place,
            aliases=list(answer.aliases),
            named_from=answer.named_from or heuristic.named_from,
            trigger=answer.trigger or heuristic.trigger,
            relation=answer.relation or heuristic.relation,
            extra=dict(answer.extra or heuristic.extra),
        )
        if merged.name != heuristic.name and heuristic.name not in merged.aliases:
            merged.aliases.append(heuristic.name)
        return merged

    # -- Application à une généalogie --------------------------------------
    def _tag_counts(
        self, genealogy: "Genealogy"
    ) -> Tuple[Dict[str, int], Dict[str, int]]:
        """Personnes distinctes par tag (replié) des événements « Autre ».

        Returns:
            (porteurs seuls, porteurs et témoins)
        """
        holders: Dict[str, Set[str]] = {}
        members: Dict[str, Set[str]] = {}
        for person_id, person in genealogy.persons.items():
            for event in person.events:
                if event.event_type is not EventType.OTHER or not event.event_type_raw:
                    continue
                _, name = _split_tag(event.event_type_raw, self.rules)
                if name:
                    key = _fold(name)
                    holders.setdefault(key, set()).add(person_id)
                    members.setdefault(key, set()).update(
                        {person_id, *_witness_ids(event, genealogy)}
                    )
        return (
            {key: len(ids) for key, ids in holders.items()},
            {key: len(ids) for key, ids in members.items()},
        )

    def apply(self, genealogy: "Genealogy") -> Tuple[int, int]:
        """Ajoute organisations et liens.

        Returns:
            (organisations créées, liens créés)
        """
        created_orgs = 0
        created_links = 0
        seen: Set[
            Tuple[str, str, Optional[str], Optional[str], Optional[str], Optional[str]]
        ] = {
            (
                link.person_id,
                link.organization_id,
                link.source_event_type,
                link.role,
                link.start_date.display_text if link.start_date else None,
                link.source_event_id,
            )
            for link in genealogy.organization_links
        }
        counts, member_counts = self._tag_counts(genealogy)

        def register(
            person_id: str,
            proposal: OrganizationProposal,
            source_type: Optional[str],
            source_id: Optional[str],
            start: Optional[Date],
            event: Optional[Event] = None,
        ) -> None:
            nonlocal created_orgs, created_links
            org = Organization.create(proposal.name, place=proposal.place)
            existing = genealogy.organizations.get(org.id)
            if existing is None:
                org.type = proposal.type
                org.aliases = list(proposal.aliases)
                org.notes = list(proposal.notes)
                org.confidence = proposal.confidence
                org.needs_review = proposal.review_required
                org.metadata = {
                    "named_from": proposal.named_from,
                    "trigger": proposal.trigger,
                    "to_determine": proposal.to_determine,
                    **proposal.extra,
                }
                genealogy.add_organization(org)
                created_orgs += 1
            else:
                # Fusion : une source sûre lève le doute des autres
                existing.confidence = max(
                    existing.confidence or 0.0, proposal.confidence
                )
                existing.needs_review = (
                    existing.needs_review and proposal.review_required
                )
                if "to_determine" in existing.metadata:
                    existing.metadata["to_determine"] = bool(
                        existing.metadata["to_determine"] and proposal.to_determine
                    )
                for note in proposal.notes:
                    if note not in existing.notes:
                        existing.notes.append(note)
                org = existing

            def link(member_id: str, role: Optional[str], notes: List[str]) -> None:
                nonlocal created_links
                key = (
                    member_id,
                    org.id,
                    source_type,
                    role,
                    start.display_text if start else None,
                    source_id,
                )
                if key in seen:
                    return
                seen.add(key)
                genealogy.link_person_to_organization(
                    member_id,
                    org.id,
                    role=role,
                    start_date=start,
                    source_event_id=source_id,
                    source_event_type=source_type,
                    notes=notes,
                )
                created_links += 1

            link(person_id, proposal.role, [])
            if event is None:
                return
            # Témoins : membres de l'organisation ou acteurs de l'événement
            for witness in event.witnesses:
                witness_id = witness.get("person_id")
                if witness_id == person_id or witness_id not in genealogy.persons:
                    continue
                kind = witness.get("witness_kind")
                role = WITNESS_KIND_ROLES.get(kind, WITNESS_ROLE) if kind else None
                link(witness_id, role or WITNESS_ROLE, [WITNESS_NOTE])

        for person_id, person in genealogy.persons.items():
            for index, event in enumerate(person.events):
                proposal = self._refine(
                    person_id,
                    event,
                    self.propose(event, counts, person.occupation, member_counts),
                )
                if (
                    proposal is None
                    and event.event_type is EventType.OCCUPATION
                    and event.notes
                    and not (event.place_parts and event.place_parts.complement)
                ):
                    city = event.place_parts.city if event.place_parts else None
                    proposal = self.propose_from_occupation(event.notes[0], city)
                if proposal is None:
                    continue
                source_type = (
                    event.event_type_raw
                    if event.event_type is EventType.OTHER
                    else event.event_type.value
                )
                register(
                    person_id,
                    proposal,
                    source_type,
                    event_ref(person_id, index),
                    event.date,
                    event,
                )

            if person.occupation:
                proposal = self.propose_from_occupation(person.occupation)
                if proposal is not None:
                    register(person_id, proposal, "occu_attr", None, None)
        return created_orgs, created_links
