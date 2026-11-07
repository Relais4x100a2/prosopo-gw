"""
Convertisseur GEDCOM pour geneweb-py.

Ce module fournit les fonctionnalités d'export et d'import vers/depuis
le format GEDCOM (Genealogical Data Communication), un standard
international pour l'échange de données généalogiques.

L'import lit des enregistrements ``HEAD``, ``INDI`` et ``FAM`` avec
résolution des pointeurs, ``DATE``, ``NOTE`` et continuations ``CONT`` /
``CONC``. Les erreurs de conversion sont levées via ``ConversionError``
(hiérarchie ``GeneWebError``). La lecture fichier détecte l'encodage
(UTF-8 puis ``chardet``, repli ISO-8859-1), alignée sur le parser .gw.

Dates : préfixes ``ABT`` / ``BEF`` / ``AFT`` / ``EST``, intervalles
``BET ... AND ...`` et calendriers républicain (``@#DFRENCH R@``) et hébreu
(``@#DHEBREW@``) sont conservés à l'aller-retour. Limites du format :

- une date inconnue (``is_unknown``) n'est pas écrite, GEDCOM n'ayant pas de
  valeur valide pour elle ; elle est relue comme absente (``None``) ;
- « peut-être » est écrit ``EST`` et relu comme « vers » (``ABOUT``) ;
- les dates ``OR`` (alternatives) ne sont pas écrites.
"""

from datetime import datetime
from pathlib import Path
from typing import Any

import chardet

from ..core.date import CalendarType, Date, DatePrefix
from ..core.event import (
    Event,
    EventType,
    FamilyEvent,
    FamilyEventType,
    PersonalEvent,
)
from ..core.family import Child, ChildSex, Family, MarriageStatus
from ..core.genealogy import Genealogy
from ..core.person import Gender, Person, Title
from .base import BaseExporter, BaseImporter, ConversionError


