"""Parser wikitext GeneWeb pour les blocs notes."""

import re
from dataclasses import dataclass, field


@dataclass
class PersonLink:
    """Lien vers une personne dans une note wikitext GeneWeb."""

    first_name: str
    last_name: str
    occurrence: int = 0
    display_text: str = ""


@dataclass
class PageLink:
    """Lien vers une page étendue GeneWeb dans une note wikitext."""

    page_name: str
    display_text: str = ""


@dataclass
class WizardLink:
    """Lien vers un magicien GeneWeb dans une note wikitext."""

    wizard_name: str
    display_text: str = ""


@dataclass
class FicheTags:
    """Balises de renvoi sur fiche individu GeneWeb. Last-write-wins sur duplicates."""

    head: str | None = None
    occu: str | None = None
    death: str | None = None
    biblio: str | None = None
    bnote: str | None = None
    note: str | None = None


@dataclass
class NoteContent:
    """Contenu structuré d'une note wikitext GeneWeb."""

    raw: str
    person_links: list[PersonLink] = field(default_factory=list)
    page_links: list[PageLink] = field(default_factory=list)
    wizard_links: list[WizardLink] = field(default_factory=list)
    fiche_tags: FicheTags = field(default_factory=FicheTags)


class WikitextParser:
    """Extrait les métadonnées structurées d'une note wikitext GeneWeb.

    Conserve le texte brut tel quel (raw). Extraction par regex via finditer
    avec déduplication par position pour éviter les chevauchements.

    Formats supportés :
    - Lien personne : [[FirstName/LastName/occurrence/DisplayText]]
    - Lien page : [[[page_name/DisplayText]]]
    - Lien magicien : [[w:WizardName/DisplayText]]
    - Balises fiche : HEAD=..., OCCU=..., BIBLIO=..., etc.

    Limitation v1 : les séquences d'échappement %[ et %] ne sont pas
    pré-traitées avant le matching — les liens dans des séquences échappées
    pourraient produire de faux positifs.
    """

    # Patterns compilés au niveau classe (une seule compilation)
    _PAGE_LINK = re.compile(r"\[\[\[([^/\]\[]+)(?:/([^\]\[]*))?\]\]\]")
    _WIZARD_LINK = re.compile(r"\[\[w:([^/\]\[]+)(?:/([^\]\[]*))?\]\]")
    _PERSON_LINK = re.compile(
        r"\[\[(?!w:)([^/\]\[]+)/([^/\]\[]+)(?:/(\d*))?(?:/([^\]\[]*))?\]\]"
    )
    _FICHE_TAG = re.compile(r"^(HEAD|OCCU|DEATH|BIBLIO|BNOTE|NOTE)=(.*)$", re.MULTILINE)

    def parse(self, raw: str) -> NoteContent:
        """Parse une note brute et retourne un NoteContent structuré.

        Args:
            raw: Texte brut original de la note

        Returns:
            NoteContent avec liens et balises extraits
        """
        note = NoteContent(raw=raw)

        # Collecter tous les matches avec positions, par priorité décroissante
        # (PAGE_LINK avant WIZARD_LINK avant PERSON_LINK)
        candidates: list[tuple[int, int, str, re.Match]] = []
        for pattern, kind in [
            (self._PAGE_LINK, "page"),
            (self._WIZARD_LINK, "wizard"),
            (self._PERSON_LINK, "person"),
        ]:
            for m in pattern.finditer(raw):
                candidates.append((m.start(), m.end(), kind, m))

        # Trier par position de début ; à position égale, garder l'ordre de priorité
        candidates.sort(key=lambda x: x[0])

        # Dédupliquer : ignorer tout match qui chevauche un match déjà accepté
        used_end = -1
        for start, end, kind, m in candidates:
            if start < used_end:
                continue  # chevauchement — ignorer
            used_end = end

            if kind == "page":
                note.page_links.append(
                    PageLink(
                        page_name=m.group(1),
                        display_text=m.group(2) or "",
                    )
                )
            elif kind == "wizard":
                note.wizard_links.append(
                    WizardLink(
                        wizard_name=m.group(1),
                        display_text=m.group(2) or "",
                    )
                )
            else:  # person
                occ_str = m.group(3) or "0"
                note.person_links.append(
                    PersonLink(
                        first_name=m.group(1),
                        last_name=m.group(2),
                        occurrence=int(occ_str) if occ_str else 0,
                        display_text=m.group(4) or "",
                    )
                )

        # Extraire les balises de fiche (last-write-wins)
        for m in self._FICHE_TAG.finditer(raw):
            tag = m.group(1).lower()
            value = m.group(2).strip()
            setattr(note.fiche_tags, tag, value)

        return note
