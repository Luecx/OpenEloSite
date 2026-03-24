from __future__ import annotations

import json
import urllib.error
import urllib.request
from pathlib import Path


class ServerClient:
    def __init__(self, server_url: str, access_key: str):
        self.server_url = server_url.rstrip("/")
        self.access_key = access_key.strip()
        if not self.server_url:
            raise ValueError("server URL fehlt")
        if not self.access_key:
            raise ValueError("access key fehlt")

    def post(self, path: str, payload: dict) -> dict:
        request = urllib.request.Request(
            url=self._url(path),
            data=json.dumps(payload).encode("utf-8"),
            headers=self._headers({"Content-Type": "application/json"}),
            method="POST",
        )
        return self._read_json(request)

    def download(self, path: str, target_path: Path) -> dict[str, str]:
        request = urllib.request.Request(url=self._url(path), headers=self._headers(), method="GET")
        try:
            with urllib.request.urlopen(request) as response:
                target_path.parent.mkdir(parents=True, exist_ok=True)
                target_path.write_bytes(response.read())
                return {
                    "content_disposition": response.headers.get("Content-Disposition", ""),
                    "content_type": response.headers.get("Content-Type", ""),
                }
        except urllib.error.HTTPError as error:
            raise RuntimeError(self._http_error_message(error)) from error

    def _url(self, path: str) -> str:
        if path.startswith("http://") or path.startswith("https://"):
            return path
        return f"{self.server_url}{path}"

    def _headers(self, extra: dict[str, str] | None = None) -> dict[str, str]:
        headers = {"Authorization": f"Bearer {self.access_key}"}
        if extra:
            headers.update(extra)
        return headers

    def _read_json(self, request: urllib.request.Request) -> dict:
        try:
            with urllib.request.urlopen(request) as response:
                return json.loads(response.read().decode("utf-8"))
        except urllib.error.HTTPError as error:
            raise RuntimeError(self._http_error_message(error)) from error

    def _http_error_message(self, error: urllib.error.HTTPError) -> str:
        body = error.read().decode("utf-8", errors="ignore").strip()
        return f"Serverfehler {error.code}: {body or error.reason}"
