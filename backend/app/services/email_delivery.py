from __future__ import annotations

from typing import Protocol

from email_validator import EmailNotValidError, validate_email

from app.integrations.gmail import GmailDelivery


class EmailTransport(Protocol):
    def send(self, *, sender: str, recipient: str, subject: str, body: str) -> GmailDelivery: ...


class EmailDeliveryService:
    """Validate an exact approved payload before invoking an injected transport."""

    def __init__(self, transport: EmailTransport) -> None:
        self.transport = transport

    def send(self, *, sender: str, recipient: str, subject: str, body: str) -> GmailDelivery:
        try:
            normalized_sender = validate_email(sender, check_deliverability=False).normalized
            normalized_recipient = validate_email(recipient, check_deliverability=False).normalized
        except EmailNotValidError as exc:
            raise ValueError("A valid sender and recipient email are required") from exc
        if not subject.strip() or not body.strip():
            raise ValueError("Approved email subject and body are required")
        return self.transport.send(
            sender=normalized_sender,
            recipient=normalized_recipient,
            subject=subject,
            body=body,
        )
