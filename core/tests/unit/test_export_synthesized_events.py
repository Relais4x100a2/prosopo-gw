"""Les événements fabriqués à la gwc ne dupliquent pas les champs exportés."""

from geneweb_py import GeneWebParser
from geneweb_py.formats.gedcom import GEDCOMExporter
from geneweb_py.formats.json import JSONExporter
from geneweb_py.formats.xml import XMLExporter

TEXTE = "fam DUPONT Jean +1900 #mp Ville MARTIN Anne\nbeg\n- h Paul 1925 #bp Lyon\nend\n"


def _export(cls, tmp_path, ext):
    g = GeneWebParser(validate=False).parse_string(TEXTE)
    chemin = tmp_path / f"o.{ext}"
    cls().export(g, str(chemin))
    return chemin.read_text(encoding="utf-8")


def test_gedcom_une_seule_naissance_et_un_seul_mariage(tmp_path):
    texte = _export(GEDCOMExporter, tmp_path, "ged")
    assert texte.count("1 BIRT") == 1
    assert texte.count("1 MARR") == 1


def test_json_et_xml_portent_les_evenements(tmp_path):
    assert '"marr"' in _export(JSONExporter, tmp_path, "json")
    assert 'type="marr"' in _export(XMLExporter, tmp_path, "xml")
