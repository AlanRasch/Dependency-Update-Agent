"""Looks up the latest released version of a package on PyPI or npm."""

from __future__ import annotations

import json
import urllib.request
from typing import Any, Callable
from urllib.parse import quote

PYPI_URL = "https://pypi.org/pypi/{name}/json"
NPM_URL = "https://registry.npmjs.org/{name}/latest"


def _http_json(url: str) -> dict[str, Any]:
    request = urllib.request.Request(url, headers={"User-Agent": "depagent/1.0", "Accept": "application/json"})
    with urllib.request.urlopen(request, timeout=10) as response:
        return json.loads(response.read().decode("utf-8"))


class Registry:
    """Caches lookups. Pass `fetch` in tests to avoid the network."""

    def __init__(self, fetch: Callable[[str], dict[str, Any]] | None = None):
        self._fetch = fetch or _http_json
        self._cache: dict[tuple[str, str], str | None] = {}

    def latest(self, ecosystem: str, name: str) -> str | None:
        key = (ecosystem, name)
        if key not in self._cache:
            self._cache[key] = self._lookup(ecosystem, name)
        return self._cache[key]

    def _lookup(self, ecosystem: str, name: str) -> str | None:
        try:
            if ecosystem == "pypi":
                return self._fetch(PYPI_URL.format(name=quote(name)))["info"]["version"]
            return self._fetch(NPM_URL.format(name=quote(name, safe="@")))["version"]
        except Exception:  # network down, unknown package, unexpected reply
            return None
