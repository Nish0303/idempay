import time
import random
import logging
from sqlalchemy.orm import Session
from sqlalchemy.exc import IntegrityError
from sqlalchemy.sql import func

from .models import WebhookEvent, EventStatus
from .redis_client import seen_recently, mark_seen

logger = logging.getLogger("idempay")


class DuplicateEventError(Exception):
    """Raised when an event with this idempotency key already exists."""

    def __init__(self, existing_event: WebhookEvent):
        self.existing_event = existing_event


def register_event(
    db: Session, idempotency_key: str, event_type: str, payload: dict
) -> WebhookEvent:
    """
    Insert a new pending event. If the idempotency key already exists,
    raise DuplicateEventError with the existing row instead of processing again.
    """
    # Fast path: Redis pre-check. This is an optimization, not correctness-critical —
    # the DB unique constraint below is what actually guarantees no duplicates.
    if seen_recently(idempotency_key):
        existing = db.query(WebhookEvent).filter_by(idempotency_key=idempotency_key).first()
        if existing:
            raise DuplicateEventError(existing)
        # Redis said "seen" but DB has no row (e.g. TTL edge case) — fall through and let
        # the DB be the final word.

    event = WebhookEvent(
        idempotency_key=idempotency_key,
        event_type=event_type,
        payload=payload,
        status=EventStatus.pending,
    )
    db.add(event)
    try:
        db.commit()
        db.refresh(event)
        mark_seen(idempotency_key)
        return event
    except IntegrityError:
        # Two concurrent requests raced on INSERT — the unique constraint caught it.
        db.rollback()
        existing = db.query(WebhookEvent).filter_by(idempotency_key=idempotency_key).first()
        mark_seen(idempotency_key)
        raise DuplicateEventError(existing)


def claim_event(db: Session, event: WebhookEvent) -> bool:
    """
    Atomically flip status from 'pending' to 'processing'.
    Returns True if this call won the claim; False if someone else already claimed it.
    """
    rows_updated = (
        db.query(WebhookEvent)
        .filter(WebhookEvent.id == event.id, WebhookEvent.status == EventStatus.pending)
        .update({"status": EventStatus.processing})
    )
    db.commit()
    return rows_updated == 1


def process_side_effect(event: WebhookEvent) -> None:
    """
    Simulated payment side effect (e.g. 'charge the card').
    In a real integration, this call to the payment provider would itself pass
    idempotency_key, so the downstream system can also dedupe on retry.
    """
    logger.info(f"Processing event {event.idempotency_key} ({event.event_type})")
    time.sleep(0.2)  # simulate a network call to a payment provider
    if random.random() < 0.05:  # simulate occasional downstream failure
        raise RuntimeError("Simulated downstream failure")


def complete_event(db: Session, event: WebhookEvent) -> None:
    db.query(WebhookEvent).filter(WebhookEvent.id == event.id).update(
        {"status": EventStatus.completed, "processed_at": func.now()}
    )
    db.commit()


def fail_event(db: Session, event: WebhookEvent, reason: str) -> None:
    db.query(WebhookEvent).filter(WebhookEvent.id == event.id).update(
        {"status": EventStatus.failed, "failure_reason": reason}
    )
    db.commit()