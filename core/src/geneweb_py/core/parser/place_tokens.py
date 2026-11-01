"""Lecture des jetons d'un lieu GeneWeb, crochets compris (``[complément]_-_lieu``)."""

from typing import List, Optional

from .lexical import Token, TokenType


def join_tokens_text(tokens: List[Token], par_ligne: bool = False) -> str:
    """Recolle des jetons en un texte, avec un espace là où la source en avait un.

    Un espace est inséré quand deux jetons ne sont pas contigus (positions) ; les
    chaînes collées (URL, ``f°42v``, ``[a]_-_b``) restent donc intactes. Avec
    ``par_ligne``, un changement de ligne source donne un retour à la ligne.
    """
    parts: List[str] = []
    prev_end = -1
    prev_line = None
    for tok in tokens:
        if parts and par_ligne and tok.line_number != prev_line:
            parts.append("\n")
        elif parts and tok.position != prev_end:
            parts.append(" ")
        prev_line = tok.line_number
        parts.append(tok.value)
        prev_end = tok.position + len(tok.value)
    return "".join(parts)


def place_run_end(tokens: List[Token], start: int) -> int:
    """Index après le lieu qui commence à ``start`` (``start`` si ce n'en est pas un).

    Un lieu est un identifiant ou un groupe ``[…]``, suivi d'identifiants collés
    et de segments séparés par des virgules (``Ville,_Code,_Pays``).
    """
    n = len(tokens)
    j = start
    if j < n and tokens[j].type == TokenType.BRACKET_OPEN:
        j += 1
        while j < n and tokens[j].type not in (
            TokenType.BRACKET_CLOSE,
            TokenType.NEWLINE,
            TokenType.EOF,
        ):
            j += 1
        if j >= n or tokens[j].type != TokenType.BRACKET_CLOSE:
            return start
        j += 1
    elif j < n and tokens[j].type == TokenType.IDENTIFIER:
        j += 1
    else:
        return start
    return mot_end(tokens, j - 1)


def death_marker(token: Token) -> Optional[str]:
    """``"od"`` ou ``"mj"`` si le jeton est un marqueur de décès, sinon ``None``.

    Le format natif écrit ``od`` / ``mj`` nus après la date de naissance ; la
    documentation les note ``#od`` / ``#mj``. À n'appeler qu'une fois nom et prénom
    lus, pour qu'un nom ``od`` reste un nom.
    """
    if token.type == TokenType.OD:
        return "od"
    if token.type == TokenType.MJ:
        return "mj"
    if token.type == TokenType.IDENTIFIER and token.value in ("od", "mj"):
        return token.value
    return None


def mot_end(tokens: List[Token], start: int) -> int:
    """Fin du mot qui commence à ``start`` : jetons contigus, de n'importe quel type.

    Un mot GeneWeb se termine à un espace ; le lexeur peut le découper (URL,
    ``<br>``, ``a?x=1``), la contiguïté des positions le recolle. Une virgule
    suivie d'un identifiant prolonge aussi le lieu (``Ville,_Code``).
    """
    n = len(tokens)
    j = start
    while j < n:
        tok = tokens[j]
        if tok.type in (TokenType.NEWLINE, TokenType.EOF):
            break
        collé = j == start or (
            tok.position == tokens[j - 1].position + len(tokens[j - 1].value)
        )
        if collé:
            j += 1
        elif (
            tok.type == TokenType.UNKNOWN
            and tok.value == ","
            and j + 1 < n
            and tokens[j + 1].type == TokenType.IDENTIFIER
        ):
            j += 2
        else:
            break
    return j


def texte_libre(tokens: List[Token], limite: int) -> str:
    """Texte d'une note : les ``limite`` premiers jetons utiles, à l'identique."""
    utiles = [
        t for t in tokens if t.type not in (TokenType.NEWLINE, TokenType.WHITESPACE)
    ]
    return join_tokens_text(utiles[:limite], par_ligne=True)
