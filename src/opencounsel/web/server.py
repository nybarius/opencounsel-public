from __future__ import annotations

from pathlib import Path

import uvicorn

from opencounsel.web.app import create_app


def run(
    *,
    host: str,
    port: int,
    root: Path,
    libreoffice: str = "libreoffice",
) -> None:
    app = create_app(root=root, libreoffice=libreoffice)
    uvicorn.run(
        app,
        host=host,
        port=port,
        log_level="warning",
        access_log=False,
        server_header=False,
    )


__all__ = ["run"]
