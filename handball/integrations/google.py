from __future__ import annotations

import base64
import ctypes
import hashlib
import json
import os
from ctypes import wintypes
from pathlib import Path
from typing import Any, Mapping, Protocol
from urllib.parse import quote, urlencode

import httpx


GOOGLE_SCOPES = (
    "openid",
    "email",
    "https://www.googleapis.com/auth/calendar.app.created",
    "https://www.googleapis.com/auth/calendar.acls",
)
GOOGLE_AUTHORIZATION_ENDPOINT = "https://accounts.google.com/o/oauth2/v2/auth"
GOOGLE_TOKEN_ENDPOINT = "https://oauth2.googleapis.com/token"
GOOGLE_REVOCATION_ENDPOINT = "https://oauth2.googleapis.com/revoke"
GOOGLE_USERINFO_ENDPOINT = "https://openidconnect.googleapis.com/v1/userinfo"
GOOGLE_CALENDAR_ENDPOINT = "https://www.googleapis.com/calendar/v3"


class GoogleIntegrationError(RuntimeError):
    def __init__(self, code: str, message: str, *, retryable: bool = False) -> None:
        super().__init__(message)
        self.code = code
        self.retryable = bool(retryable)


class TokenVault(Protocol):
    def save(self, reference: str, token: Mapping[str, Any]) -> None: ...

    def load(self, reference: str) -> dict[str, Any]: ...

    def delete(self, reference: str) -> None: ...


class MemoryTokenVault:
    """Cofre in-memory usado somente em testes."""

    def __init__(self) -> None:
        self._tokens: dict[str, dict[str, Any]] = {}

    def save(self, reference: str, token: Mapping[str, Any]) -> None:
        self._tokens[str(reference)] = dict(token)

    def load(self, reference: str) -> dict[str, Any]:
        try:
            return dict(self._tokens[str(reference)])
        except KeyError as exc:
            raise GoogleIntegrationError(
                "google.credential_missing",
                "A credencial Google não foi encontrada. Reconecte a conta.",
            ) from exc

    def delete(self, reference: str) -> None:
        self._tokens.pop(str(reference), None)


class _DataBlob(ctypes.Structure):
    _fields_ = [("cbData", wintypes.DWORD), ("pbData", ctypes.POINTER(ctypes.c_byte))]


def _blob_from_bytes(value: bytes) -> tuple[_DataBlob, Any]:
    buffer = ctypes.create_string_buffer(value)
    blob = _DataBlob(len(value), ctypes.cast(buffer, ctypes.POINTER(ctypes.c_byte)))
    return blob, buffer


