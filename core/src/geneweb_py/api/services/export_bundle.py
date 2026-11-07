"""Export complet de la base : une archive zip (voir ``core/doc/exports_design.md``)."""

from collections.abc import Sequence
from datetime import datetime

from ...core.genealogy import Genealogy
from ...core.shared_experiences import SharedExperienceIndex
from ...formats.table_writers import archive_name, base_stem, build_zip
from ...formats.tables import build_base_tables
from .organization_candidates import CandidateIndex
from .organization_exports import candidates_sidecar
from .organization_tables import build_organization_tables


def build_export_bundle(
    genealogy: Genealogy,
    index: CandidateIndex,
    shared: SharedExperienceIndex,
    ignored_words: Sequence[str],
    source_name: str | None,
    now: datetime,
) -> tuple[str, bytes]:
    """``(nom de l'archive, octets)`` : tables de la base et des organisations, compagnon."""
    tables = build_base_tables(genealogy) + build_organization_tables(
        genealogy, index, shared, ignored_words
    )
    companion = candidates_sidecar(genealogy, index)
    companion["ignored_words"] = list(ignored_words)
    data = build_zip(tables, companion, base_stem(source_name), now)
    return archive_name(source_name, now.date()), data
