"""In-process stand-in for the Hospital Directory API, used via httpx.MockTransport."""

import asyncio
import json
from collections import defaultdict

import httpx

from app.schemas import HospitalRow

TIMEOUT_AFTER_CREATE = "timeout_after_create"


def make_rows(count: int) -> list[HospitalRow]:
    return [
        HospitalRow(row=i, name=f"H{i}", address=f"{i} Main St", phone=None)
        for i in range(1, count + 1)
    ]


class FakeDirectory:
    """Stateful fake. Script failures with `script(key, *outcomes)`.

    Keys: "create:<hospital name>", "activate", "list", "ping". Each outcome is consumed
    by one matching request and may be an int status code, an httpx.Response,
    an Exception to raise, or TIMEOUT_AFTER_CREATE (store the hospital, then
    raise a read timeout).
    """

    def __init__(self) -> None:
        self.hospitals: list[dict] = []
        self.requests: list[httpx.Request] = []
        self.delay = 0.0
        self.blocked = False  # while True, requests wait; lets tests control timing
        self.max_in_flight = 0
        self._in_flight = 0
        self._next_id = 101
        self._scripted: dict[str, list] = defaultdict(list)

    def script(self, key: str, *outcomes) -> None:
        self._scripted[key].extend(outcomes)

    def create_calls(self, name: str | None = None) -> int:
        return sum(
            1
            for request in self.requests
            if request.method == "POST"
            and (name is None or json.loads(request.content)["name"] == name)
        )

    def activate_calls(self) -> int:
        return sum(1 for request in self.requests if request.method == "PATCH")

    async def __call__(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        self._in_flight += 1
        self.max_in_flight = max(self.max_in_flight, self._in_flight)
        try:
            while self.blocked:
                await asyncio.sleep(0.005)
            if self.delay:
                await asyncio.sleep(self.delay)
            return self._route(request)
        finally:
            self._in_flight -= 1

    def _next_outcome(self, key: str):
        queue = self._scripted.get(key)
        return queue.pop(0) if queue else None

    def _store(self, body: dict) -> dict:
        hospital = {
            "id": self._next_id,
            "name": body["name"],
            "address": body["address"],
            "phone": body.get("phone"),
            "creation_batch_id": body.get("creation_batch_id"),
            "active": body.get("creation_batch_id") is None,
        }
        self._next_id += 1
        self.hospitals.append(hospital)
        return hospital

    def _route(self, request: httpx.Request) -> httpx.Response:
        path = request.url.path
        if request.method == "GET" and path == "/":
            scripted = self._respond(self._next_outcome("ping"))
            if scripted is not None:
                return scripted
            return httpx.Response(200, json={"status": "OK"})

        if request.method == "POST" and path == "/hospitals/":
            body = json.loads(request.content)
            outcome = self._next_outcome(f"create:{body['name']}")
            if outcome == TIMEOUT_AFTER_CREATE:
                self._store(body)
                raise httpx.ReadTimeout("read timed out")
            scripted = self._respond(outcome)
            if scripted is not None:
                return scripted
            return httpx.Response(200, json=self._store(body))

        if request.method == "PATCH" and path.endswith("/activate"):
            scripted = self._respond(self._next_outcome("activate"))
            if scripted is not None:
                return scripted
            batch_id = path.split("/")[-2]
            members = [h for h in self.hospitals if h["creation_batch_id"] == batch_id]
            for hospital in members:
                hospital["active"] = True
            return httpx.Response(200, json={"activated": len(members)})

        if request.method == "GET" and path.startswith("/hospitals/batch/"):
            scripted = self._respond(self._next_outcome("list"))
            if scripted is not None:
                return scripted
            batch_id = path.split("/")[-1]
            members = [h for h in self.hospitals if h["creation_batch_id"] == batch_id]
            if not members:
                return httpx.Response(
                    404, json={"detail": "No hospitals found with the specified batch ID"}
                )
            return httpx.Response(200, json=members)

        return httpx.Response(404, json={"detail": "Not Found"})

    @staticmethod
    def _respond(outcome) -> httpx.Response | None:
        if outcome is None:
            return None
        if isinstance(outcome, Exception):
            raise outcome
        if isinstance(outcome, httpx.Response):
            return outcome
        return httpx.Response(outcome, json={"detail": "scripted failure"})
