"""Shared Google OAuth and authenticated HTTP helpers for source connectors."""
from __future__ import annotations

import time
from datetime import datetime, timedelta, timezone
from urllib.parse import urlencode

import requests

from app.config.settings import (GOOGLE_CLIENT_ID, GOOGLE_CLIENT_SECRET,
                                 GOOGLE_HTTP_TIMEOUT_SECONDS,
                                 GOOGLE_SOURCES_ENABLED)
from app.modules.integrations import service as consent
from app.shared.security import vault

AUTH_URL = "https://accounts.google.com/o/oauth2/v2/auth"
TOKEN_URL = "https://oauth2.googleapis.com/token"
REVOKE_URL = "https://oauth2.googleapis.com/revoke"
USERINFO_URL = "https://openidconnect.googleapis.com/v1/userinfo"

SCOPES = {
    "gmail": ["openid", "https://www.googleapis.com/auth/userinfo.email",
              "https://www.googleapis.com/auth/gmail.readonly"],
    "google_drive": ["openid", "https://www.googleapis.com/auth/userinfo.email",
                     "https://www.googleapis.com/auth/drive.readonly"],
}


class GoogleProviderError(RuntimeError):
    """Safe provider error suitable for surfacing at the API boundary."""


def ensure_configured() -> None:
    if not GOOGLE_SOURCES_ENABLED:
        raise GoogleProviderError("Google sources are disabled by configuration.")
    if not GOOGLE_CLIENT_ID or not GOOGLE_CLIENT_SECRET:
        raise GoogleProviderError("Google OAuth is not configured.")


def authorization_url(provider: str, state: str, redirect_uri: str,
                      code_challenge: str) -> str:
    ensure_configured()
    if provider not in SCOPES:
        raise GoogleProviderError("Unsupported Google source.")
    return AUTH_URL + "?" + urlencode({
        "client_id": GOOGLE_CLIENT_ID,
        "redirect_uri": redirect_uri,
        "response_type": "code",
        "scope": " ".join(SCOPES[provider]),
        "state": state,
        "access_type": "offline",
        "prompt": "consent",
        "include_granted_scopes": "false",
        "code_challenge": code_challenge,
        "code_challenge_method": "S256",
    })


def _request(method: str, url: str, **kwargs) -> requests.Response:
    kwargs.setdefault("timeout", GOOGLE_HTTP_TIMEOUT_SECONDS)
    last: requests.Response | None = None
    for attempt in range(3):
        try:
            response = requests.request(method, url, **kwargs)
        except requests.RequestException as exc:
            if attempt == 2:
                raise GoogleProviderError("Google could not be reached.") from exc
            time.sleep(0.2 * (2 ** attempt))
            continue
        last = response
        if response.status_code != 429 and response.status_code < 500:
            return response
        if attempt < 2:
            retry_after = response.headers.get("Retry-After", "")
            try:
                delay = min(float(retry_after), 2.0)
            except ValueError:
                delay = 0.2 * (2 ** attempt)
            time.sleep(delay)
    assert last is not None
    return last


def response_json(response: requests.Response, message: str) -> dict:
    try:
        payload = response.json()
    except (ValueError, TypeError) as exc:
        raise GoogleProviderError(message) from exc
    if not isinstance(payload, dict):
        raise GoogleProviderError(message)
    return payload


