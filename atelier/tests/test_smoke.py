import geneweb_py

import prosopo_gw_atelier


def test_smoke() -> None:
    assert geneweb_py is not None
    assert prosopo_gw_atelier.__version__ == "0.1.0"
