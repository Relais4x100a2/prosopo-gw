"""Le mode streaming doit lire exactement ce que lit le mode complet.

Jetons (positions comprises) et modèle construit : les lecteurs de ligne brute
s'appuient sur la source, qui doit donc être fournie aussi en streaming.
"""

import json
from pathlib import Path

import pytest

from geneweb_py import GeneWebParser
from geneweb_py.core.parser.lexical import LexicalParser, TokenType
from geneweb_py.core.parser.streaming import StreamingGeneWebParser
from geneweb_py.formats.json import JSONExporter

FIXTURES = sorted((Path(__file__).parent.parent / "fixtures").glob("*.gw"))
VALID_FIXTURES = [p for p in FIXTURES if not p.name.startswith(("error_", "malformed"))]


def _significant(tokens):
    return [
        (t.type.name, t.value, t.line_number, t.position)
        for t in tokens
        if t.type not in (TokenType.EOF,)
    ]


@pytest.mark.parametrize("path", FIXTURES, ids=lambda p: p.name)
def test_streaming_tokens_match_full_lexer(path):
    parser = StreamingGeneWebParser(validate=False)
    text = path.read_text(encoding=parser._detect_encoding(path))
    full = LexicalParser(text).tokenize()
    streamed = list(parser.parse_file_streaming(path))
    assert _significant(streamed) == _significant(full)


@pytest.mark.parametrize("path", FIXTURES, ids=lambda p: p.name)
def test_streaming_keeps_source_text(path):
    parser = StreamingGeneWebParser(validate=False)
    text = path.read_text(encoding=parser._detect_encoding(path))
    list(parser.parse_file_streaming(path))
    assert parser.source_text == text


def _without_object_ids(data):
    # l'export JSON numérote certains objets par ``id()`` : sans intérêt ici
    if isinstance(data, dict):
        return {
            k: _without_object_ids(v)
            for k, v in data.items()
            if not (k == "id" and isinstance(v, int))
        }
    if isinstance(data, list):
        return [_without_object_ids(v) for v in data]
    return data


def _export(genealogy):
    genealogy.metadata.source_file = None
    return _without_object_ids(json.loads(JSONExporter().export_to_string(genealogy)))


@pytest.mark.parametrize("path", VALID_FIXTURES, ids=lambda p: p.name)
def test_streaming_builds_same_genealogy(path):
    normal = GeneWebParser(validate=False, stream_mode=False).parse_file(path)
    flux = GeneWebParser(validate=False, stream_mode=True).parse_file(path)
    assert _export(flux) == _export(normal)


RAW_LINES = """fam DUPONT Jean + MARTIN Marie
src Acte  n°12 "copie"
beg
- h Paul
end

notes-db
Ligne  une
  indentée
end notes-db
"""


def test_streaming_reads_raw_lines_verbatim(tmp_path):
    path = tmp_path / "brut.gw"
    path.write_text(RAW_LINES, encoding="utf-8")
    flux = GeneWebParser(validate=False, stream_mode=True).parse_file(path)
    family = next(iter(flux.families.values()))
    assert family.family_source == 'Acte  n°12 "copie"'
    assert _export(flux) == _export(
        GeneWebParser(validate=False, stream_mode=False).parse_file(path)
    )
