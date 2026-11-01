"""
Parser lexical pour les fichiers .gw

Ce module implémente la tokenisation des fichiers GeneWeb (.gw) en identifiant
tous les tokens du format : blocs, mots-clés, identifiants, dates, etc.
"""

import re
from dataclasses import dataclass
from enum import Enum
from functools import lru_cache
from typing import Iterator, List, Optional, Pattern

from ..exceptions import GeneWebParseError

# Mot fait uniquement de « ? » (nom/prénom inconnu), suivi d'un blanc, de la fin
# ou d'un numéro d'occurrence ``.N`` : ce n'est pas une date (``?1950``).
_QUESTION_WORD = re.compile(r"\?+(?=\s|$|\.\d)")

# Limites contre l'abus de ressources (commentaires bloc non fermés, etc.)
_BLOCK_COMMENT_BODY_MAX_CHARS = 256 * 1024


class TokenType(Enum):
    """Types de tokens dans le format .gw"""

    # Blocs principaux
    FAM = "fam"  # Bloc famille
    NOTES = "notes"  # Bloc notes personnelles
    REL = "rel"  # Bloc relations
    PEVT = "pevt"  # Bloc événements personnels (gwplus)
    FEVT = "fevt"  # Bloc événements familiaux (gwplus)
    NOTES_DB = "notes-db"  # Bloc notes de base de données
    PAGE_EXT = "page-ext"  # Bloc pages étendues
    WIZARD_NOTE = "wizard-note"  # Bloc notes de wizard

    # Mots-clés de structure
    BEG = "beg"  # Début de bloc
    END = "end"  # Fin de bloc
    END_NOTES = "end notes"  # Fin de notes
    END_PEVT = "end pevt"  # Fin événements personnels
    END_FEVT = "end fevt"  # Fin événements familiaux
    END_NOTES_DB = "end notes-db"  # Fin notes de base
    END_PAGE_EXT = "end page-ext"  # Fin page étendue
    END_WIZARD_NOTE = "end wizard-note"  # Fin note wizard

    # Mots-clés de données
    WIT = "wit"  # Témoin
    WNOTE = "wnote"  # Note de témoin (witness note)
    SRC = "src"  # Source
    COMM = "comm"  # Commentaire
    CBP = "cbp"  # Common birth place
    CSRC = "csrc"  # Common children source
    BEG_FAMILY = "beg"  # Début famille (dans fam)
    END_FAMILY = "end"  # Fin famille (dans fam)

    # Modificateurs de lieu
    BP = "bp"  # Birth place
    DP = "dp"  # Death place
    MP = "mp"  # Marriage place
    P = "p"  # Place (générique)
    S = "s"  # Source (générique)

    # Modificateurs de statut
    NM = "nm"  # Non marié
    ENG = "eng"  # Fiancé
    SEP = "sep"  # Séparé
    DIV = "div"  # Divorcé

    # Modificateurs de sexe
    H = "h"  # Masculin
    F = "f"  # Féminin

    # Modificateurs d'accès
    APUBL = "apubl"  # Accès public
    APRIV = "apriv"  # Accès privé

    # Occupation
    OCCU = "occu"  # Occupation

    # Notes
    NOTE = "note"  # Note personnelle

    # Modificateurs de décès
    OD = "od"  # Obviously dead
    MJ = "mj"  # Mort jeune

    # Modificateurs d'inhumation
    BURI = "buri"  # Inhumation
    CREM = "crem"  # Crémation

    # Types d'événements (pevt/fevt)
    BIRT = "birt"  # Naissance
    BAPT = "bapt"  # Baptême
    DEAT = "deat"  # Décès
    BURI_EVENT = "buri"  # Inhumation (événement)
    CREM_EVENT = "crem"  # Crémation (événement)
    MARR = "marr"  # Mariage
    DIV_EVENT = "div"  # Divorce (événement)
    SEP_EVENT = "sep"  # Séparation (événement)
    ENGA = "enga"  # Fiançailles

    # Relations
    ADOP = "adop"  # Adoption
    RECO = "reco"  # Reconnaissance
    CAND = "cand"  # Candidat
    GODP = "godp"  # Parrain/Marraine
    OFFI = "offi"  # Officier (témoin #offi)
    FOST = "fost"  # Famille d'accueil
    FATH = "fath"  # Père
    MOTH = "moth"  # Mère

    # Modificateurs de champs personne
    NICK = "nick"  # Surnom / qualificatif
    SALIAS = "salias"  # Alias de nom de famille
    ALIAS = "alias"  # Alias général
    IMAGE = "image"  # Chemin image
    BS = "bs"  # Source naissance
    DS = "ds"  # Source décès
    PP = "pp"  # Lieu baptême
    PS = "ps"  # Source baptême
    RP = "rp"  # Lieu inhumation/crémation
    RS = "rs"  # Source inhumation/crémation
    MS = "ms"  # Source mariage

    # Qualificateurs de famille
    NSCK = "nsck"  # Pas de vérification sexe des époux
    NSCKM = "nsckm"  # Pas de vérification sexe (mariage)
    NOMENT = "noment"  # Relation sans mention
    BANNS = "banns"  # Publication des bans
    CONTRACT = "contract"  # Contrat de mariage
    LICENSE = "license"  # Licence de mariage

    # Autres tokens
    IDENTIFIER = "identifier"  # Identifiant (nom, prénom, lieu)
    DATE = "date"  # Date
    NUMBER = "number"  # Numéro d'occurrence
    STRING = "string"  # Chaîne de caractères
    COLON = ":"  # Deux points
    DASH = "-"  # Tire
    PLUS = "+"  # Plus (séparateur mariage)
    DOT = "."  # Point
    HASH = "#"  # Dièse (modificateur)
    PAREN_OPEN = "("  # Parenthèse ouvrante
    PAREN_CLOSE = ")"  # Parenthèse fermante
    BRACKET_OPEN = "["  # Crochet ouvrant
    BRACKET_CLOSE = "]"  # Crochet fermant
    BRACE_OPEN = "{"  # Accolade ouvrante
    BRACE_CLOSE = "}"  # Accolade fermante

    # Spéciaux
    NEWLINE = "newline"  # Nouvelle ligne
    WHITESPACE = "whitespace"  # Espace blanc
    COMMENT = "comment"  # Commentaire
    BLOCK_COMMENT = "block_comment"  # Commentaire (* ... *)
    EOF = "eof"  # Fin de fichier
    UNKNOWN = "unknown"  # Token inconnu


