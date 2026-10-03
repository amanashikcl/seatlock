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
