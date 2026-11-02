"""Les champs texte lus en ligne sont décodés comme gwc : ``_`` -> espace, ``\\_`` -> ``_``."""

from geneweb_py.core.parser.gw_parser import GeneWebParser

GW = """fam DUPONT Jean 1870 #bp Lyon #bs Registre\\_A_12 1930 #dp Nantes #ds Acte\\_B_3 +1900 MARTIN Marie
beg
- h Pierre 1900 #bs Reg\\_C_4
end
"""


def _parse(text: str):
    return GeneWebParser().parse_string(text)


def test_escaped_underscore_kept_in_sources() -> None:
    g = _parse(GW)
    dupont = next(p for p in g.persons.values() if p.last_name == "DUPONT")
    assert dupont.birth_source == "Registre_A 12"
    assert dupont.death_source == "Acte_B 3"
    child = next(p for p in g.persons.values() if p.first_name == "Pierre")
    assert child.birth_source == "Reg_C 4"


def test_child_line_reads_person_source_and_occupation_as_words() -> None:
    g = _parse(
        "fam DUPONT Jean +1900 MARTIN Marie\nbeg\n"
        "- h Pierre #occu 3_E_041/472 1900 #bp Lyon #src Doc\\_4\n"
        "- f Anne #src http://x.example/a-b/12 #occu Menuisier,_chef 1905\n"
        "end\n"
    )
    pierre = next(p for p in g.persons.values() if p.first_name == "Pierre")
    anne = next(p for p in g.persons.values() if p.first_name == "Anne")
    assert pierre.occupation == "3 E 041/472"
    assert str(pierre.birth_date) == "1900"
    assert pierre.death_date is None
    assert pierre.birth_place == "Lyon"
    assert pierre.person_source == "Doc_4"
    assert anne.person_source == "http://x.example/a-b/12"
    assert anne.occupation == "Menuisier, chef"
    assert str(anne.birth_date) == "1905"


def test_places_are_decoded_at_parse_and_hyphenated_toponyms_survive() -> None:
    g = _parse(
        "fam DUPONT Jean 1900 #bp Saint-Maur-des-Fossés_(94) +1925 #mp [Atelier\\_Rose]_-_Lyon "
        "MARTIN Marie 1902 #dp Aix-en-Provence\nbeg\n- h Pierre 1930 #bp Lieu\\_dit\nend\n"
    )
    jean = next(p for p in g.persons.values() if p.first_name == "Jean")
    marie = next(p for p in g.persons.values() if p.first_name == "Marie")
    pierre = next(p for p in g.persons.values() if p.first_name == "Pierre")
    (famille,) = g.families.values()
    assert jean.birth_place == "Saint-Maur-des-Fossés (94)"
    assert marie.death_place == "Aix-en-Provence"
    assert pierre.birth_place == "Lieu_dit"
    assert famille.marriage_place == "[Atelier_Rose] - Lyon"
