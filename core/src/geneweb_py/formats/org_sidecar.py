"""Fichier compagnon JSON (``base.org.json``) pour les organisations.

Niveau 1 de la spécification : le ``.gw`` n'est jamais modifié ; les organisations et
leurs liens vivent à côté, référencés par identifiant de personne.
"""

import json
from pathlib import Path
from typing import Any, Collection, Dict, Optional, Tuple, Union

from ..core.exceptions import GeneWebValidationError
from ..core.genealogy import Genealogy
from ..core.organization import Organization, OrganizationLink

SIDECAR_VERSION = 1

PathLike = Union[str, Path]


def sidecar_path_for(gw_path: PathLike) -> Path:
    """Chemin du fichier compagnon d'un ``.gw`` (``base.gw`` -> ``base.org.json``)."""
    return Path(gw_path).with_suffix(".org.json")


def sidecar_payload(
    genealogy: Genealogy, organization_ids: Optional[Collection[str]] = None
) -> Dict[str, Any]:
    """Contenu du fichier compagnon ; avec ``organization_ids``, seules ces organisations.

    Avec un filtre, ne sont gardés que les organisations listées et les liens qui les
    pointent. ``None`` désigne toutes les organisations.
    """
    wanted = None if organization_ids is None else set(organization_ids)
    organizations = [
        o for o in genealogy.organizations.values() if wanted is None or o.id in wanted
    ]
    links = [
        link
        for link in genealogy.organization_links
        if wanted is None or link.organization_id in wanted
    ]
    return {
        "version": SIDECAR_VERSION,
        "organizations": [o.to_dict() for o in organizations],
        "links": [link.to_dict() for link in links],
    }


def export_organizations(genealogy: Genealogy, path: PathLike) -> Path:
    """Écrit les organisations et liens de la généalogie dans ``path`` (UTF-8)."""
    payload = sidecar_payload(genealogy)
    target = Path(path)
    target.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    return target


def import_organizations(genealogy: Genealogy, path: PathLike) -> Tuple[int, int]:
    """Charge un fichier compagnon dans la généalogie.

    Un fichier absent est sans effet.

    Returns:
        (nombre d'organisations, nombre de liens) importés.

    Raises:
        GeneWebValidationError: JSON invalide, ou lien vers une personne inconnue.
    """
    source = Path(path)
    if not source.is_file():
        return (0, 0)

    try:
        payload = json.loads(source.read_text(encoding="utf-8"))
        organizations = [Organization.from_dict(d) for d in payload["organizations"]]
        links = [OrganizationLink.from_dict(d) for d in payload.get("links", [])]
    except (ValueError, KeyError, TypeError) as exc:
        raise GeneWebValidationError(
            f"Fichier compagnon invalide ({source.name}): {exc}",
            context=str(source),
        ) from exc

    for org in organizations:
        genealogy.add_organization(org)
    for link in links:
        genealogy.link_person_to_organization(
            link.person_id,
            link.organization_id,
            role=link.role,
            start_date=link.start_date,
            end_date=link.end_date,
            source_event_id=link.source_event_id,
            source_event_type=link.source_event_type,
            notes=link.notes,
        )
    return (len(organizations), len(links))


def load_sidecar_for(genealogy: Genealogy, gw_path: PathLike) -> Tuple[int, int]:
    """Charge le compagnon d'un ``.gw`` s'il existe ; sinon ne fait rien."""
    return import_organizations(genealogy, sidecar_path_for(gw_path))
