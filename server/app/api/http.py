from __future__ import annotations

from urllib.parse import quote

from fastapi.responses import RedirectResponse


def redirect_to(path: str, message: str | None = None) -> RedirectResponse:
    target = path if message is None else f"{path}?message={quote(message)}"
    return RedirectResponse(url=target, status_code=303)

