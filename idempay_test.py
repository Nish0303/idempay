import uuid, time, random, requests
import concurrent.futures as cf
from collections import defaultdict

URL = "http://localhost:8000/webhook"
UNIQUE = 500        # distinct events
REPLAY_KEYS = 200   # first 200 events get re-delivered...
REPLAYS = 3         # ...3 extra times each
RACE_KEYS = 50      # keys sent 5x simultaneously
RACE_COPIES = 5


def send(key):
    t = time.perf_counter()
    try:
        r = requests.post(
            URL,
            json={"idempotency_key": key, "event_type": "payment.succeeded", "data": {"amount": 100}},
            timeout=15,
        )
        ms = (time.perf_counter() - t) * 1000
        try:
            body = r.json()
        except Exception:
            body = {}
        status = body.get("status") or ("failed_500" if r.status_code == 500 else f"http_{r.status_code}")
        return key, status, ms
    except Exception:
        return key, "error", 0


unique_keys = [f"evt_{uuid.uuid4()}" for _ in range(UNIQUE)]
race_keys = [f"race_{uuid.uuid4()}" for _ in range(RACE_KEYS)]

deliveries = list(unique_keys)
deliveries += [k for k in unique_keys[:REPLAY_KEYS] for _ in range(REPLAYS)]
deliveries += [k for k in race_keys for _ in range(RACE_COPIES)]
random.shuffle(deliveries)

start = time.time()
with cf.ThreadPoolExecutor(max_workers=20) as ex:
    results = list(ex.map(send, deliveries))
elapsed = time.time() - start

all_keys = set(unique_keys) | set(race_keys)
attempts = defaultdict(int)       # times the side effect actually ran per key
for key, status, _ in results:
    if status in ("completed", "failed_500"):
        attempts[key] += 1

violations = [k for k in all_keys if attempts[k] != 1]
counts = defaultdict(int)
for _, s, _ in results:
    counts[s] += 1
dup_lat = sorted(ms for _, s, ms in results if s in ("duplicate", "already_claimed"))

print(f"\nDistinct events:        {len(all_keys)}")
print(f"Total deliveries:       {len(deliveries)}  ({elapsed:.1f}s)")
print(f"Response breakdown:     {dict(counts)}")
print(f"Keys processed != once: {len(violations)}   <-- this is your 'duplicate charges' number")
if dup_lat:
    print(f"Duplicate-response latency (end-to-end, incl. HTTP): "
          f"p50 {dup_lat[len(dup_lat)//2]:.1f} ms, p99 {dup_lat[int(len(dup_lat)*0.99)]:.1f} ms")
    