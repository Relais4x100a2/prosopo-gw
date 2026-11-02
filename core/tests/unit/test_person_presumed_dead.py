"""Une personne née il y a plus de 120 ans est considérée décédée."""

from datetime import datetime

import pytest

from geneweb_py.core.date import Date
from geneweb_py.core.person import Person

ANNEE = datetime.now().year


def _personne(annee, **kw):
    return Person(
        last_name="DUPONT",
        first_name="Jean",
        birth_date=Date(year=annee) if annee else None,
        **kw,
    )


def test_nee_il_y_a_plus_de_120_ans_est_decedee():
    assert _personne(ANNEE - 121).is_alive is False


def test_nee_il_y_a_120_ans_ou_moins_reste_vivante():
    assert _personne(ANNEE - 120).is_alive is True


def test_sans_date_de_naissance_reste_vivante():
    assert _personne(None).is_alive is True


@pytest.mark.parametrize("etat", [False])
def test_vivante_explicite_prime(etat):
    assert _personne(ANNEE - 130, is_deceased=etat).is_alive is True
