# IdemPay: Idempotent Webhook & Payment Event Processor

Payment providers (Stripe, Razorpay and others) deliver webhooks **at least once**. Retries, timeouts and network blips mean the same event can arrive several times, sometimes simultaneously. If every delivery triggers the side effect, a customer gets charged twice.

IdemPay is a FastAPI service that makes sure **each event's side effect runs at most once**, no matter how many times or how concurrently the event is delivered.

## Results

Measured with the included load test (`idempay_test.py`), 20 concurrent clients:

| Metric | Result |
|---|---|
| Distinct events | 550 |
| Total deliveries | 1,350 (800 duplicates, including 50 keys sent **5× simultaneously**) |
| Events processed more than once | **0** |
| Duplicate-delivery latency (end-to-end, incl. HTTP) | p50 ≈ 24 ms, p99 ≈ 150 ms |
| Injected downstream failures (5% random) | 31–44 per run, each still processed at most once |

## How it works

```
POST /webhook ──► Redis fast-path check ──► INSERT (unique idempotency_key)
                     │ seen?                     │ IntegrityError?
                     ▼                           ▼
                 "duplicate"                 "duplicate"
                                                 │ inserted
                                                 ▼
                              atomic claim: UPDATE ... SET status='processing'
                                            WHERE status='pending'
                                                 │ won the claim (1 row updated)
                                                 ▼
                                side effect ──► completed / failed
```

1. **Unique constraint is the source of truth.** Every event is inserted into PostgreSQL with a `UNIQUE` index on `idempotency_key`. If two identical requests race, the database lets exactly one `INSERT` succeed. The loser gets an `IntegrityError` and returns `duplicate`.
2. **Redis fast path.** Keys are cached in Redis for 24 hours, so repeat deliveries are answered without an insert attempt. Redis is only an optimization: if it's wrong or empty, the database still prevents duplicates.
3. **Atomic claim step.** Before running the side effect, the worker flips the status `pending → processing` with a conditional `UPDATE ... WHERE status = 'pending'`. Only the request that updates exactly one row proceeds.
4. **State machine.** `pending → processing → completed | failed`, with `processed_at` and `failure_reason` recorded for auditing.

The side effect is simulated (`process_side_effect`): a 200 ms "payment provider call" that fails 5% of the time.

## Running it

**With Docker (easiest):**
```bash
docker compose up --build
```
The API runs at http://localhost:8000 (interactive docs at http://localhost:8000/docs).

**Run the load test** (in another terminal):
```bash
pip install -r requirements-dev.txt
python idempay_test.py
```

**Without Docker:** start PostgreSQL and Redis locally, create a database `idempay` with user/password `idempay`, then:
```bash
pip install -r requirements.txt
uvicorn app.main:app --reload
```
Override the connection settings with the `DATABASE_URL`, `REDIS_HOST` and `REDIS_PORT` environment variables.

The credentials in `docker-compose.yml` are local development defaults only.

## API

| Endpoint | Description |
|---|---|
| `POST /webhook` | Body: `{"idempotency_key": "evt_123", "event_type": "payment.succeeded", "data": {...}}`. Returns `completed`, `duplicate`, `already_claimed`, or HTTP 500 if the side effect failed |
| `GET /events` | The 50 most recent events with status and timestamps |
| `GET /health` | Health check |

## Tech stack

Python, FastAPI, PostgreSQL, SQLAlchemy, Redis, Docker