class GEDCOMExporter(BaseExporter):
    """Exporteur vers le format GEDCOM."""

    def __init__(self, encoding: str = "utf-8", version: str = "5.5.1"):
        """
        Initialise l'exporteur GEDCOM.

        Args:
            encoding: Encodage à utiliser (défaut: utf-8)
            version: Version GEDCOM à utiliser (défaut: 5.5.1)
        """
        super().__init__(encoding)
        self.version = version
        self._person_ids: dict[str, str] = {}
        self._family_ids: dict[str, str] = {}
        self._spouse_families: dict[str, list[str]] = {}
        self._child_families: dict[str, list[str]] = {}
        self._next_person_id = 1
        self._next_family_id = 1

    def export(self, genealogy: Genealogy, output_path: str | Path) -> None:
        """
        Exporte une généalogie vers un fichier GEDCOM.

        Args:
            genealogy: Objet Genealogy à exporter
            output_path: Chemin du fichier de sortie

        Raises:
            ConversionError: En cas d'erreur de conversion
        """
        self._validate_genealogy(genealogy)

        try:
            gedcom_content = self.export_to_string(genealogy)

            with open(output_path, "w", encoding=self.encoding) as f:
                f.write(gedcom_content)

        except Exception as e:
            raise ConversionError(f"Erreur lors de l'export GEDCOM : {e}") from e

    def export_to_string(self, genealogy: Genealogy) -> str:
        """
        Exporte une généalogie vers une chaîne GEDCOM.

        Args:
            genealogy: Objet Genealogy à exporter

        Returns:
            Chaîne GEDCOM formatée

        Raises:
            ConversionError: En cas d'erreur de conversion
        """
        self._validate_genealogy(genealogy)

        # Réinitialiser les compteurs
        self._person_ids.clear()
        self._family_ids.clear()
        self._next_person_id = 1
        self._next_family_id = 1

        lines = []

        # En-tête GEDCOM
        lines.extend(self._generate_header())

        # Assigner des IDs aux personnes et familles
        for person in genealogy.persons.values():
            person_id = f"I{self._next_person_id:04d}"
            self._person_ids[person.unique_id] = person_id
            self._next_person_id += 1

        for family in genealogy.families.values():
            family_id = f"F{self._next_family_id:04d}"
            self._family_ids[family.family_id] = family_id
            self._next_family_id += 1

        self._index_family_links(genealogy)

        # Exporter les personnes
        for person in genealogy.persons.values():
            lines.extend(self._export_person(person))

        # Exporter les familles
        for family in genealogy.families.values():
            lines.extend(self._export_family(family))

        # Trailer
        lines.append("0 TRLR")

        return "\n".join(lines)

    def _generate_header(self) -> list[str]:
        """Génère l'en-tête GEDCOM."""
        lines = []
        lines.append("0 HEAD")
        lines.append("1 GEDC")
        lines.append("2 VERS 5.5.1")
        lines.append("2 FORM LINEAGE-LINKED")
        lines.append("1 CHAR UTF-8")
        lines.append("1 SOUR geneweb-py")
        lines.append("2 VERS 1.0.0")
        lines.append("2 NAME geneweb-py")
        lines.append("2 CORP geneweb-py")
        lines.append("1 DATE")
        lines.append(f"2 TIME {datetime.now().strftime('%H:%M:%S')}")
        lines.append(f"2 DATE {datetime.now().strftime('%d %b %Y')}")
        lines.append("1 FILE")
        lines.append("1 GEDC")
        lines.append("2 VERS 5.5.1")
        lines.append("2 FORM LINEAGE-LINKED")
        return lines

    def _export_person(self, person: Person) -> list[str]:
        """Exporte une personne vers le format GEDCOM."""
        lines = []
        person_id = self._person_ids[person.unique_id]

        lines.append(f"0 @{person_id}@ INDI")

        # Nom
        if person.last_name or person.first_name:
            lines.append("1 NAME")
            name_parts = []
            if person.first_name:
                name_parts.append(person.first_name)
            if person.last_name:
                name_parts.append(f"/{person.last_name}/")
            lines.append(f"2 GIVN {person.first_name or ''}")
            lines.append(f"2 SURN {person.last_name or ''}")

        # Sexe (M / F uniquement si connu ; évite un SEX F erroné pour inconnu)
        if person.gender != Gender.UNKNOWN:
            sex_code = "M" if person.gender == Gender.MALE else "F"
            lines.append(f"1 SEX {sex_code}")

        # Naissance : un seul bloc BIRT (DATE + PLAC au niveau 2)
        has_birt = bool(
            (person.birth_date and person.birth_date.year) or person.birth_place
        )
        has_deat = bool(
            (person.death_date and person.death_date.year) or person.death_place
        )
        if has_birt:
            lines.append("1 BIRT")
            if person.birth_date and person.birth_date.year:
                lines.append(f"2 DATE {self._format_gedcom_date(person.birth_date)}")
            if person.birth_place:
                lines.append(f"2 PLAC {person.birth_place}")

        # Décès : un seul bloc DEAT
        if has_deat:
            lines.append("1 DEAT")
            if person.death_date and person.death_date.year:
                lines.append(f"2 DATE {self._format_gedcom_date(person.death_date)}")
            if person.death_place:
                lines.append(f"2 PLAC {person.death_place}")

        # Titres et professions
        if person.titles:
            for title in person.titles:
                lines.append(f"1 TITL {title.name}")

        if person.occupation:
            lines.append(f"1 OCCU {person.occupation}")

        # Notes
        if person.notes:
            lines.append("1 NOTE")
            for note in person.notes:
                lines.extend(f"2 CONT {text}" for text in self._split_note(note))

        # Événements personnels
        if person.events:
            for event in person.events:
                if not event.event_type:
                    continue
                # Naissance/décès déjà écrits depuis les champs : pas de doublon
                gtag = self._map_event_type(event.event_type.value)
                if (gtag == "BIRT" and has_birt) or (gtag == "DEAT" and has_deat):
                    continue
                lines.extend(self._export_event(event))

        # Liens retour vers les familles (le format les exige des deux côtés)
        lines.extend(
            f"1 FAMS @{fid}@" for fid in self._spouse_families.get(person.unique_id, [])
        )
        lines.extend(
            f"1 FAMC @{fid}@" for fid in self._child_families.get(person.unique_id, [])
        )

        return lines

    def _index_family_links(self, genealogy: Genealogy) -> None:
        """Indexe, par personne, les familles où elle est conjoint (FAMS) ou enfant (FAMC)."""
        self._spouse_families = {}
        self._child_families = {}
        for family in genealogy.families.values():
            fid = self._family_ids[family.family_id]
            for spouse_id in (family.husband_id, family.wife_id):
                if spouse_id:
                    self._spouse_families.setdefault(spouse_id, []).append(fid)
            for child in family.children:
                self._child_families.setdefault(child.person_id, []).append(fid)

    def _export_family(self, family: Family) -> list[str]:
        """Exporte une famille vers le format GEDCOM."""
        lines = []
        family_id = self._family_ids[family.family_id]

        lines.append(f"0 @{family_id}@ FAM")

        # Époux
        husband = self._person_ids.get(family.husband_id or "")
        if husband:
            lines.append(f"1 HUSB @{husband}@")

        # Épouse
        wife = self._person_ids.get(family.wife_id or "")
        if wife:
            lines.append(f"1 WIFE @{wife}@")

        # Enfants
        for child in family.children:
            child_xref = self._person_ids.get(child.person_id)
            if child_xref:
                lines.append(f"1 CHIL @{child_xref}@")

        # Événements familiaux
        for event in family.events:
            event_lines = self._export_event(event, in_family=True)
            lines.extend(event_lines)

        return lines

    def _export_event(self, event: Event, in_family: bool = False) -> list[str]:
        """Exporte un événement vers le format GEDCOM.

        MARR / DIV / ENGA ne sont valides que dans un bloc FAM, et les autres
        balises que dans un INDI ; dans le mauvais contexte, EVEN + TYPE.
        """
        lines = []

        # Mapper les types d'événements GeneWeb vers GEDCOM
        gedcom_type = self._map_event_type(
            event.event_type.value if event.event_type else ""
        )
        # Sans balise dédiée, l'événement devient un EVEN typé (rien n'est perdu)
        generic_type = None
        if gedcom_type and in_family != (gedcom_type in ("MARR", "DIV", "ENGA")):
            gedcom_type = None
        if not gedcom_type and event.event_type:
            gedcom_type = "EVEN"
            generic_type = " ".join(
                (event.event_type_raw or event.event_type.value).split()
            )
        if gedcom_type:
            lines.append(f"1 {gedcom_type}")
            if generic_type:
                lines.append(f"2 TYPE {generic_type}")

            if event.date:
                date_lines = self._export_date(event.date, gedcom_type)
                lines.extend(date_lines)

            if event.place:
                lines.append(f"2 PLAC {event.place}")

            if event.notes:
                for note in event.notes:
                    first, *rest = self._split_note(note)
                    lines.append(f"2 NOTE {first}")
                    lines.extend(f"3 CONT {text}" for text in rest)

        return lines

    @staticmethod
    def _split_note(note: str) -> list[str]:
        """Découpe une note en lignes (une ligne GEDCOM ne contient jamais de saut de ligne)."""
        return note.splitlines() or [""]

    def _export_date(self, date: Date, event_type: str) -> list[str]:
        """Exporte une date vers le format GEDCOM."""
        lines = []

        if date.year:
            gedcom_date = self._format_gedcom_date(date)
            lines.append(f"2 DATE {gedcom_date}")

        return lines

    _GREGORIAN_MONTHS = [
        "",
        "JAN",
        "FEB",
        "MAR",
        "APR",
        "MAY",
        "JUN",
        "JUL",
        "AUG",
        "SEP",
        "OCT",
        "NOV",
        "DEC",
    ]
    # Mois du calendrier républicain ; le 13e (COMP) regroupe les jours complémentaires.
    _FRENCH_REPUBLICAN_MONTHS = [
        "",
        "VEND",
        "BRUM",
        "FRIM",
        "NIVO",
        "PLUV",
        "VENT",
        "GERM",
        "FLOR",
        "PRAI",
        "MESS",
        "THER",
        "FRUC",
        "COMP",
    ]

    # Mois du calendrier hébreu ; le 7e (ADS) est l'Adar II des années embolismiques.
    _HEBREW_MONTHS = [
        "",
        "TSH",
        "CSH",
        "KSL",
        "TVT",
        "SHV",
        "ADR",
        "ADS",
        "NSN",
        "IYR",
        "SVN",
        "TMZ",
        "AAV",
        "ELL",
    ]

    # Échappement GEDCOM et noms de mois des calendriers non grégoriens.
    _CALENDARS = {
        CalendarType.FRENCH_REPUBLICAN: ("@#DFRENCH R@", _FRENCH_REPUBLICAN_MONTHS),
        CalendarType.HEBREW: ("@#DHEBREW@", _HEBREW_MONTHS),
    }

    # Pas d'équivalent GEDCOM à « peut-être » : EST (estimé) est le plus proche.
    # OR porte des dates alternatives que cet export n'écrit pas.
    _GEDCOM_PREFIXES = {
        DatePrefix.ABOUT: "ABT",
        DatePrefix.MAYBE: "EST",
        DatePrefix.BEFORE: "BEF",
        DatePrefix.AFTER: "AFT",
    }

    def _format_gedcom_date(self, date: Date) -> str:
        """Formate une date au format GEDCOM."""
        if date.prefix == DatePrefix.BETWEEN and date.alternative_dates:
            # Le calendrier est porté par la date principale pour les deux bornes.
            start = self._format_date_body(date, date.calendar)
            end = self._format_date_body(date.alternative_dates[0], date.calendar)
            if start and end:
                return f"BET {start} AND {end}"

        prefix_keyword = self._GEDCOM_PREFIXES.get(date.prefix) if date.prefix else None
        body = self._format_date_body(date, date.calendar)
        return f"{prefix_keyword} {body}" if prefix_keyword else body

    def _format_date_body(self, date: Date, calendar: CalendarType) -> str:
        """Formate jour, mois et année, avec l'échappement du calendrier."""
        parts = []

        escape, month_names = self._CALENDARS.get(
            calendar, ("", self._GREGORIAN_MONTHS)
        )
        if escape:
            parts.append(escape)

        if date.day:
            parts.append(str(date.day))
        if date.month:
            parts.append(month_names[date.month])
        if date.year:
            parts.append(str(date.year))

        return " ".join(parts)

    def _map_event_type(self, event_type: str) -> str | None:
        """Mappe un type d'événement GeneWeb vers GEDCOM."""
        mapping = {
            # Noms complets
            "birth": "BIRT",
            "death": "DEAT",
            "marriage": "MARR",
            "divorce": "DIV",
            "baptism": "BAPM",
            "burial": "BURI",
            "confirmation": "CONF",
            "graduation": "GRAD",
            "immigration": "IMMI",
            "emigration": "EMIG",
            "naturalization": "NATU",
            "occupation": "OCCU",
            "residence": "RESI",
            # Valeurs courtes de EventType (ex. EventType.MARRIAGE.value == 'marr')
            "birt": "BIRT",
            "bapt": "BAPM",
            "deat": "DEAT",
            "buri": "BURI",
            "crem": "CREM",
            "conf": "CONF",
            "natu": "NATU",
            "occu": "OCCU",
            "resi": "RESI",
            "educ": "EDUC",
            "grad": "GRAD",
            "marr": "MARR",
            "div": "DIV",
            "immi": "IMMI",
            "emig": "EMIG",
            "cens": "CENS",
            "reti": "RETI",
            "fcom": "FCOM",
            "ordn": "ORDN",
            "barm": "BARM",
            "basm": "BASM",
            "bles": "BLES",
            "will": "WILL",
            "prop": "PROP",
            "enga": "ENGA",
        }
        return mapping.get(event_type.lower())


