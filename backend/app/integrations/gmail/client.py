from __future__ import annotations

import base64
from dataclasses import dataclass
from email.message import EmailMessage

import httpx


class GmailDeliveryError(RuntimeError):
    """A safe provider error that never includes credentials or response bodies."""


@dataclass(frozen=True)
class GmailDelivery:
    message_id: str


class GmailClient:
    """Backend-only Gmail OAuth refresh-token transport."""

    def __init__(self, client_id: str, client_secret: str, refresh_token: str) -> None:
        if not client_id or not client_secret or not refresh_token:
            raise ValueError("Gmail credentials are required")
        self.client_id = client_id
        self.client_secret = client_secret
        self.refresh_token = refresh_token

    def _access_token(self) -> str:
        try:
            response = httpx.post(
                "https://oauth2.googleapis.com/token",
                data={
                    "client_id": self.client_id,
                    "client_secret": self.client_secret,
                    "refresh_token": self.refresh_token,
                    "grant_type": "refresh_token",
                },
                timeout=30,
            )
            response.raise_for_status()
            token = response.json().get("access_token")
            if not isinstance(token, str) or not token:
                raise GmailDeliveryError("Gmail token exchange failed")
            return token
        except GmailDeliveryError:
            raise
        except Exception as exc:
            raise GmailDeliveryError("Gmail token exchange failed") from exc

    def send(self, *, sender: str, recipient: str, subject: str, body: str) -> GmailDelivery:
        message = EmailMessage()
        message["From"] = sender
        message["To"] = recipient
        message["Subject"] = subject
        message.set_content(body)
        raw = base64.urlsafe_b64encode(message.as_bytes()).decode("ascii")
        try:
            response = httpx.post(
                "https://gmail.googleapis.com/gmail/v1/users/me/messages/send",
                headers={"Authorization": "Bearer " + self._access_token()},
                json={"raw": raw},
                timeout=30,
            )
            response.raise_for_status()
            message_id = response.json().get("id")
            if not isinstance(message_id, str) or not message_id:
                raise GmailDeliveryError("Gmail did not return a message ID")
            return GmailDelivery(message_id=message_id)
        except GmailDeliveryError:
            raise
        except Exception as exc:
            raise GmailDeliveryError("Gmail provider request failed") from exc
