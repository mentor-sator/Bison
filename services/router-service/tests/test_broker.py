from __future__ import annotations

import json
from typing import Any

import httpx
import pytest
from fastapi import Request

from router_service.api import handle_broker_timeout
from router_service.broker import (
    BrokerClient,
    BrokerError,
    BrokerTimeoutError,
    BrokerUnreachableError,
    timed_out,
)

BASE_URL = "http://127.0.0.1:8300"
PROJECT_ID = "prj_1"
REQUEST_ID = "req_1"
TIMEOUT_MS = 120000
INVOKE_SECONDS = 3600.0
CONNECT_SECONDS = 5.0


def client(handler: Any) -> BrokerClient:
    return BrokerClient(
        BASE_URL, INVOKE_SECONDS, CONNECT_SECONDS, transport=httpx.MockTransport(handler)
    )


def raising(error: Exception) -> Any:
    def handler(request: httpx.Request) -> httpx.Response:
        raise error

    return handler


async def test_a_read_timeout_on_invoke_names_the_seconds_it_waited() -> None:
    broker = client(raising(httpx.ReadTimeout("read timed out")))

    with pytest.raises(BrokerTimeoutError) as caught:
        await broker.invoke("m", "p", REQUEST_ID, TIMEOUT_MS)

    assert caught.value.seconds == INVOKE_SECONDS
    assert str(caught.value) == f"model-broker at {BASE_URL} timed out after 3600 s"

    await broker.close()


async def test_a_read_timeout_is_not_reported_as_unreachable() -> None:
    broker = client(raising(httpx.ReadTimeout("read timed out")))

    with pytest.raises(BrokerTimeoutError) as caught:
        await broker.invoke("m", "p", REQUEST_ID, TIMEOUT_MS)

    assert not isinstance(caught.value, BrokerUnreachableError)
    assert "unreachable" not in str(caught.value)

    await broker.close()


async def test_a_refused_connection_on_invoke_is_unreachable() -> None:
    broker = client(raising(httpx.ConnectError("connection refused")))

    with pytest.raises(BrokerUnreachableError) as caught:
        await broker.invoke("m", "p", REQUEST_ID, TIMEOUT_MS)

    assert caught.value.base_url == BASE_URL

    await broker.close()


async def test_a_connect_timeout_is_unreachable_rather_than_slow() -> None:
    broker = client(raising(httpx.ConnectTimeout("connect timed out")))

    with pytest.raises(BrokerUnreachableError):
        await broker.invoke("m", "p", REQUEST_ID, TIMEOUT_MS)

    await broker.close()


async def test_a_slow_bindings_read_names_the_connect_budget() -> None:
    broker = client(raising(httpx.ReadTimeout("read timed out")))

    with pytest.raises(BrokerTimeoutError) as caught:
        await broker.binding(PROJECT_ID)

    assert caught.value.seconds == CONNECT_SECONDS

    await broker.close()


async def test_an_answer_is_returned_as_text() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"response": "a plan"})

    broker = client(handler)

    assert await broker.invoke("m", "p", REQUEST_ID, TIMEOUT_MS) == "a plan"

    await broker.close()


async def test_a_refusal_carries_the_brokers_reason() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(422, json={"detail": {"reason": "bad request_id"}})

    broker = client(handler)

    with pytest.raises(BrokerError) as caught:
        await broker.invoke("m", "p", REQUEST_ID, TIMEOUT_MS)

    assert caught.value.status == 422
    assert caught.value.detail == "bad request_id"

    await broker.close()


@pytest.mark.parametrize(
    ("error", "expected"),
    [
        (httpx.ReadTimeout("r"), True),
        (httpx.WriteTimeout("w"), True),
        (httpx.PoolTimeout("p"), True),
        (httpx.ConnectTimeout("c"), False),
        (httpx.ConnectError("c"), False),
    ],
)
def test_only_timeouts_after_connecting_count_as_timed_out(
    error: httpx.HTTPError, expected: bool
) -> None:
    assert timed_out(error) is expected


async def test_a_broker_timeout_answers_504_with_the_reason() -> None:
    response = await handle_broker_timeout(
        Request({"type": "http"}), BrokerTimeoutError(BASE_URL, INVOKE_SECONDS)
    )

    assert response.status_code == 504
    assert json.loads(bytes(response.body)) == {
        "error": "broker_timeout",
        "detail": f"model-broker at {BASE_URL} timed out after 3600 s",
    }
