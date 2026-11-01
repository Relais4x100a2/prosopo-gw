"""Lecture par mots bruts d'une ligne GeneWeb, comme ``gwc`` (``gwcomp.ml``).

Une ligne ``.gw`` est une suite de mots séparés par des espaces : dans un mot,
``_`` tient lieu d'espace et ``\\x`` protège le caractère ``x``. Lire la ligne brute
mot à mot évite de recoller les jetons du lexeur, qui découpe les mots contenant
``/ : ( ) " -`` ou des chiffres (``3_E_041/472``, ``<a_href="…">``).
"""

import re
from dataclasses import dataclass, field
from typing import Callable, List, Optional, Sequence, Tuple

_MOT = re.compile(r"[^ \t]+")

# Relations de la partie mariage (``get_mar_date``) ; ``nm`` / ``eng`` sans code
# de sexe, les autres suivies d'un code facultatif (``mf``, ``ff``, ``m?``…)
RELATIONS_SANS_CODE = ("nm", "eng")
RELATIONS_AVEC_CODE = (
    "noment",
    "nsck",
    "nsckm",
    "banns",
    "contract",
    "license",
    "pacs",
    "residence",
)
_CHAMPS = {"#mp": "place", "#mn": "note", "#ms": "source"}


def split_words(line: str) -> List[str]:
    """Mots bruts d'une ligne (séparateurs : espaces et tabulations, répétés ou non)."""
    return _MOT.findall(line)


def word_spans(line: str) -> List[Tuple[str, int]]:
    """Mots bruts d'une ligne, chacun avec sa position de début dans ``line``."""
    return [(m.group(), m.start()) for m in _MOT.finditer(line)]


def decode_word(word: str) -> str:
    """Valeur d'un mot (``copy_decode`` de gwc) : ``_`` → espace, ``\\x`` → ``x``."""
    out: List[str] = []
    i = 0
    n = len(word)
    while i < n:
        c = word[i]
        if c == "\\" and i + 1 < n:
            out.append(word[i + 1])
            i += 2
            continue
        out.append(" " if c == "_" else c)
        i += 1
    return "".join(out)


def cut_space(text: str) -> str:
    """Retire une espace en tête et une en fin (``cut_space`` de gwc)."""
    if text == " ":
        return ""
    debut = 1 if text.startswith(" ") else 0
    fin = len(text) - 1 if text.endswith(" ") else len(text)
    return text[debut:fin] if fin > debut else ""


def is_sex_code(word: str) -> bool:
    """Code des sexes des conjoints après une relation : deux lettres parmi ``m f ?``."""
    return len(word) == 2 and all(c in "mf?" for c in word)


@dataclass
class MarriagePart:
    """Partie mariage d'une ligne ``fam``, mots bruts (non décodés).

    ``date`` est le texte qui suit ``+`` (``None`` pour ``+`` seul) ; ``relations``
    garde l'ordre de lecture (``nm``, ``eng``, ``noment``…) ; ``sexes`` est le code
    brut (``mf``…) de la dernière relation qui en avait un.
    """

    date: Optional[str] = None
    relations: List[str] = field(default_factory=list)
    sexes: Optional[str] = None
    place: Optional[str] = None
    note: Optional[str] = None
    source: Optional[str] = None
    divorced: bool = False
    divorce_date: Optional[str] = None
    separated: bool = False
    separation_date: Optional[str] = None


def _jamais(_: int) -> bool:
    return False


def read_marriage_part(
    words: Sequence[str],
    start: int = 0,
    is_date: Callable[[int], bool] = _jamais,
) -> Tuple[MarriagePart, int]:
    """Lit la partie mariage qui commence au mot ``+[date]`` d'index ``start``.

    Grammaire de ``get_mar_date`` (gwc) : ``+[date]``, relation et code de sexe,
    ``#mp``, ``#mn``, ``#ms`` (un mot chacun), puis ``-[date]`` ou ``#sep``. Les
    marqueurs sont acceptés dans n'importe quel ordre, une relation sans code de
    sexe aussi. Tolérances historiques du parser, que gwc refuse : date détachée
    après ``+``, ``-``, ``#sep`` ou ``#div`` (``is_date(k)`` dit si le mot ``k`` en
    est une) et ``-`` seul après ``#sep`` / ``#div`` (date absente).

    Returns:
        (partie mariage, index du premier mot qui n'en fait pas partie : l'épouse)

    Raises:
        ValueError: si le mot ``start`` ne commence pas par ``+``.
    """
    n = len(words)
    if start >= n or not words[start].startswith("+"):
        raise ValueError("la partie mariage commence par un mot « + »")
    part = MarriagePart(date=words[start][1:] or None)
    k = start + 1
    if part.date is None and k < n and is_date(k):
        part.date = words[k]
        k += 1

    def date_detachee(k_: int) -> Tuple[Optional[str], int]:
        if k_ < n and is_date(k_):
            return words[k_], k_ + 1
        return None, k_

    while k < n:
        mot = words[k]
        tag = mot[1:] if mot.startswith("#") else None
        if tag in RELATIONS_SANS_CODE:
            part.relations.append(tag)
            k += 1
        elif tag in RELATIONS_AVEC_CODE:
            part.relations.append(tag)
            k += 1
            if k < n and is_sex_code(words[k]):
                part.sexes = words[k]
                k += 1
        elif mot in _CHAMPS:
            if k + 1 < n:
                setattr(part, _CHAMPS[mot], words[k + 1])
            k += 2
        elif mot.startswith("-"):
            part.divorced = True
            part.divorce_date = mot[1:] or None
            k += 1
            if part.divorce_date is None:
                part.divorce_date, k = date_detachee(k)
        elif mot in ("#sep", "#div"):
            k += 1
            date: Optional[str] = None
            if k < n and words[k] == "-":
                k += 1
            else:
                date, k = date_detachee(k)
            if mot == "#sep":
                part.separated = True
                part.separation_date = date
            else:
                part.divorced = True
                part.divorce_date = date
        else:
            break
    return part, min(k, n)
