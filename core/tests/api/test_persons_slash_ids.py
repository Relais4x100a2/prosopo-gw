"""Un id de personne contenant « / » reste adressable (encodé en %2F par le front)."""

from unittest.mock import Mock

import pytest
from fastapi.testclient import TestClient

from geneweb_py.api.dependencies import get_session_service
from geneweb_py.api.main import app
from geneweb_py.api.services.genealogy_service import GenealogyService
from geneweb_py.core.models import Gender, Person

ID = "DUPONT_Jean/1_0"


@pytest.fixture
def client_et_service():
    service = Mock(spec=GenealogyService)
    personne = Person(first_name="Jean", last_name="DUPONT", gender=Gender.MALE)
    service.get_person.side_effect = lambda pid: personne if pid == ID else None
    app.dependency_overrides[get_session_service] = lambda: service
    yield TestClient(app), service
    app.dependency_overrides.clear()


@pytest.mark.parametrize("suffixe", ["", "/families"])
def test_id_avec_slash_encode(client_et_service, suffixe):
    client, service = client_et_service
    r = client.get("/api/v1/persons/DUPONT_Jean%2F1_0" + suffixe)
    assert r.status_code == 200
    service.get_person.assert_called_with(ID)


def test_id_inconnu_reste_404(client_et_service):
    client, _ = client_et_service
    assert client.get("/api/v1/persons/AUTRE%2Fx").status_code == 404
