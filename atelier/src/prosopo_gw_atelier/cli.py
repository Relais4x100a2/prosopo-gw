"""Command ``prosopo-gw-atelier BASE.gw``: open a base in the local atelier.

The server listens on ``127.0.0.1`` only, on ``--port`` or a free port, and
the browser opens once it is up (unless ``--no-browser``). The personal
registry and the projects live in ``--data-dir`` (default: ``data_dir()``,
which ``$PROSOPO_GW_ATELIER_HOME`` overrides): ``referentiel.sqlite`` and
``projets/``. Ctrl+C stops the server; the registry is closed on the way out.
"""

from __future__ import annotations

import argparse
import socket
import sys
import threading
import time
import webbrowser
from collections.abc import Callable, Sequence
from pathlib import Path

from fastapi import FastAPI

from .project import Project
from .refdata import RefData, load_refdata
from .sources import SourceRuntime
from .sources.fetch import Opener
from .store.paths import data_dir
from .store.registry import PlaceRegistry
from .web.app import create_app

HOST = "127.0.0.1"

Launcher = Callable[[FastAPI, int, Callable[[], None]], None]
"""Serves ``app`` on ``port`` and calls the callback once the server is up."""


def free_port() -> int:
    """A port free on ``127.0.0.1`` right now (asked to the system)."""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind((HOST, 0))
        port: int = sock.getsockname()[1]
        return port


def port_is_free(port: int) -> bool:
    """Whether ``port`` can be bound on ``127.0.0.1`` right now."""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        try:
            sock.bind((HOST, port))
        except OSError:
            return False
    return True


def serve(app: FastAPI, port: int, on_started: Callable[[], None]) -> None:
    """Run uvicorn on ``127.0.0.1:port`` until Ctrl+C."""
    import uvicorn

    server = uvicorn.Server(
        uvicorn.Config(app, host=HOST, port=port, log_level="warning")
    )

    def wait_until_started() -> None:
        while not server.started and not server.should_exit:
            time.sleep(0.05)
        if server.started:
            on_started()

    threading.Thread(target=wait_until_started, daemon=True).start()
    server.run()


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="prosopo-gw-atelier",
        description="Ouvre une base GeneWeb (.gw) dans l'atelier local de nettoyage.",
    )
    parser.add_argument("base", type=Path, metavar="BASE.gw", help="base GeneWeb")
    parser.add_argument(
        "--port", type=int, help="port d'écoute (par défaut : un port libre)"
    )
    parser.add_argument(
        "--no-browser",
        action="store_true",
        help="ne pas ouvrir le navigateur",
    )
    parser.add_argument(
        "--data-dir",
        type=Path,
        help="dossier du référentiel personnel et des projets",
    )
    return parser


def main(
    argv: Sequence[str] | None = None,
    *,
    launcher: Launcher = serve,
    open_browser: Callable[[str], object] = webbrowser.open,
    load_ref: Callable[[], RefData] = load_refdata,
    opener: Opener | None = None,
) -> int:
    """Entry point; returns the exit code (2: base not found, bad or busy port)."""
    args = _parser().parse_args(argv)
    base: Path = args.base
    if not base.is_file():
        print(f"Fichier introuvable : {base}", file=sys.stderr)
        return 2
    if args.port is not None and not 0 < args.port < 65536:
        print(f"Port invalide : {args.port}", file=sys.stderr)
        return 2
    if args.port is not None and not port_is_free(args.port):
        print(f"Port {args.port} déjà utilisé", file=sys.stderr)
        return 2
    directory: Path = args.data_dir if args.data_dir is not None else data_dir()
    ref = load_ref()
    with PlaceRegistry(directory / "referentiel.sqlite", ref) as registry:
        try:
            project = Project.open(base, registry, ref, directory / "projets")
        except Exception as exc:  # the parser's errors are not one family
            print(f"Impossible de lire {base} : {exc}", file=sys.stderr)
            return 1
        runtime = SourceRuntime.build(directory, ref, opener=opener)
        app = create_app(project, registry, ref, sources=runtime)
        port = args.port if args.port is not None else free_port()
        url = f"http://{HOST}:{port}/"
        print(f"Atelier ouvert sur {url} (Ctrl+C pour arrêter)", flush=True)

        def on_started() -> None:
            if not args.no_browser:
                open_browser(url)

        launcher(app, port, on_started)
    return 0


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
