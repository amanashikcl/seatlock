# Benchmark: does the Redis seat gate earn its place?

## Question

During a flash sale almost every request loses: thousands of buyers go for the same few
seats. Each losing request used to open a Postgres transaction and wait on seat-row locks
only to be told "taken". The Redis gate (`apps/reservations/gate.py`) answers that case from
memory instead. Is the extra moving part worth it?

## Setup

- Everything on one laptop under Docker Compose: API (gunicorn, 3 sync workers), Postgres 16,
  Redis 7, Locust as the load generator.
- 300 simulated buyers, ramped at 20 per second, for 90 seconds. Each registers, logs in,
  reads the seat map, then repeatedly tries to hold a random seat out of 50 hot seats
  (200 seats exist; every buyer targets the same 50). 0.1-0.4 s think time.
- Per-user rate limiting raised to 1,000,000 so it cannot interfere.
- Two runs, differing only in `SEAT_GATE_ENABLED`. Each ran on a freshly created event.
- Reproduce: see `loadtest/locustfile.py`, `seed_loadtest` and `loadtest_report`.

## Results (`POST holds`)

| Metric | Gate on | Gate off |
|---|---|---|
| Requests completed | 59,779 | 41,652 |
| Throughput | 666 req/s | 464 req/s |
| Median latency | 22 ms | 150 ms |
| 95th percentile | 88 ms | 210 ms |
| 99th percentile | 150 ms | 310 ms |
| Holds won (201) | 50 | 50 |
| Rejected as taken (409) | 59,729 | 41,602 |
| Failures | 0 | 0 |

## Correctness

In both runs exactly 50 holds succeeded for 50 contended seats: one winner per seat, never
two. After the gate-off run, `loadtest_report` confirmed 50 live reservations, 50 active seat
claims and 50 distinct claimed seats. The guarantee does not come from the gate: Postgres
enforces it with a partial unique index (one active claim per seat) and row locks. The gate
only decides how cheaply the losers are turned away.

## Conclusion

For this contention-heavy workload the gate cut median latency about 7x and raised
throughput about 43%, so it stays. Why it works: a losing request never reaches Postgres.

## Caveats (read before quoting the numbers)

- One run per configuration, on a single laptop that also runs the load generator. Treat the
  numbers as relative, not absolute. Repeating the runs would give a variance estimate.
- Gate-on ran first, gate-off second; order effects (warm caches, thermal state) are possible,
  though the gap is far larger than that would explain.
- The 99.9th percentile (about 10-12 s in both runs) comes from the first seconds of the test,
  when 300 users register and log in at once. Password hashing is deliberately slow and only 3
  workers share it, so hold requests queue behind it. It affects both runs equally.
- The workload is nearly all losing requests. For a lightly contended event the gate adds a
  Redis round trip (about 1 ms) and saves nothing; that case was not measured.
