"""Pistes d'organisation dans un texte de note (textes 100 % synthétiques)."""

from geneweb_py.core.note_leads import EXCERPT_MAX, find_note_leads


def test_establishment_word_found() -> None:
    leads = find_note_leads("Il entre à la banque du village en 1890.")
    assert len(leads) == 1
    lead = leads[0]
    assert lead.words == ("banque",)
    assert lead.guessed_type == "company"
    assert lead.strong is False
    assert "banque du village" in lead.excerpt


def test_accented_capitals() -> None:
    (lead,) = find_note_leads("Directeur des ÉTABLISSEMENTS Durand")
    assert lead.words == ("etablissements",)
    assert lead.strong is True


def test_strong_company_name() -> None:
    (strong,) = find_note_leads("Associé de la Société des Forges Fictives.")
    assert strong.strong is True
    (weak,) = find_note_leads("une société de pêche")
    assert weak.strong is False


def test_legal_form_case_sensitive() -> None:
    (lead,) = find_note_leads("Fonde DUPONT SNC avec son frère")
    assert lead.strong is True
    assert lead.words == ("snc",)
    assert find_note_leads("sa femme et sa fille") == []


def test_en_compagnie_de_ignored() -> None:
    assert find_note_leads("Parti en compagnie de son frère") == []
    assert find_note_leads("EN COMPAGNIE D'un ami") == []
    assert len(find_note_leads("Entre à la Compagnie des Mines")) == 1


def test_compagnie_number_is_military() -> None:
    (lead,) = find_note_leads("Sert dans la Compagnie 3 du régiment")
    assert lead.guessed_type == "military"


def test_ignored_word() -> None:
    assert find_note_leads("Travaille à l'usine", ignored_words=["Usine"]) == []


def test_urls_removed() -> None:
    assert find_note_leads("https://usine.example/banque") == []
    (lead,) = find_note_leads("Voir www.banque.example ; employé à l'usine")
    assert "www" not in lead.excerpt
    assert lead.words == ("usine",)


def test_empty_note() -> None:
    for text in ("", "   ", "Né à Villefictive."):
        assert find_note_leads(text) == []


def test_windows_merged() -> None:
    text = "Employé de la banque " + "x " * 50 + "puis entre à l'usine."
    (lead,) = find_note_leads(text)
    assert lead.words == ("banque", "usine")


def test_extract_bounds() -> None:
    spaced = " ".join((["usine"] + ["mot"] * 400) * 3)
    dense = " ".join((["atelier"] + ["mot"] * 25) * 60)
    for text, count in ((spaced, 3), (dense, 60)):
        leads = find_note_leads(text)
        assert leads
        assert all(len(lead.excerpt) <= EXCERPT_MAX for lead in leads)
        for lead in leads:
            for word in lead.words:
                assert word in lead.excerpt
        covered = sum(lead.excerpt.split().count(leads[0].words[0]) for lead in leads)
        assert covered >= count
