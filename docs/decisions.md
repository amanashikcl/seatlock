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
