"""
Construction des charges utiles Person pour les réponses API.
"""

from ..core.person import Person
from .models.person import PersonListSchema, PersonSchema
from .serialization import (
    date_to_api_string,
    person_source_fields,
    related_family_ids_for_person,
    stable_event_id,
    title_to_schema,
)


def person_to_person_schema(person: Person) -> PersonSchema:
    """Convertit une personne domaine en schéma API complet."""
    event_ids: list[str] = []
    for idx, ev in enumerate(person.events):
        uid = getattr(ev, "unique_id", None)
        if uid is not None:
            event_ids.append(str(uid))
        else:
            event_ids.append(
                stable_event_id(
                    ev, scope="person", scope_key=person.unique_id, index=idx
                )
            )

    return PersonSchema(
        id=person.unique_id,
        first_name=person.first_name,
        surname=person.last_name,
        public_name=person.public_name,
        titles=[title_to_schema(t) for t in person.titles],
        image=person.image_path,
        sex=person.gender,
        access_level=person.access_level,
        birth_date=date_to_api_string(person.birth_date),
        birth_place=person.birth_place,
        death_date=date_to_api_string(person.death_date),
        death_place=person.death_place,
        death_cause=None,
        burial_date=None,
        burial_place=person.burial_place,
        baptism_date=date_to_api_string(person.baptism_date),
        baptism_place=person.baptism_place,
        notes=person.notes,
        sources=person_source_fields(person),
        families=list(person.get_families()),
        related_families=related_family_ids_for_person(person),
        events=event_ids,
    )


def person_to_list_schema(person: Person) -> PersonListSchema:
    """Schéma liste avec dates sérialisées."""
    return PersonListSchema(
        id=person.unique_id,
        first_name=person.first_name,
        surname=person.last_name,
        public_name=person.public_name,
        birth_date=date_to_api_string(person.birth_date),
        death_date=date_to_api_string(person.death_date),
        sex=person.gender,
        access_level=person.access_level,
    )
