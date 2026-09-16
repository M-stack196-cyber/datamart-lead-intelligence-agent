from __future__ import annotations

import base64
import hashlib
import hmac
import json
import secrets
from datetime import datetime, timedelta, timezone
from typing import Any
from urllib.parse import urlencode

import httpx

from app.core.config import Settings
from app.integrations.gmail import GmailDeliveryError


GMAIL_SEND_SCOPE = "https://www.googleapis.com/auth/gmail.send"
GOOGLE_AUTH_URL = "https://accounts.google.com/o/oauth2/v2/auth"
GOOGLE_TOKEN_URL = "https://oauth2.googleapis.com/token"
GOOGLE_USERINFO_URL = "https://www.googleapis.com/oauth2/v2/userinfo"


def build_gmail_authorization_url(
    *,
    settings: Settings,
    sender_account_id: str,
) -> str:
    _oauth_client(settings)
    redirect_uri = _redirect_uri(settings)
    state = sign_oauth_state(settings, sender_account_id=sender_account_id)
    query = urlencode(
        {
            "client_id": _client_id(settings),
            "redirect_uri": redirect_uri,
            "response_type": "code",
            "scope": GMAIL_SEND_SCOPE,
            "access_type": "offline",
            "prompt": "consent",
            "state": state,
        }
    )
    return f"{GOOGLE_AUTH_URL}?{query}"


def sign_oauth_state(settings: Settings, *, sender_account_id: str) -> str:
    payload = {
        "sender_account_id": sender_account_id,
        "nonce": secrets.token_urlsafe(18),
        "exp": int((datetime.now(timezone.utc) + timedelta(minutes=15)).timestamp()),
    }
    encoded = _b64url(json.dumps(payload, separators=(",", ":")).encode("utf-8"))
    signature = _b64url(hmac.new(_state_key(settings), encoded.encode("ascii"), hashlib.sha256).digest())
    return f"{encoded}.{signature}"


def verify_oauth_state(settings: Settings, state: str) -> str:
    try:
        encoded, signature = state.split(".", 1)
    except ValueError as exc:
        raise ValueError("Invalid Gmail OAuth state") from exc
    expected = _b64url(hmac.new(_state_key(settings), encoded.encode("ascii"), hashlib.sha256).digest())
    if not hmac.compare_digest(signature, expected):
        raise ValueError("Invalid Gmail OAuth state")
    payload = json.loads(_b64url_decode(encoded).decode("utf-8"))
    if int(payload.get("exp") or 0) < int(datetime.now(timezone.utc).timestamp()):
        raise ValueError("Gmail OAuth state expired")
    sender_account_id = payload.get("sender_account_id")
    if not isinstance(sender_account_id, str) or not sender_account_id:
        raise ValueError("Invalid Gmail OAuth state")
    return sender_account_id


def exchange_gmail_code(settings: Settings, *, code: str) -> dict[str, Any]:
    client_id, client_secret = _oauth_client(settings)
    try:
        response = httpx.post(
            GOOGLE_TOKEN_URL,
            data={
                "code": code,
                "client_id": client_id,
                "client_secret": client_secret,
                "redirect_uri": _redirect_uri(settings),
                "grant_type": "authorization_code",
            },
            timeout=30,
        )
        response.raise_for_status()
        tokens = response.json()
    except Exception as exc:
        raise GmailDeliveryError("Gmail OAuth token exchange failed") from exc
    if not isinstance(tokens.get("refresh_token"), str) or not tokens["refresh_token"]:
        raise GmailDeliveryError("Gmail OAuth did not return a refresh token")
    return tokens


def fetch_google_email(access_token: str) -> str:
    try:
        response = httpx.get(
            GOOGLE_USERINFO_URL,
            headers={"Authorization": "Bearer " + access_token},
            timeout=30,
        )
        response.raise_for_status()
        email = response.json().get("email")
    except Exception as exc:
        raise GmailDeliveryError("Gmail account verification failed") from exc
    if not isinstance(email, str) or "@" not in email:
        raise GmailDeliveryError("Gmail account verification failed")
    return email.strip().lower()


