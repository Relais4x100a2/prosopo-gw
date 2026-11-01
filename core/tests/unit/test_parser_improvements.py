"""
Tests unitaires pour les améliorations du parser GeneWeb
"""

import pytest

from geneweb_py.core.parser.gw_parser import GeneWebParser
from geneweb_py.core.parser.lexical import LexicalParser, TokenType


class TestLexicalParserImprovements:
    """Tests pour les améliorations du parser lexical"""

    def test_apostrophes_in_identifiers(self):
        """Test que les apostrophes sont acceptées dans les identifiants"""
        parser = LexicalParser("fam d'Arc Jean-Marie O'Brien")
        tokens = parser.tokenize()

        # Trouver les tokens IDENTIFIER
        identifiers = [t for t in tokens if t.type == TokenType.IDENTIFIER]

        # Vérifier que les noms avec apostrophes sont parsés
        identifier_values = [t.value for t in identifiers]
        assert "d'Arc" in identifier_values
        assert "Jean-Marie" in identifier_values
        assert "O'Brien" in identifier_values

    def test_special_characters_in_occupations(self):
        """Test que les caractères spéciaux sont acceptés dans les occupations"""
        parser = LexicalParser("#occu Dominicain,_Aumônier_de_l'enseignement_à_Rouen")
        tokens = parser.tokenize()

        # Trouver le token OCCU et les tokens suivants
        occu_index = next(i for i, t in enumerate(tokens) if t.type == TokenType.OCCU)

        # Vérifier que les caractères spéciaux sont préservés dans les tokens suivants
        occupation_tokens = tokens[occu_index + 1 :]
        occupation_text = "".join(
            t.value for t in occupation_tokens if t.type != TokenType.EOF
        )
        assert "Dominicain,_Aumônier_de_l'enseignement_à_Rouen" in occupation_text

    def test_complex_occupation_with_parentheses(self):
        """Test des occupations avec parenthèses"""
        parser = LexicalParser("#occu Ingénieur_(ENSIA),_Ancien_combattant_AFN")
        tokens = parser.tokenize()

        # Trouver le token OCCU et les tokens suivants
        occu_index = next(i for i, t in enumerate(tokens) if t.type == TokenType.OCCU)

        # Vérifier que les parenthèses sont préservées dans les tokens suivants
        occupation_tokens = tokens[occu_index + 1 :]
        occupation_text = "".join(
            t.value for t in occupation_tokens if t.type != TokenType.EOF
        )
        assert "Ingénieur_(ENSIA),_Ancien_combattant_AFN" in occupation_text


class TestDeduplicationImprovements:
    """Tests pour les améliorations de déduplication"""

    def test_occurrence_number_extraction(self):
        """Test l'extraction des numéros d'occurrence"""
        parser = GeneWebParser()

        # Test avec un fichier simple contenant des numéros d'occurrence
        content = """
fam CORNO Jean .1 + MOREAU Marie .2
beg
- h Pierre_Bernard .1
- f Marie_Claire .2
end
"""
        genealogy = parser.parse_string(content)

        # Vérifier que les personnes sont créées avec les bons numéros d'occurrence
        persons = list(genealogy.persons.values())

        # Trouver les personnes par nom
        jean = next((p for p in persons if p.first_name == "Jean"), None)
        marie = next((p for p in persons if p.first_name == "Marie"), None)

        # Les parents ont bien leurs numéros d'occurrence
        assert jean is not None
        assert jean.occurrence_number == 1
        assert marie is not None
        assert marie.occurrence_number == 2

        # Note: Les enfants dans beg...end ne sont pas actuellement créés comme personnes séparées  # noqa: E501
        # C'est une limitation connue du parser actuel

    def test_witness_occurrence_numbers(self):
        """Test des numéros d'occurrence pour les témoins"""
        parser = GeneWebParser()

        content = """
fam CORNO Jean + MOREAU Marie
wit m: LEROY Bernard .1 #occu Dominicain
wit f: BLANC Anne .2 #occu Prêtre
beg
- h Pierre_Bernard
end
"""
        genealogy = parser.parse_string(content)

        persons = list(genealogy.persons.values())

        # Trouver les témoins
        leroy = next((p for p in persons if p.first_name == "Bernard"), None)
        thierry = next((p for p in persons if p.first_name == "Anne"), None)

        assert leroy is not None
        assert leroy.occurrence_number == 1
        assert leroy.occupation == "Dominicain"

        assert thierry is not None
        assert thierry.occurrence_number == 2
        assert thierry.occupation == "Prêtre"


