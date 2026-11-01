"""cbp / csrc : lieu de naissance et source communs aux enfants de la famille."""

from geneweb_py import GeneWebParser


def _parse(s):
    return GeneWebParser(validate=False).parse_string(s)


def test_cbp_et_csrc_appliques_aux_enfants_sans_valeur_propre():
    g = _parse(
        "fam A B +1900 C D\ncbp Ville,_75000,_France\ncsrc Site_(Web)  v2\n"
        "beg\n- h E 1/1/1930\n- f F #bp Autre\n- h G\nend\n"
    )
    (f,) = g.families.values()
    assert f.common_birth_place == "Ville,_75000,_France"
    assert f.common_children_source == "Site_(Web)  v2"
    e, fl, h = (g.persons[c.person_id] for c in f.children)
    assert (e.birth_place, fl.birth_place, h.birth_place) == (
        "Ville,_75000,_France",
        "Autre",
        "Ville,_75000,_France",
    )
    assert all(p.person_source == "Site_(Web)  v2" for p in (e, fl, h))


def test_sans_cbp_rien_n_est_ajoute():
    g = _parse("fam A B +1900 C D\nbeg\n- h E\nend\n")
    (f,) = g.families.values()
    assert g.persons[f.children[0].person_id].birth_place is None
    assert f.common_birth_place is None


def test_nom_enfant_prenom_puis_nom():
    g = _parse(
        "fam DUPONT Jean +1900 MARTIN Marie\nbeg\n"
        "- f Julie,_Noémie,_Joséphine 23/9/1903\n"
        "- h Jean-Marie.2 LEROY_DE_X 1/1/1950\n"
        "- f Iris_Ayala DUPONT_LANDAU #apriv 3/9/2015\n- h Luc\nend\n"
    )
    ids = {p.unique_id for p in g.persons.values()}
    assert {
        "DUPONT_Julie,_Noémie,_Joséphine_0",
        "LEROY_DE_X_Jean-Marie_2",
        "DUPONT_LANDAU_Iris_Ayala_0",
        "DUPONT_Luc_0",
    } <= ids


def test_csrc_cbp_appliques_apres_fevt():
    g = _parse(
        "fam DUPONT Jean +1900 MARTIN Marie\ncsrc Src_X\ncbp Ville_X\n"
        "fevt\n#marr 1900\nend fevt\nbeg\n- f Sylvie\nend\n"
    )
    enfant = next(p for p in g.persons.values() if p.first_name == "Sylvie")
    assert enfant.person_source == "Src_X"
    assert enfant.birth_place == "Ville_X"
