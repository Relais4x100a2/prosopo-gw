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