@dataclass
class Token:
    """Représentation d'un token avec sa position"""

    type: TokenType
    value: str
    line_number: int
    column: int
    position: int  # Position absolue dans le fichier

    def __str__(self) -> str:
        """Représentation string du token"""
        return f"{self.type.value}('{self.value}')@{self.line_number}:{self.column}"

    def __repr__(self) -> str:
        """Représentation pour debug"""
        return f"Token({self.type.value}, '{self.value}', {self.line_number}:{self.column})"  # noqa: E501


# Cache LRU pour les patterns regex compilés
@lru_cache(maxsize=128)
def _get_compiled_pattern(pattern: str) -> Pattern:
    """Cache pour les patterns regex compilés

    Args:
        pattern: Pattern regex sous forme de chaîne

    Returns:
        Pattern compilé
    """
    return re.compile(pattern)


class LexicalParser:
    """Parser lexical pour les fichiers .gw

    Tokenise un fichier .gw en identifiant tous les éléments lexicaux
    selon la spécification du format GeneWeb.
    """

    def __init__(self, text: str, filename: Optional[str] = None):
        """Initialise le parser lexical

        Args:
            text: Contenu du fichier à parser
            filename: Nom du fichier (pour les erreurs)
        """
        self.text = text
        self.filename = filename or "<string>"
        self.position = 0
        self.line_number = 1
        self.column = 1
        self.tokens: List[Token] = []

        # Patterns de reconnaissance
        self._compile_patterns()

    def _compile_patterns(self) -> None:
        """Compile les expressions régulières pour la tokenisation

        Note: dictionnaires pour des lookups O(1) plutôt que conditionnels.
        """

        # Symboles simples (pre-compilés pour accès rapide)
        self.symbol_map = {
            ":": TokenType.COLON,
            "-": TokenType.DASH,
            "+": TokenType.PLUS,
            ".": TokenType.DOT,
            "(": TokenType.PAREN_OPEN,
            ")": TokenType.PAREN_CLOSE,
            "[": TokenType.BRACKET_OPEN,
            "]": TokenType.BRACKET_CLOSE,
            "{": TokenType.BRACE_OPEN,
            "}": TokenType.BRACE_CLOSE,
        }

        # Mots-clés de blocs (doivent être en début de ligne)
        self.block_keywords = {
            "fam": TokenType.FAM,
            "notes": TokenType.NOTES,
            "rel": TokenType.REL,
            "pevt": TokenType.PEVT,
            "fevt": TokenType.FEVT,
            "notes-db": TokenType.NOTES_DB,
            "page-ext": TokenType.PAGE_EXT,
            "wizard-note": TokenType.WIZARD_NOTE,
            "wit": TokenType.WIT,
            "wnote": TokenType.WNOTE,
            "src": TokenType.SRC,
            "comm": TokenType.COMM,
        }

        # Mots-clés de fin de bloc
        self.end_keywords = {
            "end notes": TokenType.END_NOTES,
            "end pevt": TokenType.END_PEVT,
            "end fevt": TokenType.END_FEVT,
            "end notes-db": TokenType.END_NOTES_DB,
            "end page-ext": TokenType.END_PAGE_EXT,
            "end wizard-note": TokenType.END_WIZARD_NOTE,
            "end": TokenType.END,
            "beg": TokenType.BEG,
        }

        # Modificateurs avec #
        self.hash_modifiers = {
            "nm": TokenType.NM,
            "eng": TokenType.ENG,
            "sep": TokenType.SEP,
            "div": TokenType.DIV,
            "h": TokenType.H,
            "f": TokenType.F,
            "apubl": TokenType.APUBL,
            "apriv": TokenType.APRIV,
            "od": TokenType.OD,
            "mj": TokenType.MJ,
            "note": TokenType.NOTE,
            "occu": TokenType.OCCU,
            "buri": TokenType.BURI,
            "crem": TokenType.CREM,
            "wit": TokenType.WIT,
            "src": TokenType.SRC,
            "comm": TokenType.COMM,
            "cbp": TokenType.CBP,
            "csrc": TokenType.CSRC,
            "bp": TokenType.BP,
            "dp": TokenType.DP,
            "mp": TokenType.MP,
            "p": TokenType.P,
            "s": TokenType.S,
            "adop": TokenType.ADOP,
            "reco": TokenType.RECO,
            "cand": TokenType.CAND,
            "godp": TokenType.GODP,
            "offi": TokenType.OFFI,
            "fost": TokenType.FOST,
            "fath": TokenType.FATH,
            "moth": TokenType.MOTH,
            "nick": TokenType.NICK,
            "salias": TokenType.SALIAS,
            "alias": TokenType.ALIAS,
            "image": TokenType.IMAGE,
            "bs": TokenType.BS,
            "ds": TokenType.DS,
            "pp": TokenType.PP,
            "ps": TokenType.PS,
            "rp": TokenType.RP,
            "rs": TokenType.RS,
            "ms": TokenType.MS,
            "nsck": TokenType.NSCK,
            "nsckm": TokenType.NSCKM,
            "noment": TokenType.NOMENT,
            "banns": TokenType.BANNS,
            "contract": TokenType.CONTRACT,
            "license": TokenType.LICENSE,
        }

        # Types d'événements
        self.event_types = {
            "birt": TokenType.BIRT,
            "bapt": TokenType.BAPT,
            "deat": TokenType.DEAT,
            "buri": TokenType.BURI_EVENT,
            "crem": TokenType.CREM_EVENT,
            "marr": TokenType.MARR,
            "div": TokenType.DIV_EVENT,
            "sep": TokenType.SEP_EVENT,
            "enga": TokenType.ENGA,
        }

        # Mots-clés de relations (sans #)
        self.relation_keywords = {
            "adop": TokenType.ADOP,
            "reco": TokenType.RECO,
            "cand": TokenType.CAND,
            "godp": TokenType.GODP,
            "fost": TokenType.FOST,
            "fath": TokenType.FATH,
            "moth": TokenType.MOTH,
        }

    def tokenize(self) -> List[Token]:
        """Tokenise le texte complet

        Returns:
            Liste de tous les tokens

        Raises:
            GeneWebParseError: En cas d'erreur de tokenisation
        """
        self.tokens = []
        self.position = 0
        self.line_number = 1
        self.column = 1

        while self.position < len(self.text):
            # Gérer les newlines séparément
            if self.text[self.position] == "\n":
                self.tokens.append(
                    Token(
                        type=TokenType.NEWLINE,
                        value="\n",
                        line_number=self.line_number,
                        column=self.column,
                        position=self.position,
                    )
                )
                self._advance_position()
                continue

            # Ignorer les autres espaces blancs
            self._skip_whitespace()

            if self.position >= len(self.text):
                break

            # Espaces en fin de ligne : laisser la boucle émettre le NEWLINE
            if self.text[self.position] == "\n":
                continue

            token = self._next_token()
            if token:
                self.tokens.append(token)

        # Ajouter le token EOF
        self.tokens.append(
            Token(
                type=TokenType.EOF,
                value="",
                line_number=self.line_number,
                column=self.column,
                position=self.position,
            )
        )

        return self.tokens

    def _skip_whitespace(self) -> None:
        """Ignore les espaces blancs (sauf les newlines) et met à jour la position"""
        while (
            self.position < len(self.text)
            and self.text[self.position].isspace()
            and self.text[self.position] != "\n"
        ):
            self.column += 1
            self.position += 1

    def _next_token(self) -> Optional[Token]:
        """Lit le prochain token

        Returns:
            Token suivant ou None si fin de fichier
        """
        char = self.text[self.position]
        start_pos = self.position
        start_line = self.line_number
        start_col = self.column

        # Commentaires bloc (* ... *) — ignorés par le parser syntaxique
        # Pré-vérification rapide : *) doit exister sur la même ligne.
        # Sans cela, un (* dans un bloc notes (ex : "(* 1934; ...)")
        # provoquerait un scan de 256 Ko inutile avant de lever une erreur.
        if (
            char == "("
            and self.position + 1 < len(self.text)
            and self.text[self.position + 1] == "*"
        ):
            eol = self.text.find("\n", self.position + 2)
            if eol == -1:
                eol = len(self.text)
            if self.text.find("*)", self.position + 2, eol) != -1:
                return self._parse_block_comment(start_line, start_col, start_pos)
            # Pas de *) sur la même ligne → traité comme texte littéral

        # Modificateurs avec # (y compris les événements)
        # Vérifier d'abord si c'est un modificateur connu
        if char == "#":
            # Essayer de parser comme modificateur
            # Si ça échoue et qu'on est en début de ligne, c'est un commentaire
            saved_pos = self.position
            saved_line = self.line_number
            saved_col = self.column

            # Tenter de parser comme modificateur
            token = self._parse_hash_modifier(start_line, start_col, start_pos)

            # Si c'est un modificateur connu, le retourner
            if token and token.type != TokenType.IDENTIFIER:
                return token

            # Sinon, restaurer la position et traiter comme commentaire si en début de ligne  # noqa: E501
            self.position = saved_pos
            self.line_number = saved_line
            self.column = saved_col

            # Si on est en début de ligne et que ce n'est pas un modificateur, c'est un commentaire  # noqa: E501
            if self.column == 1 or (
                self.position > 0 and self.text[self.position - 1] == "\n"
            ):
                return self._parse_comment(start_line, start_col, start_pos)

        # Mots-clés de blocs (en début de ligne)
        if self.column == 1:
            block_token = self._parse_block_keyword(start_line, start_col, start_pos)
            if block_token:
                return block_token

        # Nom ou prénom inconnu écrit ``?``, ``???``… (hors date ``?1950``)
        if char == "?" and _QUESTION_WORD.match(self.text, self.position):
            return self._parse_identifier(start_line, start_col, start_pos)

        # Dates (commençant par un chiffre ou un préfixe)
        if char.isdigit() or char in "~?<>":
            return self._parse_date(start_line, start_col, start_pos)

        # Numéros d'occurrence (.nombre)
        if (
            char == "."
            and self.position + 1 < len(self.text)
            and self.text[self.position + 1].isdigit()
        ):
            return self._parse_number(start_line, start_col, start_pos)

        # Symboles simples (utilisation du dictionnaire pré-compilé)
        if char in self.symbol_map:
            self._advance_position()
            return Token(
                type=self.symbol_map[char],
                value=char,
                line_number=start_line,
                column=start_col,
                position=start_pos,
            )

        # Identifiants (noms, prénoms, lieux)
        if char.isalpha() or char == "_":
            return self._parse_identifier(start_line, start_col, start_pos)

        # Chaînes de caractères (entre guillemets)
        if char == '"':
            return self._parse_string(start_line, start_col, start_pos)

        # Token inconnu
        self._advance_position()
        return Token(
            type=TokenType.UNKNOWN,
            value=char,
            line_number=start_line,
            column=start_col,
            position=start_pos,
        )

    def _parse_comment(self, line: int, col: int, pos: int) -> Token:
        """Parse un commentaire (ligne complète commençant par #)"""
        start_pos = pos
        while self.position < len(self.text) and self.text[self.position] != "\n":
            self._advance_position()

        value = self.text[start_pos : self.position]
        return Token(
            type=TokenType.COMMENT,
            value=value,
            line_number=line,
            column=col,
            position=pos,
        )

    def _parse_block_comment(self, line: int, col: int, pos: int) -> Token:
        """Parse un commentaire bloc GeneWeb du type (* ... *)."""
        start_pos = pos
        # Avancer au-delà de "(*"
        self._advance_position()
        self._advance_position()
        body_len = 0
        closed = False
        while self.position + 1 < len(self.text):
            if self.text[self.position] == "*" and self.text[self.position + 1] == ")":
                self._advance_position()
                self._advance_position()
                closed = True
                break
            self._advance_position()
            body_len += 1
            if body_len > _BLOCK_COMMENT_BODY_MAX_CHARS:
                raise GeneWebParseError(
                    "Commentaire bloc (* ...) trop long ou non terminé avant la limite",
                    line_number=line,
                    token=self.text[start_pos : start_pos + 40],
                    expected="*)",
                )

        if not closed:
            raise GeneWebParseError(
                "Commentaire bloc (* ...) non fermé avant la fin du flux",
                line_number=line,
                token=self.text[start_pos : start_pos + 40],
                expected="*)",
            )

        value = self.text[start_pos : self.position]
        return Token(
            type=TokenType.BLOCK_COMMENT,
            value=value,
            line_number=line,
            column=col,
            position=pos,
        )

    def _parse_block_keyword(self, line: int, col: int, pos: int) -> Optional[Token]:
        """Parse un mot-clé de bloc en début de ligne (peut être composé)"""
        word = ""
        start_pos = pos

        # Lire le premier mot
        while self.position < len(self.text) and (
            self.text[self.position].isalnum() or self.text[self.position] in "-_"
        ):
            word += self.text[self.position]
            self._advance_position()

        # Vérifier si c'est le début d'un mot-clé composé (comme "end notes")
        if word == "end":
            # Lire le mot suivant
            self._skip_whitespace()
            if self.position < len(self.text):
                next_word = ""
                next_start_pos = self.position
                while self.position < len(self.text) and (
                    self.text[self.position].isalnum()
                    or self.text[self.position] in "-_"
                ):
                    next_word += self.text[self.position]
                    self._advance_position()

                # Vérifier si c'est un mot-clé composé
                compound_keyword = f"{word} {next_word}"
                if compound_keyword in self.end_keywords:
                    return Token(
                        type=self.end_keywords[compound_keyword],
                        value=compound_keyword,
                        line_number=line,
                        column=col,
                        position=pos,
                    )
                else:
                    # Remettre la position du deuxième mot
                    self.position = next_start_pos
                    self.line_number = line
                    self.column = col + len(word)
                    # Continuer avec la vérification des mots-clés simples

        # Vérifier si c'est un mot-clé simple
        if word in self.block_keywords:
            return Token(
                type=self.block_keywords[word],
                value=word,
                line_number=line,
                column=col,
                position=pos,
            )

        if word in self.end_keywords:
            return Token(
                type=self.end_keywords[word],
                value=word,
                line_number=line,
                column=col,
                position=pos,
            )

        # Si ce n'est pas un mot-clé, on remet la position et on continue
        self.position = start_pos
        self.line_number = line
        self.column = col
        return None

    def _parse_hash_modifier(self, line: int, col: int, pos: int) -> Token:
        """Parse un modificateur avec # (ex: #bp, #mp, #wit)"""
        self._advance_position()  # Passer le #

        word = ""

        # Parser le mot-clé de base
        while self.position < len(self.text) and (
            self.text[self.position].isalnum() or self.text[self.position] in "-_"
        ):
            word += self.text[self.position]
            self._advance_position()

        # Déterminer le type de token
        if word in self.hash_modifiers:
            token_type = self.hash_modifiers[word]
        elif word in self.event_types:
            token_type = self.event_types[word]
        else:
            token_type = TokenType.IDENTIFIER

        return Token(
            type=token_type,
            value=f"#{word}",
            line_number=line,
            column=col,
            position=pos,
        )

    def _parse_date(self, line: int, col: int, pos: int) -> Token:
        """Parse une date (ex: 25/12/1990, ~10/5/1990, 0(texte))"""
        value = ""

        # Cas spécial pour les dates avec parenthèses 0(texte)
        if (
            self.position < len(self.text)
            and self.text[self.position] == "0"
            and self.position + 1 < len(self.text)
            and self.text[self.position + 1] == "("
        ):
            # Parser jusqu'à la parenthèse fermante correspondante
            paren_count = 0
            while self.position < len(self.text):
                char = self.text[self.position]
                value += char
                if char == "(":
                    paren_count += 1
                elif char == ")":
                    paren_count -= 1
                    if paren_count == 0:
                        self._advance_position()
                        break
                self._advance_position()
        else:
            # Parser normal pour les autres dates
            while self.position < len(self.text) and (
                self.text[self.position].isdigit()
                or self.text[self.position] in "/~?<>|.()JFH"
                or self.text[self.position].isalpha()
            ):
                value += self.text[self.position]
                self._advance_position()

        return Token(
            type=TokenType.DATE, value=value, line_number=line, column=col, position=pos
        )

    def _parse_number(self, line: int, col: int, pos: int) -> Token:
        """Parse un numéro d'occurrence (ex: .1, .2)"""
        value = ""

        while self.position < len(self.text) and (
            self.text[self.position].isdigit() or self.text[self.position] == "."
        ):
            value += self.text[self.position]
            self._advance_position()

        return Token(
            type=TokenType.NUMBER,
            value=value,
            line_number=line,
            column=col,
            position=pos,
        )

    def _parse_identifier(self, line: int, col: int, pos: int) -> Token:
        """Parse un identifiant (nom, prénom, lieu) ou un mot-clé spécial"""
        value = ""

        while self.position < len(self.text) and (
            self.text[self.position].isalnum() or self.text[self.position] in "_-'?"
        ):
            value += self.text[self.position]
            self._advance_position()

        # Vérifier si c'est un mot-clé spécial (wit, wnote, src, comm, beg, end)
        if value in ["wit", "wnote", "src", "comm", "beg", "end"]:
            token_type = {
                "wit": TokenType.WIT,
                "wnote": TokenType.WNOTE,
                "src": TokenType.SRC,
                "comm": TokenType.COMM,
                "beg": TokenType.BEG,
                "end": TokenType.END,
            }[value]
        # Vérifier si c'est un modificateur de sexe (m/f/h/f)
        elif value in ["m", "f", "h"]:
            token_type = {
                "m": TokenType.H,  # Masculin
                "f": TokenType.F,  # Féminin
                "h": TokenType.H,  # Homme (masculin)
            }[value]
        # Vérifier si c'est un mot-clé de relation
        elif value in self.relation_keywords:
            token_type = self.relation_keywords[value]
        else:
            token_type = TokenType.IDENTIFIER

        return Token(
            type=token_type, value=value, line_number=line, column=col, position=pos
        )

    def _parse_string(self, line: int, col: int, pos: int) -> Token:
        """Parse une chaîne de caractères entre guillemets (mono-ligne uniquement).

        Si le guillemet fermant n'est pas trouvé sur la même ligne, le guillemet
        ouvrant est restitué comme UNKNOWN pour éviter de consommer les blocs
        suivants (end notes, pevt, etc.) comme contenu de la chaîne.
        """
        # Vérifier qu'un " fermant existe sur la même ligne avant d'avancer
        close = self.text.find('"', pos + 1)
        eol = self.text.find("\n", pos + 1)
        if close == -1 or (eol != -1 and close > eol):
            # Pas de fermeture sur la ligne : guillemet traité comme UNKNOWN
            self._advance_position()
            return Token(
                type=TokenType.UNKNOWN,
                value='"',
                line_number=line,
                column=col,
                position=pos,
            )

        self._advance_position()  # Passer le guillemet ouvrant
        value = ""

        while self.position < len(self.text) and self.text[self.position] != '"':
            if self.text[self.position] == "\\" and self.position + 1 < len(self.text):
                # Gérer les échappements
                self._advance_position()
                if self.text[self.position] == '"':
                    value += '"'
                elif self.text[self.position] == "\\":
                    value += "\\"
                else:
                    value += "\\" + self.text[self.position]
            else:
                value += self.text[self.position]
            self._advance_position()

        if self.position < len(self.text):
            self._advance_position()  # Passer le guillemet fermant

        return Token(
            type=TokenType.STRING,
            value=value,
            line_number=line,
            column=col,
            position=pos,
        )

    def _advance_position(self) -> None:
        """Avance la position d'un caractère"""
        if self.position < len(self.text):
            if self.text[self.position] == "\n":
                self.line_number += 1
                self.column = 1
            else:
                self.column += 1
            self.position += 1

    def get_tokens(self) -> List[Token]:
        """Retourne la liste des tokens"""
        return self.tokens

    def __iter__(self) -> Iterator[Token]:
        """Itérateur sur les tokens"""
        return iter(self.tokens)
