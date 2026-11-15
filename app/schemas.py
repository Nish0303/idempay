from typing import Any, Dict
from pydantic import BaseModel, Field


class WebhookPayload(BaseModel):
    idempotency_key: str = Field(
        ..., description="Unique event ID from the sender, e.g. Stripe's evt_..."
    )
    event_type: str
    data: Dict[str, Any]