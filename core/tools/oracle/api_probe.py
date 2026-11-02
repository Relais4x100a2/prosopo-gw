"""Sonde de l'API REST sur une base réelle : routes de personnes et d'événements.

Usage : python api_probe.py <base.gw>

Sortie : une ligne ``route | statut | durée`` par appel. Toute exception serveur est imprimée
avec ses trames ``fichier:ligne`` et un message masqué (lettres -> « a », chiffres -> « 9 »).
Aucun nom, lieu ou date de la base n'est affiché.
"""

from __future__ import annotations

import collections
import logging
import sys
import time
import traceback
from typing import Any
from urllib.parse import quote

from fastapi.testclient import TestClient

from geneweb_py.api.main import app
from geneweb_py.api.rate_limit import limiter
from oracle.compare import mask

BASE = "/api/v1"


def _first(obj: Any, key: str) -> Any:
    """Première valeur de ``key`` dans une structure JSON imbriquée."""
    if isinstance(obj, dict):
        if key in obj:
            return obj[key]
        for v in obj.values():
            found = _first(v, key)
            if found is not None:
                return found
    elif isinstance(obj, list):
        for v in obj:
            found = _first(v, key)
            if found is not None:
                return found
    return None


def _print_trace(exc: BaseException) -> None:
    frames = traceback.extract_tb(exc.__traceback__)
    print(f"  {type(exc).__name__}: {mask(str(exc))}")
    for fr in frames[-6:]:
        print(f"    {fr.filename.split('/src/')[-1]}:{fr.lineno} in {fr.name}")


def call(client: TestClient, label: str, method: str, url: str, **kw: Any) -> Any:
    start = time.perf_counter()
    try:
        resp = client.request(method, url, **kw)
    except Exception as exc:  # noqa: BLE001 : on veut la trace de toute exception serveur
        print(f"{label} | EXCEPTION | {time.perf_counter() - start:.1f}s")
        _print_trace(exc)
        return None
    print(f"{label} | {resp.status_code} | {time.perf_counter() - start:.1f}s")
    if resp.status_code >= 400:
        print(f"  corps masqué : {mask(resp.text)}")
    try:
        return resp.json()
    except ValueError:
        return None


def main(path: str) -> int:
    limiter.enabled = False
    logging.disable(logging.CRITICAL)
    with TestClient(app, raise_server_exceptions=True) as client:
        return _probe(client, path)


def _probe(client: TestClient, path: str) -> int:
    with open(path, "rb") as f:
        created = call(
            client,
            "POST /sessions",
            "POST",
            f"{BASE}/sessions/",
            files={"file": ("base.gw", f, "application/octet-stream")},
        )
    token = _first(created, "session_token")
    if not token:
        print("pas de session : arrêt")
        return 1
    headers = {"X-Session-Token": token}
    people = call(
        client,
        "GET /persons?size=1",
        "GET",
        f"{BASE}/persons/",
        params={"size": 1},
        headers=headers,
    )
    person_id = _first(people, "id") or _first(people, "person_id")
    first_name = _first(people, "first_name")
    if not person_id:
        print("aucune personne exposée : arrêt")
        return 1
    q = {"query": first_name} if first_name else {}
    call(
        client,
        "GET /persons?query",
        "GET",
        f"{BASE}/persons/",
        params=q,
        headers=headers,
    )
    call(
        client,
        "GET /persons/{id}",
        "GET",
        f"{BASE}/persons/{person_id}",
        headers=headers,
    )
    call(
        client,
        "GET /persons/{id}/families",
        "GET",
        f"{BASE}/persons/{person_id}/families",
        headers=headers,
    )
    call(
        client,
        "GET /persons/{id}/events",
        "GET",
        f"{BASE}/persons/{person_id}/events",
        headers=headers,
    )
    call(
        client,
        "GET /events?person_id",
        "GET",
        f"{BASE}/events/",
        params={"person_id": person_id},
        headers=headers,
    )
    call(
        client, "GET /events?query", "GET", f"{BASE}/events/", params=q, headers=headers
    )
    call(
        client,
        "GET /events?size=100",
        "GET",
        f"{BASE}/events/",
        params={"size": 100},
        headers=headers,
    )
    call(
        client,
        "GET /events/stats/overview",
        "GET",
        f"{BASE}/events/stats/overview",
        headers=headers,
    )
    call(
        client,
        "GET /families",
        "GET",
        f"{BASE}/families/",
        params={"size": 100},
        headers=headers,
    )
    _sweep(client, headers)
    _sweep_misc(client, headers)
    return 0


def _count(
    client: TestClient, label: str, url: str, headers: dict[str, str], **kw: Any
) -> None:
    try:
        resp = client.get(url, headers=headers, **kw)
        print(f"{label} | {resp.status_code}")
        if resp.status_code >= 400:
            print(f"  corps masqué : {mask(resp.text)}")
    except Exception as exc:  # noqa: BLE001
        print(f"{label} | EXCEPTION")
        _print_trace(exc)