class TestNewBlockParsers:
    """Tests pour les nouveaux parsers de blocs"""

    def test_database_notes_block(self):
        """Test du parsing des blocs notes-db"""
        parser = GeneWebParser()

        content = """
notes-db
Ceci est une note de base de données
avec plusieurs lignes
end notes-db
"""
        genealogy = parser.parse_string(content)

        # Vérifier que les notes de base de données sont stockées
        assert hasattr(genealogy.metadata, "database_notes")
        assert len(genealogy.metadata.database_notes) == 1
        assert (
            "Ceci est une note de base de données\navec plusieurs lignes"
            in genealogy.metadata.database_notes[0]
        )

    def test_extended_page_block(self):
        """Test du parsing des blocs page-ext"""
        parser = GeneWebParser()

        content = """
page-ext CORNO Jean .1
<h1>Page personnelle de Jean CORNO</h1>
<p>Informations supplémentaires...</p>
end page-ext
"""
        genealogy = parser.parse_string(content)

        # Vérifier que la personne est créée
        persons = list(genealogy.persons.values())
        jean = next((p for p in persons if p.first_name == "Jean"), None)

        assert jean is not None
        assert jean.occurrence_number == 1

        # Vérifier que le contenu de la page est stocké
        assert "extended_page" in jean.metadata
        assert len(jean.metadata["extended_page"]) > 0
        assert "Page personnelle de Jean CORNO" in jean.metadata["extended_page"][0]

    def test_wizard_note_block(self):
        """Test du parsing des blocs wizard-note"""
        parser = GeneWebParser()

        content = """
wizard-note CORNO Jean .1
Note générée automatiquement par le wizard
Informations importantes sur cette personne
end wizard-note
"""
        genealogy = parser.parse_string(content)

        # Vérifier que la personne est créée
        persons = list(genealogy.persons.values())
        jean = next((p for p in persons if p.first_name == "Jean"), None)

        assert jean is not None
        assert jean.occurrence_number == 1

        # Vérifier que les notes de wizard sont ajoutées
        assert len(jean.notes) == 1
        assert "[Wizard]" in jean.notes[0]
        assert "Note générée automatiquement par le wizard" in jean.notes[0]


class TestOccupationParsingImprovements:
    """Tests pour les améliorations du parsing des occupations"""

    def test_occupation_with_commas(self):
        """Test des occupations avec virgules"""
        parser = GeneWebParser()

        content = """
fam CORNO Jean #occu Ingénieur,_éditeur,_dirigeant + MOREAU Marie
"""
        genealogy = parser.parse_string(content)

        persons = list(genealogy.persons.values())
        jean = next((p for p in persons if p.first_name == "Jean"), None)

        assert jean is not None
        assert jean.occupation == "Ingénieur, éditeur, dirigeant"

    def test_occupation_with_parentheses(self):
        """Test des occupations avec parenthèses"""
        parser = GeneWebParser()

        content = """
fam CORNO Jean #occu Ingénieur_(ENSIA),_Ancien_combattant_AFN + MOREAU Marie
"""
        genealogy = parser.parse_string(content)

        persons = list(genealogy.persons.values())
        jean = next((p for p in persons if p.first_name == "Jean"), None)

        assert jean is not None
        assert jean.occupation == "Ingénieur (ENSIA), Ancien combattant AFN"

    def test_occupation_with_apostrophes(self):
        """Test des occupations avec apostrophes"""
        parser = GeneWebParser()

        content = """
fam CORNO Jean #occu Aumônier_de_l'enseignement_technique + MOREAU Marie
"""
        genealogy = parser.parse_string(content)

        persons = list(genealogy.persons.values())
        jean = next((p for p in persons if p.first_name == "Jean"), None)

        assert jean is not None
        assert jean.occupation == "Aumônier de l'enseignement technique"


class TestComplexScenarios:
    """Tests pour des scénarios complexes combinant plusieurs améliorations"""

    @pytest.mark.skip(
        reason=(
            "Parser ne parse pas encore témoins et enfants inline — limitation connue"
        )
    )
    def test_complete_improvements_integration(self):
        """Test d'intégration de toutes les améliorations"""
        parser = GeneWebParser()

        content = (
            """
fam d'Arc Jean-Marie .1 #occu Ingénieur_(ENSIA), """
            """_Aumônier_de_l'enseignement + O'Brien Marie-Claire .2
wit m: LEROY Bernard .1 #occu Dominicain,_Aumônier_de_l'enseignement_technique_à_Rouen
beg
- h Pierre_Bernard .1 #occu Ingénieur,_éditeur
- f Marie_Claire .2 #occu Conseillère_en_économie_sociale_et_familiale
end

notes-db
Notes générales sur cette famille
end notes-db

page-ext d'Arc Jean-Marie .1
<h1>Page de Jean-Marie d'Arc</h1>
end page-ext

wizard-note O'Brien Marie-Claire .2
Note générée par le wizard pour Marie-Claire
end wizard-note
"""
        )
        genealogy = parser.parse_string(content)

        # Vérifier que toutes les personnes sont créées avec les bons numéros d'occurrence  # noqa: E501
        persons = list(genealogy.persons.values())

        jean_marie = next(
            (
                p
                for p in persons
                if p.first_name == "Jean-Marie" and p.last_name == "d'Arc"
            ),
            None,
        )
        marie_claire = next(
            (
                p
                for p in persons
                if p.first_name == "Marie-Claire" and p.last_name == "O'Brien"
            ),
            None,
        )
        bernard = next((p for p in persons if p.first_name == "Bernard"), None)

        # Vérifications des numéros d'occurrence pour les parents et témoins
        assert jean_marie is not None
        assert jean_marie.occurrence_number == 1
        assert marie_claire is not None
        assert marie_claire.occurrence_number == 2
        assert bernard is not None
        assert bernard.occurrence_number == 1

        # Note: Les enfants dans beg...end ne sont pas actuellement créés comme personnes séparées  # noqa: E501
        # C'est une limitation connue du parser actuel

        # Vérifications des occupations avec caractères spéciaux
        assert jean_marie.occupation == "Ingénieur (ENSIA), Aumônier de l'enseignement"
        assert (
            bernard.occupation
            == "Dominicain, Aumônier de l'enseignement technique à Rouen"
        )

        # Vérifications des nouveaux blocs
        assert hasattr(genealogy.metadata, "database_notes")
        assert len(genealogy.metadata.database_notes) == 1

        assert "extended_page" in jean_marie.metadata
        assert len(jean_marie.metadata["extended_page"]) > 0

        assert len(marie_claire.notes) == 1
        assert "[Wizard]" in marie_claire.notes[0]
