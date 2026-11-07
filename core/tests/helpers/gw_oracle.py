"""
Oracle regex pour les tests : extraction brute des ``wit`` et des blocs ``pevt``.

Sert de référence indépendante du lexer/parser nominal pour vérifier qu'aucun témoin
ni événement n'est perdu (voir ``tests/integration/test_zero_event_loss.py``).
Ce module n'appartient pas à la bibliothèque : il vit côté tests uniquement.
"""

import re

from geneweb_py.core.person import Gender


class RegexPersonExtractor:
    """Extracteur de personnes basé sur regex (comme script original)"""

    def __init__(self):
        """Initialise l'extracteur regex"""
        # Regex pour extraire les témoins (plus robuste que le tokenizer)
        self.regex_wit = re.compile(r"^wit\s+(m|f)?:?\s+(\S+)\s+(\S+)", re.MULTILINE)

        # Regex pour les blocs pevt
        self.regex_pevt = re.compile(
            r"(?s)^pevt\s+(\S+)\s+(\S+).*?^end\s+pevt", re.MULTILINE
        )

        # Regex pour les blocs fevt
        self.regex_fevt = re.compile(r"(?s)^fevt.*?^end\s+fevt", re.MULTILINE)

    def extract_all_witnesses(self, content: str) -> list[dict[str, str]]:
        """Extrait TOUS les témoins du fichier avec regex

        Args:
            content: Contenu texte complet du fichier .gw

        Returns:
            Liste de dictionnaires {last_name, first_name, gender, line_number}
        """
        witnesses = []

        for match in self.regex_wit.finditer(content):
            sex = match.group(1)  # 'm', 'f', ou None
            last_name = match.group(2)
            first_name = match.group(3)

            # Déterminer le sexe
            gender = Gender.UNKNOWN
            if sex == "m":
                gender = Gender.MALE
            elif sex == "f":
                gender = Gender.FEMALE

            # Calculer le numéro de ligne
            line_number = content[: match.start()].count("\n") + 1

            witnesses.append(
                {
                    "last_name": last_name,
                    "first_name": first_name,
                    "gender": gender,
                    "line_number": line_number,
                }
            )

        return witnesses

    def extract_pevt_blocks(self, content: str) -> list[tuple[str, str, str]]:
        """Extrait les blocs pevt avec regex

        Args:
            content: Contenu texte du fichier

        Returns:
            Liste de tuples (last_name, first_name, bloc_content)
        """
        results = []

        for match in self.regex_pevt.finditer(content):
            last_name = match.group(1)
            first_name = match.group(2)
            bloc_content = match.group(0)

            results.append((last_name, first_name, bloc_content))

        return results

    def count_pevt_event_lines(self, content: str) -> int:
        """Compte les lignes ``#tag`` des blocs pevt (hors ``#p``/``#s``)."""
        total = 0
        for _, _, block in self.extract_pevt_blocks(content):
            total += len(re.findall(r"^#(?!p\s|s\s)[A-Za-z]\S*", block, re.MULTILINE))
        return total


def compare_extraction_methods(file_path: str) -> dict[str, int]:
    """Compare les méthodes d'extraction regex vs tokens

    Args:
        file_path: Chemin vers le fichier .gw

    Returns:
        Dictionnaire avec les statistiques de comparaison
    """
    # Lire le fichier
    with open(file_path, encoding="utf-8") as f:
        content = f.read()

    # Extraction regex
    extractor = RegexPersonExtractor()
    witnesses_regex = extractor.extract_all_witnesses(content)
    pevt_blocks_regex = extractor.extract_pevt_blocks(content)

    # Extraction tokens
    from geneweb_py.core.parser.gw_parser import GeneWebParser
    from geneweb_py.core.parser.lexical import TokenType

    parser = GeneWebParser()
    parser.parse_file(file_path)

    wit_tokens = sum(1 for t in parser.tokens if t.type == TokenType.WIT)
    pevt_nodes = sum(1 for n in parser.syntax_nodes if n.type.value == "person_events")

    return {
        "witnesses_regex": len(witnesses_regex),
        "witnesses_tokens": wit_tokens,
        "witnesses_lost": len(witnesses_regex) - wit_tokens,
        "pevt_regex": len(pevt_blocks_regex),
        "pevt_nodes": pevt_nodes,
    }