def _sweep_misc(client: TestClient, headers: dict[str, str]) -> None:
    """Routes de l'interface web : statistiques, familles, filtres d'événements, exports."""
    print("\nroutes de l'interface")
    _count(client, "genealogy/stats", f"{BASE}/genealogy/stats", headers)
    for fmt in ("json", "gedcom", "xml"):
        _count(
            client, f"genealogy/export/{fmt}", f"{BASE}/genealogy/export/{fmt}", headers
        )
    for etype in ("birth", "marriage", "death", "baptism", "occupation"):
        _count(
            client,
            f"events?event_type={etype}",
            f"{BASE}/events/",
            headers,
            params={"event_type": etype, "size": 100},
        )
    _count(
        client,
        "events?place=a",
        f"{BASE}/events/",
        headers,
        params={"place": "a", "size": 100},
    )
    fams: list[dict[str, Any]] = []
    page = 1
    while True:
        resp = client.get(
            f"{BASE}/families/", params={"page": page, "size": 100}, headers=headers
        )
        items = (resp.json() or {}).get("items") or []
        fams.extend(i for i in items if isinstance(i, dict))
        if len(items) < 100:
            break
        page += 1
    status: dict[str, collections.Counter[str]] = collections.defaultdict(
        collections.Counter
    )
    for f in fams[:: max(1, len(fams) // SWEEP_SIZE)]:
        fid = quote(str(f.get("id") or f.get("family_id")), safe="")
        for name, url in (
            ("families/{id}", f"{BASE}/families/{fid}"),
            ("families/{id}/children", f"{BASE}/families/{fid}/children"),
        ):
            try:
                status[name][str(client.get(url, headers=headers).status_code)] += 1
            except Exception as exc:  # noqa: BLE001
                status[name]["EXCEPTION " + type(exc).__name__] += 1
    print(f"familles listées : {len(fams)}")
    for name, counter in status.items():
        print(f"  {name}: {dict(counter)}")


SWEEP_SIZE = 300


def _all_persons(client: TestClient, headers: dict[str, str]) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    page = 1
    while True:
        resp = client.get(
            f"{BASE}/persons/", params={"page": page, "size": 100}, headers=headers
        )
        items = _first(resp.json(), "items") or _first(resp.json(), "data") or []
        if not items:
            return out
        out.extend(i for i in items if isinstance(i, dict))
        page += 1
        if len(items) < 100:
            return out


def _sweep(client: TestClient, headers: dict[str, str]) -> None:
    """Balayage d'un échantillon régulier de personnes : statuts par route, exceptions distinctes."""
    persons = _all_persons(client, headers)
    step = max(1, len(persons) // SWEEP_SIZE)
    sample = persons[::step]
    status: dict[str, collections.Counter[str]] = collections.defaultdict(
        collections.Counter
    )
    traces: dict[str, str] = {}
    not_found: list[str] = []
    for p in sample:
        pid = p.get("id") or p.get("person_id")
        qpid = quote(str(pid), safe="")
        fn = p.get("first_name") or ""
        routes = {
            "persons/{id}": ("GET", f"{BASE}/persons/{qpid}", {}),
            "persons/{id}/families": ("GET", f"{BASE}/persons/{qpid}/families", {}),
            "persons/{id}/events": ("GET", f"{BASE}/persons/{qpid}/events", {}),
            "events?person_id": ("GET", f"{BASE}/events/", {"person_id": pid}),
            "events?query=prénom": ("GET", f"{BASE}/events/", {"query": fn}),
            "persons/{id}/related": (
                "GET",
                f"{BASE}/persons/{qpid}/related",
                {"degree": 2},
            ),
            "persons?query=prénom": (
                "GET",
                f"{BASE}/persons/",
                {"query": fn, "size": 10},
            ),
        }
        for name, (method, url, params) in routes.items():
            try:
                resp = client.request(method, url, params=params, headers=headers)
                status[name][str(resp.status_code)] += 1
                if resp.status_code == 404 and name == "persons/{id}":
                    not_found.append(str(pid))
            except Exception as exc:  # noqa: BLE001
                sig = f"{type(exc).__name__}"
                status[name]["EXCEPTION " + sig] += 1
                if name + sig not in traces:
                    frames = traceback.extract_tb(exc.__traceback__)
                    traces[name + sig] = (
                        f"{name} : {sig}: {mask(str(exc))}\n"
                        + "\n".join(
                            f"    {f.filename.split('/src/')[-1]}:{f.lineno} in {f.name}"
                            for f in frames[-6:]
                        )
                    )
    print(f"\nbalayage : {len(sample)} personnes sur {len(persons)}")
    for name, counter in status.items():
        print(f"  {name}: {dict(counter)}")
    for t in traces.values():
        print("\n" + t)
    if not_found:
        print("\nidentifiants listés mais introuvables (forme masquée) :")
        for pid in not_found:
            print(f"  {mask(pid)}")


if __name__ == "__main__":
    sys.exit(main(sys.argv[1]))