def exchange_code(provider: str, code: str, redirect_uri: str,
                  code_verifier: str) -> tuple[dict, dict]:
    ensure_configured()
    response = _request("POST", TOKEN_URL, data={
        "client_id": GOOGLE_CLIENT_ID,
        "client_secret": GOOGLE_CLIENT_SECRET,
        "code": code,
        "code_verifier": code_verifier,
        "grant_type": "authorization_code",
        "redirect_uri": redirect_uri,
    })
    if response.status_code != 200:
        raise GoogleProviderError("Google authorization could not be completed.")
    payload = response_json(response, "Google returned an invalid authorization response.")
    granted = set(str(payload.get("scope", "")).split())
    required = set(SCOPES[provider])
    if not required.issubset(granted) or not payload.get("refresh_token"):
        raise GoogleProviderError("Google did not grant all required offline permissions.")
    profile_response = _request(
        "GET", USERINFO_URL,
        headers={"Authorization": f"Bearer {payload['access_token']}"},
    )
    if profile_response.status_code != 200:
        raise GoogleProviderError("Google account details could not be verified.")
    profile = response_json(profile_response, "Google returned invalid account details.")
    if not profile.get("sub") or not profile.get("email"):
        raise GoogleProviderError("Google did not return a usable account identity.")
    secret = {
        "access_token": payload["access_token"],
        "refresh_token": payload["refresh_token"],
        "access_expires_at": (
            datetime.now(timezone.utc) + timedelta(seconds=int(payload.get("expires_in", 3600)))
        ).isoformat(timespec="seconds"),
        "token_scopes": sorted(granted),
        "google_sub": profile["sub"],
        "email": profile["email"],
    }
    return secret, profile


def access_token(provider: str) -> str:
    consent.require(provider)
    secret = vault.get_secret(provider) or {}
    expires_at = secret.get("access_expires_at", "")
    if secret.get("access_token") and expires_at:
        if datetime.fromisoformat(expires_at) > datetime.now(timezone.utc) + timedelta(seconds=60):
            return str(secret["access_token"])
    if not secret.get("refresh_token"):
        consent.set_status(provider, "reauthorization_required", "missing refresh token")
        raise consent.ConsentError(f"{provider} must be reconnected.")
    response = _request("POST", TOKEN_URL, data={
        "client_id": GOOGLE_CLIENT_ID,
        "client_secret": GOOGLE_CLIENT_SECRET,
        "refresh_token": secret["refresh_token"],
        "grant_type": "refresh_token",
    })
    if response.status_code != 200:
        consent.set_status(provider, "reauthorization_required", "Google refresh rejected")
        raise consent.ConsentError(f"{provider} authorization must be renewed.")
    payload = response_json(response, "Google returned an invalid token response.")
    secret["access_token"] = payload["access_token"]
    secret["access_expires_at"] = (
        datetime.now(timezone.utc) + timedelta(seconds=int(payload.get("expires_in", 3600)))
    ).isoformat(timespec="seconds")
    vault.set_secret(provider, secret)
    return str(secret["access_token"])


def api_request(provider: str, method: str, url: str, **kwargs) -> requests.Response:
    headers = dict(kwargs.pop("headers", {}))
    headers["Authorization"] = f"Bearer {access_token(provider)}"
    response = _request(method, url, headers=headers, **kwargs)
    if response.status_code == 401:
        # Force one refresh before declaring the grant unusable.
        secret = vault.get_secret(provider) or {}
        secret["access_expires_at"] = "1970-01-01T00:00:00+00:00"
        vault.set_secret(provider, secret)
        headers["Authorization"] = f"Bearer {access_token(provider)}"
        response = _request(method, url, headers=headers, **kwargs)
    return response


def disconnect(provider: str) -> None:
    """Revoke remotely only when no sibling source needs this account grant."""
    record = consent.get(provider)
    secret = vault.get_secret(provider) or {}
    google_sub = (record or {}).get("meta", {}).get("google_sub")
    sibling_active = any(
        item["provider"] in SCOPES
        and item["provider"] != provider
        and item["status"] == "active"
        and item.get("meta", {}).get("google_sub") == google_sub
        for item in consent.list_all()
    )
    if not sibling_active and secret.get("refresh_token"):
        try:
            _request("POST", REVOKE_URL, params={"token": secret["refresh_token"]},
                     headers={"Content-Type": "application/x-www-form-urlencoded"})
        except GoogleProviderError:
            # Local revocation must still complete; the Google account revocation
            # URL remains visible to the user.
            pass
    consent.revoke(provider, purge_all=True)
