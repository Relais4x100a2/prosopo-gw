import pytest

from prosopo_gw_atelier.refdata import normalize


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("ST-OMER", "saint omer"),
        ("Ste  Foy-lès-Lyon", "sainte foy les lyon"),
        ("L'Haÿ-les-Roses", "l hay les roses"),
        ("  Marcq-en-Barœul ", "marcq en baroeul"),
        ("Saint_Pol_sur_Mer", "saint pol sur mer"),
        ("Bastia", "bastia"),
        ("Stenay", "stenay"),
        ("Pont-Ste-Marie", "pont sainte marie"),
        ("L’Isle-Adam", "l isle adam"),
        ("", ""),
    ],
)
def test_normalize(text: str, expected: str) -> None:
    assert normalize(text) == expected
