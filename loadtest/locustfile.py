"""Flash-sale load test: many buyers fight over a small set of hot seats.

Run through docker compose (see docs/benchmarks.md). Each simulated buyer registers, logs in,
reads the seat map once, then keeps trying to hold a random hot seat. Almost every attempt
loses (409): that is the realistic flash-sale shape, and exactly the path the Redis gate
is meant to make cheap.
"""

import os
import random
import uuid
from typing import Any

from locust import HttpUser, between, events, task
from locust.exception import StopUser

if not os.environ.get("EVENT_ID", "").isdigit():
    raise SystemExit("EVENT_ID must be the number printed by seed_loadtest, e.g. EVENT_ID=14")
EVENT_ID = int(os.environ["EVENT_ID"])
HOT_SEATS = int(os.environ.get("HOT_SEATS", "50"))
PASSWORD = "Load-test-pass-12345!"  # throwaway value for generated benchmark users

outcomes = {"won": 0, "lost": 0}  # 201 = got the seat, 409 = someone else had it


class Buyer(HttpUser):
    wait_time = between(0.1, 0.4)

    def on_start(self) -> None:
        # We reach the API as http://api:8000 inside Docker, but Django only accepts the hosts
        # in ALLOWED_HOSTS. Present as localhost instead of loosening a security setting.
        self.client.headers["Host"] = "localhost"
        email = f"load-{uuid.uuid4().hex[:16]}@example.com"
        self.client.post(
            "/api/v1/auth/register/",
            json={"email": email, "password": PASSWORD},
            name="setup: register",
        )
        login = self.client.post(
            "/api/v1/auth/token/",
            json={"email": email, "password": PASSWORD},
            name="setup: login",
        )
        if login.status_code != 200:
            print(f"setup failed: login returned {login.status_code}")
            raise StopUser()
        self.client.headers["Authorization"] = f"Bearer {login.json()['access']}"
        seat_map = self.client.get(
            f"/api/v1/events/{EVENT_ID}/seats/?page_size={HOT_SEATS}", name="setup: seat map"
        )
        if seat_map.status_code != 200:
            print(f"setup failed: seat map returned {seat_map.status_code} (wrong EVENT_ID?)")
            raise StopUser()
        self.hot_seat_ids = [seat["id"] for seat in seat_map.json()["results"]]

    @task
    def try_to_hold_a_hot_seat(self) -> None:
        seat_id = random.choice(self.hot_seat_ids)
        with self.client.post(
            f"/api/v1/events/{EVENT_ID}/holds/",
            json={"seat_ids": [seat_id]},
            name="POST holds",
            catch_response=True,
        ) as response:
            if response.status_code == 201:
                outcomes["won"] += 1
                response.success()
            elif response.status_code == 409:
                outcomes["lost"] += 1
                response.success()  # expected: someone else got there first
            elif response.status_code == 429:
                response.failure("rate limited: set HOLD_RATE_LIMIT high for the benchmark")
            else:
                response.failure(f"unexpected status {response.status_code}")


@events.test_stop.add_listener
def print_outcomes(environment: Any, **kwargs: Any) -> None:
    print(f"OUTCOMES won(201)={outcomes['won']} lost(409)={outcomes['lost']}")
