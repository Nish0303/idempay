import logging
from fastapi import FastAPI, Depends, HTTPException
from sqlalchemy.orm import Session

from .database import Base, engine, get_db
from .models import WebhookEvent
from .schemas import WebhookPayload
from .processor import (
    register_event,
    claim_event,
    process_side_effect,
    complete_event,
    fail_event,
    DuplicateEventError,
)

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("idempay")

app = FastAPI(title="IdemPay")

Base.metadata.create_all(bind=engine)


@app.post("/webhook")
def receive_webhook(payload: WebhookPayload, db: Session = Depends(get_db)):
    try:
        event = register_event(db, payload.idempotency_key, payload.event_type, payload.data)
    except DuplicateEventError as e:
        existing = e.existing_event
        return {
            "status": "duplicate",
            "idempotency_key": existing.idempotency_key,
            "current_status": existing.status,
        }

    claimed = claim_event(db, event)
    if not claimed:
        return {"status": "already_claimed", "idempotency_key": event.idempotency_key}

    try:
        process_side_effect(event)
        complete_event(db, event)
        return {"status": "completed", "idempotency_key": event.idempotency_key}
    except Exception as e:
        fail_event(db, event, str(e))
        raise HTTPException(status_code=500, detail=f"Processing failed: {e}")


@app.get("/events")
def list_events(db: Session = Depends(get_db)):
    events = (
        db.query(WebhookEvent).order_by(WebhookEvent.received_at.desc()).limit(50).all()
    )
    return [
        {
            "id": e.id,
            "idempotency_key": e.idempotency_key,
            "event_type": e.event_type,
            "status": e.status,
            "received_at": e.received_at,
            "processed_at": e.processed_at,
            "failure_reason": e.failure_reason,
        }
        for e in events
    ]


@app.get("/health")
def health():
    return {"status": "ok"}