def store_gmail_oauth_tokens(
    client: Any,
    *,
    settings: Settings,
    sender_account_id: str,
    tokens: dict[str, Any],
    google_email: str,
) -> None:
    now = datetime.now(timezone.utc)
    expires_in = int(tokens.get("expires_in") or 0)
    expires_at = now + timedelta(seconds=expires_in) if expires_in > 0 else None
    payload = {
        "sender_account_id": sender_account_id,
        "provider": "gmail",
        "encrypted_access_token": encrypt_token(settings, str(tokens.get("access_token") or "")) if tokens.get("access_token") else None,
        "encrypted_refresh_token": encrypt_token(settings, str(tokens["refresh_token"])),
        "token_type": tokens.get("token_type"),
        "scope": tokens.get("scope"),
        "expires_at": expires_at.isoformat().replace("+00:00", "Z") if expires_at else None,
        "google_email": google_email,
    }
    rows = (
        client.table("sender_account_oauth_tokens")
        .select("id")
        .eq("sender_account_id", sender_account_id)
        .eq("provider", "gmail")
        .limit(1)
        .execute()
        .data
        or []
    )
    if rows:
        client.table("sender_account_oauth_tokens").update(payload).eq("id", rows[0]["id"]).execute()
    else:
        client.table("sender_account_oauth_tokens").insert(payload).execute()


def load_gmail_refresh_token(client: Any, *, settings: Settings, sender_account_id: str) -> str:
    rows = (
        client.table("sender_account_oauth_tokens")
        .select("encrypted_refresh_token")
        .eq("sender_account_id", sender_account_id)
        .eq("provider", "gmail")
        .limit(1)
        .execute()
        .data
        or []
    )
    if not rows or not rows[0].get("encrypted_refresh_token"):
        raise ValueError("Sender account is not connected for system sending.")
    return decrypt_token(settings, str(rows[0]["encrypted_refresh_token"]))


def delete_gmail_oauth_tokens(client: Any, *, sender_account_id: str) -> None:
    client.table("sender_account_oauth_tokens").delete().eq("sender_account_id", sender_account_id).eq("provider", "gmail").execute()


def encrypt_token(settings: Settings, token: str) -> str:
    if not token:
        return ""
    key = _encryption_key(settings)
    nonce = secrets.token_bytes(16)
    ciphertext = _xor_stream(token.encode("utf-8"), key, nonce)
    tag = hmac.new(key, nonce + ciphertext, hashlib.sha256).digest()
    return _b64url(nonce + tag + ciphertext)


def decrypt_token(settings: Settings, encrypted: str) -> str:
    blob = _b64url_decode(encrypted)
    if len(blob) < 48:
        raise ValueError("Stored Gmail token is invalid")
    nonce, tag, ciphertext = blob[:16], blob[16:48], blob[48:]
    key = _encryption_key(settings)
    expected = hmac.new(key, nonce + ciphertext, hashlib.sha256).digest()
    if not hmac.compare_digest(tag, expected):
        raise ValueError("Stored Gmail token is invalid")
    return _xor_stream(ciphertext, key, nonce).decode("utf-8")


def _xor_stream(data: bytes, key: bytes, nonce: bytes) -> bytes:
    output = bytearray()
    counter = 0
    while len(output) < len(data):
        block = hmac.new(key, nonce + counter.to_bytes(8, "big"), hashlib.sha256).digest()
        output.extend(block)
        counter += 1
    return bytes(value ^ stream for value, stream in zip(data, output))


def _client_id(settings: Settings) -> str:
    return settings.google_client_id or settings.gmail_client_id or ""


def _client_secret(settings: Settings) -> str:
    return settings.google_client_secret or settings.gmail_client_secret or ""


def _oauth_client(settings: Settings) -> tuple[str, str]:
    client_id = _client_id(settings)
    client_secret = _client_secret(settings)
    if not client_id or not client_secret:
        raise RuntimeError("Google OAuth client is not configured")
    return client_id, client_secret


def _redirect_uri(settings: Settings) -> str:
    return settings.gmail_oauth_redirect_uri or settings.backend_url.rstrip("/") + "/gmail/oauth/callback"


def _state_key(settings: Settings) -> bytes:
    return _encryption_key(settings)


def _encryption_key(settings: Settings) -> bytes:
    value = settings.gmail_token_encryption_key
    if not value:
        raise RuntimeError("GMAIL_TOKEN_ENCRYPTION_KEY is required")
    return hashlib.sha256(value.encode("utf-8")).digest()


def _b64url(value: bytes) -> str:
    return base64.urlsafe_b64encode(value).decode("ascii").rstrip("=")


def _b64url_decode(value: str) -> bytes:
    padded = value + "=" * (-len(value) % 4)
    return base64.urlsafe_b64decode(padded.encode("ascii"))
