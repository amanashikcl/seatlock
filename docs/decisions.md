# Design decisions

Short records of choices that affect more than one module. Newest at the bottom.

## 1. Money is stored as integer cents
Prices and totals are integers in the smallest currency unit (`price_cents`). Floats cannot
represent 0.10 exactly; `Decimal` is exact but costs more at every boundary (JSON, Redis,
webhooks). Integers sum exactly and are trivial to compare. A DB check keeps them >= 0.
Single currency for now; a `currency` column is added if multi-currency is ever needed.

## 2. IDs: auto-increment for catalog data, UUID for reservations
Events and seats are public catalog data, so sequential IDs are fine. Reservations appear in
payment webhooks and customer links, so they use UUIDs: not guessable, and safe to generate
before the row exists.

## 3. Seat availability is derived, never stored
`Seat` has no sold/available flag. Availability comes from reservation rows, the single
source of truth. A flag would be a second copy that can drift when a worker crashes between
two writes, which is the classic overselling bug.

## 4. Invariants live in the database
Uniqueness and range rules are enforced by DB constraints (unique email, unique seat label,
`sales_open_at < starts_at`, non-negative prices), with Python validation only for friendly
errors. App code can be bypassed by scripts, bulk operations and races; constraints cannot.

## 5. Roles are fixed and live in code
Three roles (customer, organizer, admin) as a `TextChoices` field plus permission classes.
Admin is a superset of organizer. Only admins can change roles; registration never accepts one.

## 6. "One active claim per seat" is a partial unique index
`ReservationSeat` has a unique constraint on `seat` that applies only `WHERE is_active`.
Postgres therefore rejects a second live claim on a seat no matter how the insert happens, so
locks and caches (later steps) affect speed and fairness, never correctness. `is_active` is the
single deliberate copy of reservation state: a partial index cannot join to `Reservation`, so
it flips in the same transaction that expires or cancels the reservation. Rejected:
triggers/exclusion constraints (harder to test), deleting released rows (loses history).
Known gap: "seat belongs to the reservation's event" is a cross-table rule, enforced in the
service layer instead.

## 7. Baseline booking strategy: pessimistic row locks, ordered by id
`hold_seats` locks the requested `Seat` rows with `SELECT ... FOR UPDATE` in ascending id
order, then checks availability. Ordered locking prevents deadlocks when two buyers want the
same seats in opposite orders. This is the correctness baseline; optimistic and Redis-based
strategies are benchmarked against it later. The unique index remains the backstop either way.
Service functions raise domain exceptions (no HTTP), so views and workers can both call them.

## 8. Expiry is a plain function with SKIP LOCKED, scheduled separately
`expire_holds` finds lapsed `held` reservations (via a partial index), locks them with
`FOR UPDATE SKIP LOCKED`, and flips the reservation and its seat claims in one short
transaction, in batches. Skipping locked rows means concurrent sweepers (or a payment being
confirmed) never collide or stall. It is idempotent, so retries are safe. It knows nothing
about Celery; the scheduler (Step 2.5) just calls it. Trade-off: a seat stays blocked until
the next sweep. Refinement for later: expire stale claims inline inside `hold_seats`.

## 9. Background work: Celery with RabbitMQ, scheduled by beat
Periodic and slow jobs run in Celery workers, not in web requests. RabbitMQ is the broker
(durable delivery, acknowledgements) rather than Redis, so a cache restart cannot lose queued
jobs and a cache problem cannot take down the queue. `acks_late` plus
`reject_on_worker_lost` redeliver a task if a worker dies mid-run; that is only safe because
tasks are idempotent. Prefetch is 1 and no result backend is used. Tasks are thin wrappers
around plain tested functions. A test checks every beat entry names a registered task,
because a typo there fails silently. Beat runs as a single instance.

## 10. RabbitMQ 4 needs two deprecated features permitted for Celery (known tech debt)
Celery's worker declares transient non-exclusive queues (remote-control and gossip reply
queues) and uses global QoS for prefetch limits. RabbitMQ 4 rejects both unless
`deprecated_features.permit.transient_nonexcl_queues` and `...global_qos` are set, which
`docker/rabbitmq/seatlock.conf` does. The feature will be removed in a future
RabbitMQ major, so the image stays on 4.x. Exit plan: move task queues to quorum queues and
disable Celery remote control/gossip, which removes the need for the exception.

## 11. API authorization: roles for actions, ownership for objects
Who may *do* something is a role check (`IsOrganizer`); who may change a *specific* event is an
object-level check (`IsOwnerOrAdmin`). Role checks alone would let one organizer edit another's
event. The organizer on a new event always comes from the authenticated user, never the request
body. Events expose no PUT or DELETE (cancelling will be an explicit action), and all list
endpoints are paginated by default with a stable ordering.

## 12. Holds API: thin view, domain errors mapped to stable codes
`POST /events/<id>/holds/` validates only the request shape, calls `hold_seats`, and translates
domain exceptions: `seat_unavailable` and `sales_not_open` are 409 (valid request, conflicting
state), `invalid_selection` is 400. Every error carries a machine-readable `code`. The seat map
computes `available` with a NOT EXISTS over active claims, so there is no flag to drift (a lapsed
but unswept hold still shows unavailable for up to one sweep interval). Known gaps: retries after
a timeout need an Idempotency-Key (with payments), and rate limiting needs a shared counter (with
the Redis step).

## 13. Confirming a payment: row lock, grace period, idempotent
`confirm_reservation` locks the reservation row (`FOR UPDATE`); the expiry sweeper uses
`SKIP LOCKED`, so a reservation can never be both confirmed and expired. Payments are accepted
until `expires_at + 60s`, and the sweeper only expires holds after that same moment, so the
cut-off is a fixed instant, not "whenever the sweeper last ran" (cost: seats stay blocked a
minute longer). Confirming a confirmed reservation is a no-op (webhooks are delivered more than
once). A payment that arrives too late is rejected with a reason; refunding it is handled by the
webhook layer. We do not try to re-claim seats after expiry, since someone else may hold them.

## 14. Webhooks: signed, stored once, then processed idempotently
Incoming payment webhooks are authenticated with HMAC-SHA256 over `"<timestamp>.<raw body>"`,
compared in constant time, with a 5-minute timestamp window against replays. Each event is stored
in `WebhookEvent` (UNIQUE provider event id, so duplicates are caught by the database) *before* it
is processed; processing is idempotent, so a crash between the two is repaired by replay. Business
failures (unknown reservation, too late, wrong amount) are acknowledged and recorded as `failed`
with a reason for follow-up; only unexpected errors leave an event `received` to be retried.
The amount is checked against the reservation total under the row lock. Unknown event types are
stored and acknowledged so a provider adding types cannot cause endless retries.