class GEDCOMImporter(BaseImporter):
    """Importeur GEDCOM (5.5 / 5.5.1) vers les modèles geneweb-py.

    Périmètre supporté : ``HEAD``, ``INDI``, ``FAM`` avec ``DATE``, ``NOTE``,
    ``CONT`` / ``CONC``, pointeurs ``@xref@`` ou identifiants plats (``I0001``).
    Hors périmètre : ``OBJE``, ``SOUR`` structuré, extensions logicielles.
    """

    _GEDCOM_MONTHS: dict[str, int] = {
        "JAN": 1,
        "FEB": 2,
        "MAR": 3,
        "APR": 4,
        "MAY": 5,
        "JUN": 6,
        "JUL": 7,
        "AUG": 8,
        "SEP": 9,
        "OCT": 10,
        "NOV": 11,
        "DEC": 12,
    }

    _GEDCOM_TAG_TO_EVENT: dict[str, EventType] = {
        "BIRT": EventType.BIRTH,
        "DEAT": EventType.DEATH,
        "BAPM": EventType.BAPTISM,
        "BURI": EventType.BURIAL,
        "CONF": EventType.CONFIRMATION,
        "GRAD": EventType.GRADUATION,
        "NATU": EventType.NATURALIZATION,
        "OCCU": EventType.OCCUPATION,
        "RESI": EventType.RESIDENCE,
        "EDUC": EventType.EDUCATION,
        "IMMI": EventType.IMMIGRATION,
        "EMIG": EventType.EMIGRATION,
        "CENS": EventType.RECENSEMENT,
        "RETI": EventType.RETIREMENT,
        "FCOM": EventType.FIRST_COMMUNION,
        "ORDN": EventType.ORDINATION,
        "BARM": EventType.BAR_MITZVAH,
        "BASM": EventType.BAT_MITZVAH,
        "BLES": EventType.BENEDICTION,
        "WILL": EventType.WILL,
        "PROP": EventType.PROPERTY,
        "CREM": EventType.CREMATION,
    }

    def __init__(self, encoding: str = "utf-8") -> None:
        super().__init__(encoding)
        self._xref_to_uid: dict[str, str] = {}
        self._xref_to_family_id: dict[str, str] = {}
        self._pending_spouse_fams: dict[str, list[str]] = {}
        self._pending_child_fams: dict[str, list[str]] = {}

    @staticmethod
    def _normalize_xref_key(token: str) -> str:
        t = token.strip()
        if t.startswith("@") and t.endswith("@") and len(t) > 2:
            return t[1:-1]
        return t

    def _decode_file_bytes(self, raw_data: bytes) -> tuple[str, str]:
        try:
            return raw_data.decode("utf-8"), "utf-8"
        except UnicodeDecodeError:
            pass
        sample = raw_data[:8192]
        result = chardet.detect(sample)
        detected = result.get("encoding") or "iso-8859-1"
        confidence = float(result.get("confidence") or 0.0)
        if confidence >= 0.7 and detected:
            try:
                return raw_data.decode(detected), detected
            except (UnicodeDecodeError, LookupError):
                pass
        try:
            return raw_data.decode("iso-8859-1"), "iso-8859-1"
        except UnicodeDecodeError:
            enc = detected or "utf-8"
            return raw_data.decode(enc, errors="replace"), enc

    def import_from_file(self, input_path: str | Path) -> Genealogy:
        path = self._validate_file_path(input_path)
        try:
            with open(path, "rb") as f:
                raw = f.read()
        except OSError as exc:
            raise ConversionError(
                f"Impossible de lire le fichier GEDCOM : {exc}",
                context=str(path),
                source_format="GEDCOM",
            ) from exc
        text, used_enc = self._decode_file_bytes(raw)
        genealogy = self.import_from_string(text)
        genealogy.metadata.encoding = used_enc
        genealogy.metadata.source_file = str(path)
        return genealogy

    def import_from_string(self, data: str) -> Genealogy:
        try:
            self._xref_to_uid.clear()
            self._xref_to_family_id.clear()
            self._pending_spouse_fams.clear()
            self._pending_child_fams.clear()

            tokens = self._non_empty_lines(data)
            blocks = self._split_level_zero_blocks(tokens)
            genealogy = Genealogy()

            indi_blocks: list[tuple[str, list[tuple[int, str]]]] = []
            fam_blocks: list[tuple[str, list[tuple[int, str]]]] = []

            for block in blocks:
                if not block:
                    continue
                ln0, raw0 = block[0]
                parsed = self._try_parse_line(raw0, ln0)
                if parsed is None:
                    continue
                _lv, xref0, tag0, _val0 = parsed
                if tag0 == "HEAD":
                    self._apply_head_block(genealogy, block)
                elif tag0 == "INDI":
                    if not xref0:
                        continue
                    key = self._normalize_xref_key(xref0)
                    indi_blocks.append((key, block))
                elif tag0 == "FAM":
                    if not xref0:
                        continue
                    key = self._normalize_xref_key(xref0)
                    fam_blocks.append((key, block))

            for xref_key, block in indi_blocks:
                self._import_indi_block(xref_key, block, genealogy)

            for xref_key, block in fam_blocks:
                self._import_fam_block(xref_key, block, genealogy)

            self._resolve_family_pointers(genealogy)
            genealogy._update_cross_references()
            return genealogy
        except ConversionError:
            raise
        except Exception as exc:
            raise ConversionError(
                f"Erreur lors du parsing GEDCOM : {exc}",
                source_format="GEDCOM",
            ) from exc

    def _non_empty_lines(self, data: str) -> list[tuple[int, str]]:
        out: list[tuple[int, str]] = []
        for i, raw in enumerate(data.splitlines(), start=1):
            s = raw.strip()
            if s:
                out.append((i, raw.rstrip("\r")))
        return out

    def _try_parse_line(
        self, raw: str, line_number: int
    ) -> tuple[int, str | None, str, str] | None:
        try:
            return self._parse_line(raw, line_number)
        except ConversionError:
            return None

    def _split_level_zero_blocks(
        self, tokens: list[tuple[int, str]]
    ) -> list[list[tuple[int, str]]]:
        blocks: list[list[tuple[int, str]]] = []
        n = len(tokens)
        i = 0
        while i < n:
            ln, raw = tokens[i]
            p = self._try_parse_line(raw, ln)
            if p is None or p[0] != 0:
                i += 1
                continue
            start = i
            i += 1
            while i < n:
                ln2, raw2 = tokens[i]
                p2 = self._try_parse_line(raw2, ln2)
                if p2 is not None and p2[0] == 0:
                    break
                i += 1
            blocks.append(tokens[start:i])
        return blocks

    def _parse_line(
        self, raw: str, line_number: int
    ) -> tuple[int, str | None, str, str]:
        s = raw.strip()
        if not s:
            raise ConversionError(
                "Ligne GEDCOM vide",
                line_number=line_number,
                context=raw,
                source_format="GEDCOM",
            )
        head, sep, rest = s.partition(" ")
        if not head.isdigit():
            raise ConversionError(
                "Niveau GEDCOM invalide (attendu un entier)",
                line_number=line_number,
                context=raw,
                source_format="GEDCOM",
            )
        level = int(head)
        rest = rest.strip()
        record_xref: str | None = None
        if level == 0:
            if rest.startswith("@"):
                end = rest.find("@", 1)
                if end == -1:
                    raise ConversionError(
                        "Pointeur GEDCOM non terminé",
                        line_number=line_number,
                        context=raw,
                        source_format="GEDCOM",
                    )
                inner = rest[1:end]
                tail = rest[end + 1 :].strip()
                parts = tail.split(None, 1)
                tag = parts[0]
                value = parts[1] if len(parts) > 1 else ""
                record_xref = inner
                return level, record_xref, tag, value
            parts = rest.split()
            if len(parts) >= 2 and parts[1] in ("INDI", "FAM"):
                record_xref = parts[0]
                tag = parts[1]
                value = " ".join(parts[2:])
                return level, record_xref, tag, value
            if not parts:
                raise ConversionError(
                    "Enregistrement de niveau 0 vide",
                    line_number=line_number,
                    context=raw,
                    source_format="GEDCOM",
                )
            tag = parts[0]
            value = " ".join(parts[1:])
            return level, None, tag, value
        if not rest:
            raise ConversionError(
                "Ligne GEDCOM sans balise",
                line_number=line_number,
                context=raw,
                source_format="GEDCOM",
            )
        rp = rest.split(None, 1)
        tag = rp[0]
        value = rp[1] if len(rp) > 1 else ""
        return level, None, tag, value

    def _apply_head_block(
        self, genealogy: Genealogy, block: list[tuple[int, str]]
    ) -> None:
        notes: list[str] = []
        for ln, raw in block[1:]:
            p = self._try_parse_line(raw, ln)
            if p is None:
                continue
            _lv, _xr, tg, val = p
            if tg == "CHAR" and val:
                genealogy.metadata.encoding = val.strip()
            elif tg == "SOUR" and val:
                notes.append(f"SOUR {val}")
        if notes:
            genealogy.metadata.database_notes.extend(notes)

    def _parse_gedcom_date(self, value: str, line_number: int) -> Date | None:
        if not value or not value.strip():
            return None
        tokens = value.strip().split()
        if not tokens:
            return None
        prefix_map = {
            "ABT": DatePrefix.ABOUT,
            "ABOUT": DatePrefix.ABOUT,
            "EST": DatePrefix.ABOUT,
            "CAL": DatePrefix.ABOUT,
            "BEF": DatePrefix.BEFORE,
            "BEFORE": DatePrefix.BEFORE,
            "AFT": DatePrefix.AFTER,
            "AFTER": DatePrefix.AFTER,
        }
        prefix: DatePrefix | None = None
        if tokens[0] in prefix_map:
            prefix = prefix_map[tokens[0]]
            tokens = tokens[1:]
        if not tokens:
            return None
        if tokens[0] == "BET":
            return self._parse_gedcom_between(tokens[1:], line_number)
        calendar = CalendarType.GREGORIAN
        months = self._GEDCOM_MONTHS
        for candidate, (escape, names) in GEDCOMExporter._CALENDARS.items():
            escape_tokens = escape.split()
            if tokens[: len(escape_tokens)] == escape_tokens:
                calendar = candidate
                months = {name: number for number, name in enumerate(names) if name}
                tokens = tokens[len(escape_tokens) :]
                break
        if not tokens:
            return None
        day: int | None = None
        month: int | None = None
        year: int | None = None
        if len(tokens) == 1:
            if tokens[0].isdigit():
                year = int(tokens[0])
        elif len(tokens) == 2:
            mkey = tokens[0].upper()
            if mkey in months and tokens[1].isdigit():
                month = months[mkey]
                year = int(tokens[1])
            elif tokens[0].isdigit() and tokens[1].isdigit():
                day = int(tokens[0])
                month = int(tokens[1])
        elif len(tokens) >= 3:
            if tokens[0].isdigit():
                day = int(tokens[0])
            mkey = tokens[1].upper()
            if mkey in months:
                month = months[mkey]
            if tokens[2].isdigit():
                year = int(tokens[2])
        try:
            return Date(
                day=day, month=month, year=year, prefix=prefix, calendar=calendar
            )
        except ValueError as exc:
            raise ConversionError(
                f"Date GEDCOM invalide : {value!r}",
                line_number=line_number,
                context=value,
                source_format="GEDCOM",
            ) from exc

    def _parse_gedcom_between(self, tokens: list[str], line_number: int) -> Date | None:
        """Lit ``<date> AND <date>`` : la borne de fin va dans ``alternative_dates``."""
        if "AND" not in tokens:
            return None
        cut = tokens.index("AND")
        start = self._parse_gedcom_date(" ".join(tokens[:cut]), line_number)
        end = self._parse_gedcom_date(" ".join(tokens[cut + 1 :]), line_number)
        if start is None or end is None:
            return None
        # Le calendrier reste porté par la date principale (cf. Date.parse).
        end.calendar = CalendarType.GREGORIAN
        start.prefix = DatePrefix.BETWEEN
        start.alternative_dates = [end]
        return start

    def _parse_note_payload(
        self, block: list[tuple[int, str]], start: int, base_level: int
    ) -> tuple[str, int]:
        ln, raw = block[start]
        _lv, _xr, _tg, first = self._parse_line(raw, ln)
        parts: list[str] = []
        if first:
            parts.append(first)
        i = start + 1
        while i < len(block):
            ln2, raw2 = block[i]
            lv, _xr2, tg2, va2 = self._parse_line(raw2, ln2)
            if lv <= base_level:
                break
            if tg2 == "CONT":
                parts.append("\n" + (va2 or ""))
                i += 1
            elif tg2 == "CONC":
                parts.append(va2 or "")
                i += 1
            else:
                break
        return "".join(parts).strip(), i

    def _parse_name_payload(
        self, block: list[tuple[int, str]], start: int
    ) -> tuple[str, str, int]:
        givn = ""
        surn = ""
        i = start
        while i < len(block):
            ln, raw = block[i]
            lv, _xr, tg, va = self._parse_line(raw, ln)
            if lv <= 1:
                break
            if tg == "GIVN":
                givn = va or givn
            elif tg == "SURN":
                surn = va or surn
            i += 1
        return givn, surn, i

    def _slash_name_parts(self, payload: str) -> tuple[str, str]:
        if "/" in payload:
            chunks = payload.split("/")
            if len(chunks) >= 3:
                first = chunks[0].strip()
                last = chunks[1].strip()
                return last or "?", first or "?"
        return "", payload.strip()

    def _parse_event_payload(
        self, block: list[tuple[int, str]], start: int, tag_expected: str
    ) -> tuple[dict[str, Any], int]:
        ln0, raw0 = block[start]
        lv0, _xr0, tg0, _v0 = self._parse_line(raw0, ln0)
        if tg0 != tag_expected:
            return {"date": None, "place": None, "notes": [], "type": None}, start + 1
        date_v: Date | None = None
        place_v: str | None = None
        type_v: str | None = None
        notes_acc: list[str] = []
        i = start + 1
        while i < len(block):
            ln, raw = block[i]
            lv, _xr, tg, va = self._parse_line(raw, ln)
            if lv <= 1:
                break
            if tg == "DATE":
                date_v = self._parse_gedcom_date(va, ln) or date_v
                i += 1
            elif tg == "PLAC":
                place_v = va or place_v
                i += 1
            elif tg == "TYPE" and lv == 2:
                type_v = va or type_v
                i += 1
            elif tg == "NOTE":
                text, j = self._parse_note_payload(block, i, lv)
                if text:
                    notes_acc.append(text)
                i = j
            else:
                i += 1
        return {
            "date": date_v,
            "place": place_v,
            "notes": notes_acc,
            "type": type_v,
        }, i

    @staticmethod
    def _resolve_generic_event_type(
        type_value: str | None,
    ) -> tuple[EventType, str | None]:
        """Type d'un EVEN : code EventType connu, sinon libellé libre (OTHER)."""
        if type_value:
            for event_type in EventType:
                if event_type.value == type_value and event_type != EventType.OTHER:
                    return event_type, None
        return EventType.OTHER, type_value or None

    def _allocate_person(
        self, last_name: str, first_name: str, genealogy: Genealogy
    ) -> Person:
        last = (last_name or "?").strip() or "?"
        first = (first_name or "?").strip() or "?"
        occ = 0
        while True:
            candidate = Person(last_name=last, first_name=first, occurrence_number=occ)
            uid = candidate.unique_id
            if uid not in genealogy.persons:
                return candidate
            occ += 1

    def _import_indi_block(
        self,
        xref_key: str,
        block: list[tuple[int, str]],
        genealogy: Genealogy,
    ) -> None:
        if xref_key in self._xref_to_uid:
            ln0, _ = block[0]
            raise ConversionError(
                f"Référence INDI dupliquée : {xref_key!r}",
                line_number=ln0,
                source_format="GEDCOM",
            )
        givn = ""
        surn = ""
        gender = Gender.UNKNOWN
        birth_date: Date | None = None
        death_date: Date | None = None
        birth_place: str | None = None
        death_place: str | None = None
        notes: list[str] = []
        fams_raw: list[str] = []
        famc_raw: list[str] = []
        extra_events: list[PersonalEvent] = []
        titles: list[Title] = []
        occupation: str | None = None

        i = 1
        while i < len(block):
            ln, raw = block[i]
            level, _xr, tag, val = self._parse_line(raw, ln)
            if level != 1:
                i += 1
                continue
            if tag == "NAME":
                g, s, ni = self._parse_name_payload(block, i + 1)
                if g:
                    givn = g
                if s:
                    surn = s
                if not givn and not surn and val:
                    sl, sf = self._slash_name_parts(val)
                    if sl:
                        surn = sl
                    if sf:
                        givn = sf
                i = ni
                continue
            if tag == "SEX":
                if val.strip().upper() == "M":
                    gender = Gender.MALE
                elif val.strip().upper() == "F":
                    gender = Gender.FEMALE
                else:
                    gender = Gender.UNKNOWN
                i += 1
                continue
            if tag in ("BIRT", "DEAT"):
                payload, ni = self._parse_event_payload(block, i, tag)
                if tag == "BIRT":
                    if payload.get("date") and birth_date is None:
                        birth_date = payload["date"]
                    if payload.get("place"):
                        birth_place = birth_place or payload["place"]
                    for nt in payload.get("notes", []):
                        notes.append(nt)
                else:
                    if payload.get("date") and death_date is None:
                        death_date = payload["date"]
                    if payload.get("place"):
                        death_place = death_place or payload["place"]
                    for nt in payload.get("notes", []):
                        notes.append(nt)
                i = ni
                continue
            if tag == "NOTE":
                text, j = self._parse_note_payload(block, i, 1)
                if text:
                    notes.append(text)
                i = j
                continue
            if tag == "FAMS":
                fams_raw.append(self._normalize_xref_key(val))
                i += 1
                continue
            if tag == "FAMC":
                famc_raw.append(self._normalize_xref_key(val))
                i += 1
                continue
            if tag == "TITL" and val:
                titles.append(Title(name=val))
                i += 1
                continue
            if tag == "OCCU" and val:
                occupation = val
                i += 1
                continue
            et = self._GEDCOM_TAG_TO_EVENT.get(tag)
            raw_type: str | None = None
            if tag == "EVEN":
                payload, ni = self._parse_event_payload(block, i, tag)
                et, raw_type = self._resolve_generic_event_type(payload.get("type"))
            if et is not None:
                if tag != "EVEN":
                    payload, ni = self._parse_event_payload(block, i, tag)
                meta: dict[str, str] = {}
                if tag in ("IMMI", "EMIG"):
                    meta["gedcom_tag"] = tag
                ev = PersonalEvent(
                    event_type=et,
                    event_type_raw=raw_type,
                    date=payload.get("date"),
                    place=payload.get("place"),
                    notes=list(payload.get("notes") or []),
                    metadata=meta,
                )
                extra_events.append(ev)
                i = ni
                continue
            i += 1

        person = self._allocate_person(surn, givn, genealogy)
        person.gender = gender
        person.birth_date = birth_date
        person.death_date = death_date
        person.birth_place = birth_place
        person.death_place = death_place
        person.notes.extend(notes)
        person.titles.extend(titles)
        person.occupation = occupation or person.occupation
        for ev in extra_events:
            person.add_event(ev)

        genealogy.add_person(person)
        uid = person.unique_id
        self._xref_to_uid[xref_key] = uid
        if fams_raw:
            self._pending_spouse_fams[uid] = fams_raw
        if famc_raw:
            self._pending_child_fams[uid] = famc_raw

    def _resolve_person_pointer(self, raw: str, genealogy: Genealogy) -> str:
        key = self._normalize_xref_key(raw)
        if key in self._xref_to_uid:
            return self._xref_to_uid[key]
        if key in genealogy.persons:
            return key
        return key

    def _import_fam_block(
        self,
        xref_key: str,
        block: list[tuple[int, str]],
        genealogy: Genealogy,
    ) -> None:
        family_id = xref_key
        if family_id in genealogy.families:
            ln0, _ = block[0]
            raise ConversionError(
                f"Référence FAM dupliquée : {family_id!r}",
                line_number=ln0,
                source_format="GEDCOM",
            )
        husband_id: str | None = None
        wife_id: str | None = None
        children: list[Child] = []
        marriage_date: Date | None = None
        marriage_place: str | None = None
        divorce_date: Date | None = None
        fam_notes: list[str] = []
        fam_events: list[FamilyEvent] = []

        i = 1
        while i < len(block):
            ln, raw = block[i]
            level, _xr, tag, val = self._parse_line(raw, ln)
            if level != 1:
                i += 1
                continue
            if tag == "HUSB":
                husband_id = self._resolve_person_pointer(val, genealogy)
                i += 1
                continue
            if tag == "WIFE":
                wife_id = self._resolve_person_pointer(val, genealogy)
                i += 1
                continue
            if tag == "CHIL":
                cid = self._resolve_person_pointer(val, genealogy)
                children.append(Child(person_id=cid, sex=ChildSex.UNKNOWN))
                i += 1
                continue
            if tag == "MARR":
                payload, ni = self._parse_event_payload(block, i, "MARR")
                marriage_date = payload.get("date")
                marriage_place = payload.get("place")
                for nt in payload.get("notes", []):
                    fam_notes.append(nt)
                fe = FamilyEvent(
                    event_type=EventType.MARRIAGE,
                    family_event_type=FamilyEventType.MARRIAGE,
                    date=marriage_date,
                    place=marriage_place,
                    notes=list(payload.get("notes") or []),
                )
                fam_events.append(fe)
                i = ni
                continue
            if tag == "DIV":
                payload, ni = self._parse_event_payload(block, i, "DIV")
                divorce_date = payload.get("date")
                for nt in payload.get("notes", []):
                    fam_notes.append(nt)
                fe = FamilyEvent(
                    event_type=EventType.DIVORCE,
                    family_event_type=FamilyEventType.DIVORCE,
                    date=divorce_date,
                    notes=list(payload.get("notes") or []),
                )
                fam_events.append(fe)
                i = ni
                continue
            if tag in ("ENGA", "EVEN"):
                payload, ni = self._parse_event_payload(block, i, tag)
                if tag == "ENGA":
                    fam_type, fam_raw = EventType.ENGAGEMENT, None
                else:
                    fam_type, fam_raw = self._resolve_generic_event_type(
                        payload.get("type")
                    )
                fam_events.append(
                    FamilyEvent(
                        event_type=fam_type,
                        event_type_raw=fam_raw,
                        date=payload.get("date"),
                        place=payload.get("place"),
                        notes=list(payload.get("notes") or []),
                    )
                )
                i = ni
                continue
            if tag == "NOTE":
                text, j = self._parse_note_payload(block, i, 1)
                if text:
                    fam_notes.append(text)
                i = j
                continue
            i += 1

        family = Family(
            family_id=family_id,
            husband_id=husband_id,
            wife_id=wife_id,
            marriage_date=marriage_date,
            marriage_place=marriage_place,
            divorce_date=divorce_date,
            marriage_status=MarriageStatus.MARRIED,
            children=children,
            events=fam_events,
            comments=fam_notes,
        )
        genealogy.add_family(family)
        self._xref_to_family_id[xref_key] = family_id

    def _resolve_family_pointers(self, genealogy: Genealogy) -> None:
        for uid, fam_keys in self._pending_spouse_fams.items():
            person = genealogy.persons.get(uid)
            if not person:
                continue
            for fk in fam_keys:
                fid = self._xref_to_family_id.get(fk, fk)
                if fid in genealogy.families and fid not in person.families_as_spouse:
                    person.families_as_spouse.append(fid)
        for uid, fam_keys in self._pending_child_fams.items():
            person = genealogy.persons.get(uid)
            if not person:
                continue
            for fk in fam_keys:
                fid = self._xref_to_family_id.get(fk, fk)
                if fid in genealogy.families and fid not in person.families_as_child:
                    person.families_as_child.append(fid)
