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


def test_street_of_other_street_types():
    assert street_of("Cité Trévise, Paris") == "Cité Trévise"
    assert street_of("cours la Reine") == "cours la Reine"
    assert street_of("2 allée des Cygnes") == "allée des Cygnes"
    assert street_of("cul-de-sac Saint-Pierre") == "cul-de-sac Saint-Pierre"
    assert street_of("cloître Saint-Merri, 1er") == "cloître Saint-Merri"
    assert street_of("Chaussée d'Antin") == "Chaussée d'Antin"
    assert street_of("place du Marché") == "place du Marché"


def test_street_key_other_street_types():
    assert street_key("Cité Trévise") == "cite trevise"
    assert street_key("cours la Reine") == "cours reine"
    assert street_key("Chaussée d'Antin") == "chaussee antin"


def test_street_key_short_abbreviation_only_first():
    assert street_key("rue Pierre Q. Dupont") == "rue pierre q dupont"
    assert street_key("pl. du Marché") == "place marche"
