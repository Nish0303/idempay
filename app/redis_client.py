import os
import redis

REDIS_HOST = os.getenv("REDIS_HOST", "localhost")
REDIS_PORT = int(os.getenv("REDIS_PORT", 6379))

redis_client = redis.Redis(host=REDIS_HOST, port=REDIS_PORT, decode_responses=True)

DEDUP_TTL_SECONDS = 60 * 60 * 24  # 24 hours


def seen_recently(idempotency_key: str) -> bool:
    """Fast pre-check only — an optimization, never the source of truth."""
    return redis_client.exists(f"idempotency:{idempotency_key}") == 1


def mark_seen(idempotency_key: str) -> None:
    redis_client.set(f"idempotency:{idempotency_key}", "1", ex=DEDUP_TTL_SECONDS)