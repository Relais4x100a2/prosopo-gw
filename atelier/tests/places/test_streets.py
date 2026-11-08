from prosopo_gw_atelier.places.streets import street_key, street_of


def test_street_of_complement():
    assert street_of("12, rue Saint-Honoré") == "rue Saint-Honoré"
    assert street_of("chez son père, 5 rue de la Paix, 2e étage") == "rue de la Paix"
    assert street_of("hôpital de la Charité") is None
    assert street_of(None) is None


def test_street_of_edge_cases():
    assert street_of("12 bis rue de Vaugirard") == "rue de Vaugirard"
    assert street_of("") is None
    assert street_of("12") is None
    assert street_of("rue") is None
    assert street_of("rue de la Paix n° 5") == "rue de la Paix"
    assert street_of("3 bd. Saint Germain (3e étage)") == "bd. Saint Germain"


def test_street_key_abbreviations():
    assert (
        street_key("12 r. St-Honoré")
        == street_key("rue Saint-Honoré")
        == "rue saint honore"
    )
    assert street_key("bd. Saint Germain") == "boulevard saint germain"
    assert street_key("faub. St Antoine") == street_key(
        "rue du Faubourg-Saint-Antoine"
    ).removeprefix("rue ")
    assert street_key("rue de la Paix n° 5") == "rue paix"


def test_street_key_edge_cases():
    assert street_key("12 bis rue de l'Arbre-Sec") == "rue arbre sec"
    assert street_key("12 ter, rue X") == "rue x"
    assert street_key("") == ""
    assert street_key("12") == ""
    assert street_key("rue de la Paix no 5") == "rue paix"
    assert street_key("rue du 4 Septembre") == "rue 4 septembre"
    assert street_key("av. d'Italie") == "avenue italie"
    assert street_key("imp. des Boeufs") == street_key("impasse des Bœufs")