class FileTokenVault:
    """Arquivos DPAPI machine-bound, fora de banco, release e Git."""

    _CRYPTPROTECT_LOCAL_MACHINE = 0x4
    _CRYPTPROTECT_UI_FORBIDDEN = 0x1

    def __init__(self, root: Path, *, entropy: str) -> None:
        self.root = Path(root)
        self._entropy = hashlib.sha256(entropy.encode("utf-8")).digest()

    @staticmethod
    def _safe_name(reference: str) -> str:
        value = str(reference).strip()
        if not value or any(char not in "0123456789abcdef-" for char in value.casefold()):
            raise GoogleIntegrationError(
                "google.credential_reference_invalid",
                "A referência segura da credencial é inválida.",
            )
        return value.casefold() + ".bin"

    def _path(self, reference: str) -> Path:
        return self.root / self._safe_name(reference)

    def _protect(self, value: bytes) -> bytes:
        if os.name != "nt":
            raise GoogleIntegrationError(
                "google.dpapi_unavailable",
                "O cofre Google requer o servidor Windows configurado.",
            )
        source, source_buffer = _blob_from_bytes(value)
        entropy, entropy_buffer = _blob_from_bytes(self._entropy)
        output = _DataBlob()
        crypt32 = ctypes.windll.crypt32
        kernel32 = ctypes.windll.kernel32
        ok = crypt32.CryptProtectData(
            ctypes.byref(source),
            "Crepaldi Handball Google token",
            ctypes.byref(entropy),
            None,
            None,
            self._CRYPTPROTECT_LOCAL_MACHINE | self._CRYPTPROTECT_UI_FORBIDDEN,
            ctypes.byref(output),
        )
        if not ok:
            raise ctypes.WinError()
        try:
            return ctypes.string_at(output.pbData, output.cbData)
        finally:
            kernel32.LocalFree(output.pbData)

    def _unprotect(self, value: bytes) -> bytes:
        if os.name != "nt":
            raise GoogleIntegrationError(
                "google.dpapi_unavailable",
                "O cofre Google requer o servidor Windows configurado.",
            )
        source, source_buffer = _blob_from_bytes(value)
        entropy, entropy_buffer = _blob_from_bytes(self._entropy)
        output = _DataBlob()
        crypt32 = ctypes.windll.crypt32
        kernel32 = ctypes.windll.kernel32
        ok = crypt32.CryptUnprotectData(
            ctypes.byref(source),
            None,
            ctypes.byref(entropy),
            None,
            None,
            self._CRYPTPROTECT_UI_FORBIDDEN,
            ctypes.byref(output),
        )
        if not ok:
            raise GoogleIntegrationError(
                "google.credential_unreadable",
                "A credencial não pode ser lida neste servidor. Reconecte a conta.",
            )
        try:
            return ctypes.string_at(output.pbData, output.cbData)
        finally:
            kernel32.LocalFree(output.pbData)

    def save(self, reference: str, token: Mapping[str, Any]) -> None:
        self.root.mkdir(parents=True, exist_ok=True)
        encoded = json.dumps(
            dict(token), ensure_ascii=False, sort_keys=True, separators=(",", ":")
        ).encode("utf-8")
        destination = self._path(reference)
        temporary = destination.with_suffix(".tmp")
        temporary.write_bytes(self._protect(encoded))
        temporary.replace(destination)

    def load(self, reference: str) -> dict[str, Any]:
        path = self._path(reference)
        if not path.is_file():
            raise GoogleIntegrationError(
                "google.credential_missing",
                "A credencial Google não foi encontrada. Reconecte a conta.",
            )
        try:
            return json.loads(self._unprotect(path.read_bytes()).decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise GoogleIntegrationError(
                "google.credential_invalid",
                "A credencial Google está inválida. Reconecte a conta.",
            ) from exc

    def delete(self, reference: str) -> None:
        path = self._path(reference)
        if path.exists():
            path.unlink()


class _GoogleHttpClient:
    def __init__(self, *, transport: httpx.BaseTransport | None = None) -> None:
        self._transport = transport

    def _client(self) -> httpx.Client:
        return httpx.Client(
            timeout=httpx.Timeout(15.0, connect=8.0),
            follow_redirects=False,
            transport=self._transport,
        )

    def _request(self, method: str, url: str, **kwargs: Any) -> httpx.Response:
        try:
            with self._client() as client:
                return client.request(method, url, **kwargs)
        except httpx.HTTPError as exc:
            raise GoogleIntegrationError(
                "google.network",
                "Não foi possível falar com o Google agora.",
                retryable=True,
            ) from exc

    @staticmethod
    def _error(response: httpx.Response, fallback: str) -> GoogleIntegrationError:
        try:
            payload = response.json()
        except ValueError:
            payload = {}
        detail = payload.get("error") if isinstance(payload, dict) else None
        if isinstance(detail, dict):
            reason = str(detail.get("status") or detail.get("message") or fallback)
        else:
            reason = str(detail or fallback)
        code = f"google.http_{response.status_code}"
        if response.status_code == 401:
            code = "google.reauth_required"
        return GoogleIntegrationError(
            code,
            reason[:500],
            retryable=response.status_code in {408, 429, 500, 502, 503, 504},
        )


class GoogleOAuthClient(_GoogleHttpClient):
    def __init__(
        self,
        *,
        client_id: str,
        client_secret: str,
        redirect_uri: str,
        transport: httpx.BaseTransport | None = None,
    ) -> None:
        super().__init__(transport=transport)
        self.client_id = client_id
        self.client_secret = client_secret
        self.redirect_uri = redirect_uri

    def authorization_url(
        self,
        *,
        state: str,
        code_challenge: str,
        login_hint: str | None = None,
    ) -> str:
        query: dict[str, str] = {
            "client_id": self.client_id,
            "redirect_uri": self.redirect_uri,
            "response_type": "code",
            "scope": " ".join(GOOGLE_SCOPES),
            "access_type": "offline",
            "include_granted_scopes": "true",
            "prompt": "consent select_account",
            "state": state,
            "code_challenge": code_challenge,
            "code_challenge_method": "S256",
        }
        if login_hint:
            query["login_hint"] = login_hint
        return GOOGLE_AUTHORIZATION_ENDPOINT + "?" + urlencode(query)

    def exchange_code(self, *, code: str, code_verifier: str) -> dict[str, Any]:
        try:
            with self._client() as client:
                response = client.post(
                    GOOGLE_TOKEN_ENDPOINT,
                    data={
                        "client_id": self.client_id,
                        "client_secret": self.client_secret,
                        "code": code,
                        "code_verifier": code_verifier,
                        "grant_type": "authorization_code",
                        "redirect_uri": self.redirect_uri,
                    },
                )
        except httpx.HTTPError as exc:
            raise GoogleIntegrationError(
                "google.network",
                "Não foi possível falar com o Google agora.",
                retryable=True,
            ) from exc
        if response.is_error:
            raise self._error(response, "O Google recusou a autorização.")
        payload = response.json()
        if not payload.get("access_token"):
            raise GoogleIntegrationError(
                "google.token_missing",
                "O Google não retornou uma credencial válida.",
            )
        return dict(payload)

    def refresh_access_token(self, refresh_token: str) -> dict[str, Any]:
        try:
            with self._client() as client:
                response = client.post(
                    GOOGLE_TOKEN_ENDPOINT,
                    data={
                        "client_id": self.client_id,
                        "client_secret": self.client_secret,
                        "refresh_token": refresh_token,
                        "grant_type": "refresh_token",
                    },
                )
        except httpx.HTTPError as exc:
            raise GoogleIntegrationError(
                "google.network",
                "Não foi possível renovar a conexão Google agora.",
                retryable=True,
            ) from exc
        if response.is_error:
            error = self._error(response, "A conexão Google precisa ser refeita.")
            try:
                if response.json().get("error") == "invalid_grant":
                    error = GoogleIntegrationError(
                        "google.reauth_required",
                        "A autorização expirou ou foi removida. Reconecte a conta.",
                    )
            except ValueError:
                pass
            raise error
        return dict(response.json())

    def user_identity(self, access_token: str) -> dict[str, str]:
        response = self._request(
            "GET",
            GOOGLE_USERINFO_ENDPOINT,
            headers={"Authorization": f"Bearer {access_token}"},
        )
        if response.is_error:
            raise self._error(response, "Não foi possível identificar a conta Google.")
        payload = response.json()
        subject = str(payload.get("sub") or "")
        email = str(payload.get("email") or "").strip().casefold()
        if not subject or not email:
            raise GoogleIntegrationError(
                "google.identity_missing",
                "O Google não informou qual conta foi autorizada.",
            )
        return {"sub": subject, "email": email}

    def revoke(self, token: str) -> bool:
        try:
            with self._client() as client:
                response = client.post(
                    GOOGLE_REVOCATION_ENDPOINT,
                    data={"token": token},
                )
        except httpx.HTTPError:
            return False
        return response.status_code in {200, 400}


class GoogleCalendarClient(_GoogleHttpClient):
    @staticmethod
    def _headers(access_token: str) -> dict[str, str]:
        return {
            "Authorization": f"Bearer {access_token}",
            "Accept": "application/json",
            "Content-Type": "application/json",
        }

    def create_calendar(self, access_token: str, name: str) -> dict[str, Any]:
        response = self._request(
            "POST",
            f"{GOOGLE_CALENDAR_ENDPOINT}/calendars",
            headers=self._headers(access_token),
            json={
                "summary": name,
                "description": "Agenda pública atualizada pelo Handball.",
                "timeZone": "America/Sao_Paulo",
            },
        )
        if response.is_error:
            raise self._error(response, "Não foi possível criar o calendário Google.")
        return dict(response.json())

    def make_public(self, access_token: str, calendar_id: str) -> None:
        encoded = quote(calendar_id, safe="")
        response = self._request(
            "POST",
            f"{GOOGLE_CALENDAR_ENDPOINT}/calendars/{encoded}/acl",
            headers=self._headers(access_token),
            params={"sendNotifications": "false"},
            json={"scope": {"type": "default"}, "role": "reader"},
        )
        if response.status_code == 409:
            return
        if response.is_error:
            raise self._error(response, "Não foi possível tornar o calendário público.")

    def make_private(self, access_token: str, calendar_id: str) -> None:
        encoded = quote(calendar_id, safe="")
        response = self._request(
            "DELETE",
            f"{GOOGLE_CALENDAR_ENDPOINT}/calendars/{encoded}/acl/default",
            headers=self._headers(access_token),
        )
        if response.status_code == 404:
            return
        if response.is_error:
            raise self._error(response, "Não foi possível tornar o calendário privado.")

    @staticmethod
    def public_url(calendar_id: str) -> str:
        return "https://calendar.google.com/calendar/embed?" + urlencode(
            {"src": calendar_id, "ctz": "America/Sao_Paulo"}
        )

    def upsert_event(
        self,
        access_token: str,
        *,
        calendar_id: str,
        google_event_id: str,
        event: Mapping[str, Any],
    ) -> dict[str, Any]:
        calendar = quote(calendar_id, safe="")
        event_id = quote(google_event_id, safe="")
        url = f"{GOOGLE_CALENDAR_ENDPOINT}/calendars/{calendar}/events/{event_id}"
        headers = self._headers(access_token)
        current = self._request("GET", url, headers=headers)
        if current.status_code == 404:
            response = self._request(
                "POST",
                f"{GOOGLE_CALENDAR_ENDPOINT}/calendars/{calendar}/events",
                headers=headers,
                json={"id": google_event_id, **dict(event)},
            )
        elif current.is_error:
            raise self._error(current, "Não foi possível consultar o evento Google.")
        else:
            response = self._request(
                "PUT", url, headers=headers, json=dict(event)
            )
        if response.status_code == 409:
            response = self._request(
                "PUT", url, headers=headers, json=dict(event)
            )
        if response.is_error:
            raise self._error(response, "Não foi possível atualizar o evento Google.")
        return dict(response.json())

    def delete_event(
        self,
        access_token: str,
        *,
        calendar_id: str,
        google_event_id: str,
    ) -> None:
        calendar = quote(calendar_id, safe="")
        event_id = quote(google_event_id, safe="")
        response = self._request(
            "DELETE",
            f"{GOOGLE_CALENDAR_ENDPOINT}/calendars/{calendar}/events/{event_id}",
            headers=self._headers(access_token),
        )
        if response.status_code in {404, 410}:
            return
        if response.is_error:
            raise self._error(response, "Não foi possível retirar o evento Google.")


def pkce_challenge(verifier: str) -> str:
    digest = hashlib.sha256(verifier.encode("ascii")).digest()
    return base64.urlsafe_b64encode(digest).rstrip(b"=").decode("ascii")
