from __future__ import annotations

import time
from typing import Any

import requests


class SlskdError(RuntimeError):
    pass


class SlskdClient:
    """Client minimal de l'API REST v0 de slskd.

    L'instance expose sa spécification OpenAPI : {base_url}/swagger/v1/swagger.json
    """

    def __init__(self, base_url: str, api_key: str, timeout: float = 30.0):
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout
        self.session = requests.Session()
        if api_key:
            self.session.headers["X-API-Key"] = api_key

    # ------------------------------------------------------------------ HTTP
    def _request(self, method: str, path: str, **kwargs: Any) -> Any:
        url = f"{self.base_url}{path}"
        try:
            response = self.session.request(method, url, timeout=self.timeout, **kwargs)
        except requests.RequestException as exc:
            raise SlskdError(f"slskd injoignable ({url}) : {exc}") from exc
        if response.status_code >= 400:
            body = response.text[:300]
            raise SlskdError(f"{method} {path} -> HTTP {response.status_code} : {body}")
        if response.status_code == 204 or not response.content:
            return None
        try:
            return response.json()
        except ValueError:
            return response.text

    # ------------------------------------------------------------- état app
    def application_state(self) -> dict:
        return self._request("GET", "/api/v0/application") or {}

    def server_state(self) -> dict:
        return self._request("GET", "/api/v0/server") or {}

    def is_logged_in(self) -> bool:
        state = self.server_state()
        return bool(state.get("isLoggedIn"))

    def wait_for_login(
        self, timeout_s: float | None = 900, poll_s: float = 5.0, log=print
    ) -> bool:
        """Attend que slskd soit connecté au serveur Soulseek (ou timeout)."""
        deadline = None if timeout_s is None else time.monotonic() + float(timeout_s)
        announced = False
        while True:
            try:
                if self.is_logged_in():
                    if announced:
                        log("slskd reconnecté au serveur Soulseek")
                    return True
            except SlskdError:
                pass
            if not announced:
                announced = True
            if deadline is not None and time.monotonic() >= deadline:
                return False
            time.sleep(poll_s)

    # --------------------------------------------------------------- recherche
    def start_search(self, text: str) -> str:
        data = self._request("POST", "/api/v0/searches", json={"searchText": text})
        if isinstance(data, dict):
            search_id = data.get("id") or data.get("token")
        else:
            search_id = data
        if not search_id:
            raise SlskdError(f"Réponse de recherche inattendue : {data!r}")
        return str(search_id)

    def search_state(self, search_id: str) -> dict:
        return self._request("GET", f"/api/v0/searches/{search_id}") or {}

    def search_responses(self, search_id: str) -> dict:
        data = self._request("GET", f"/api/v0/searches/{search_id}/responses")
        if isinstance(data, list):
            return {"responses": data}
        return data or {}

    def wait_for_search(
        self, search_id: str, timeout_s: float = 35.0, poll_s: float = 1.0
    ) -> dict:
        """Attend la fin d'une recherche et renvoie ses réponses."""
        deadline = time.monotonic() + timeout_s
        while True:
            try:
                state = self.search_state(search_id)
            except SlskdError:
                break
            # slskd renvoie des états composés, ex: 'Completed, ResponseLimitReached'.
            current = str(state.get("state") or "").lower()
            if any(part.strip() in ("completed", "cancelled", "removed") for part in current.split(",")):
                break
            if time.monotonic() >= deadline:
                break
            time.sleep(poll_s)
        return self.search_responses(search_id)

    def delete_search(self, search_id: str) -> None:
        try:
            self._request("DELETE", f"/api/v0/searches/{search_id}")
        except SlskdError:
            pass

    # ------------------------------------------------------------ transferts
    def enqueue_download(self, username: str, files: list[dict]) -> Any:
        return self._request(
            "POST", f"/api/v0/transfers/downloads/{username}", json=files
        )

    def downloads(self) -> Any:
        return self._request("GET", "/api/v0/transfers/downloads")

    def cancel_download(self, username: str, transfer_id: str, remove: bool = False) -> None:
        suffix = "?remove=true" if remove else ""
        try:
            self._request(
                "DELETE", f"/api/v0/transfers/downloads/{username}/{transfer_id}{suffix}"
            )
        except SlskdError:
            pass
