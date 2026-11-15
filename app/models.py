import enum
from sqlalchemy import Column, BigInteger, String, Enum, DateTime, Text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.sql import func
from .database import Base


class EventStatus(str, enum.Enum):
    pending = "pending"
    processing = "processing"
    completed = "completed"
    failed = "failed"


class WebhookEvent(Base):
    __tablename__ = "webhook_events"

    id = Column(BigInteger, primary_key=True, autoincrement=True)
    idempotency_key = Column(String(255), unique=True, nullable=False, index=True)
    event_type = Column(String(100), nullable=False)
    payload = Column(JSONB, nullable=False)
    status = Column(
        Enum(EventStatus, name="event_status"),
        nullable=False,
        default=EventStatus.pending,
    )
    received_at = Column(DateTime(timezone=True), server_default=func.now())
    processed_at = Column(DateTime(timezone=True), nullable=True)
    failure_reason = Column(Text, nullable=True)