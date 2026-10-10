"""Client for the upstream Hospital Directory API, including the retry policy."""

import asyncio
import random
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from uuid import UUID

import httpx

from app.schemas import HospitalRow

RETRYABLE_STATUS_CODES = frozenset({429, 502, 503, 504})


class UpstreamError(Exception):
    """The Hospital Directory API failed or could not be reached."""

    def __init__(self, message: str, *, status_code: int | None = None) -> None:
        super().__init__(message)
        self.status_code = status_code


@dataclass(frozen=True)
class UpstreamHospital:
    id: int
    name: str
    address: str
    phone: str | None


class HospitalDirectoryClient:
    def __init__(
        self,
        http: httpx.AsyncClient,
        *,
        max_retries: int,
        backoff_seconds: float,
        sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
    ) -> None:
        self._http = http
        self._max_retries = max_retries
        self._backoff_seconds = backoff_seconds
        self._sleep = sleep

    async def ping(self) -> None:
        """Check the upstream is reachable. Idempotent, so timeouts are retried."""
        await self._request("GET", "/", retry_on_timeout=True)

    async def create_hospital(self, row: HospitalRow, batch_id: UUID) -> int:
        payload = {
            "name": row.name,
            "address": row.address,
            "phone": row.phone,
            "creation_batch_id": str(batch_id),
        }
        # A read timeout is ambiguous for a create: the hospital may exist.
        # Retrying could duplicate it, so the caller reconciles on resume instead.
        response = await self._request("POST", "/hospitals/", retry_on_timeout=False, json=payload)
        try:
            return int(response.json()["id"])
        except (ValueError, KeyError, TypeError) as exc:
            raise UpstreamError("Hospital directory returned an unexpected response") from exc

    async def list_batch(self, batch_id: UUID) -> list[UpstreamHospital]:
        try:
            response = await self._request(
                "GET", f"/hospitals/batch/{batch_id}", retry_on_timeout=True
            )
        except UpstreamError as exc:
            if exc.status_code == 404:  # upstream reports an empty batch as 404
                return []
            raise
        try:
            return [
                UpstreamHospital(
                    id=int(item["id"]),
                    name=item["name"],
                    address=item["address"],
                    phone=item.get("phone"),
                )
                for item in response.json()
            ]
        except (ValueError, KeyError, TypeError, AttributeError) as exc:
            raise UpstreamError("Hospital directory returned an unexpected batch listing") from exc

    async def activate_batch(self, batch_id: UUID) -> None:
        await self._request("PATCH", f"/hospitals/batch/{batch_id}/activate", retry_on_timeout=True)

    async def _request(
        self, method: str, url: str, *, retry_on_timeout: bool, **kwargs
    ) -> httpx.Response:
        for attempt in range(1, self._max_retries + 1):
            try:
                response = await self._http.request(method, url, **kwargs)
            except (httpx.ConnectError, httpx.ConnectTimeout, httpx.PoolTimeout) as exc:
                # The request never reached the upstream, so a retry is always safe.
                failure = UpstreamError(f"Could not connect to hospital directory: {exc}")
            except httpx.TimeoutException as exc:
                failure = UpstreamError("Hospital directory timed out")
                if not retry_on_timeout:
                    raise failure from exc
            except httpx.HTTPError as exc:
                raise UpstreamError(f"Hospital directory request failed: {exc}") from exc
            else:
                if response.is_success:
                    return response
                failure = UpstreamError(
                    f"Hospital directory returned {response.status_code}: {response.text[:200]}",
                    status_code=response.status_code,
                )
                if response.status_code not in RETRYABLE_STATUS_CODES:
                    raise failure

            if attempt == self._max_retries:
                raise failure
            backoff = self._backoff_seconds * 2 ** (attempt - 1)
            await self._sleep(backoff + random.uniform(0, self._backoff_seconds))

        raise AssertionError("unreachable: max_retries must be at least 1")
