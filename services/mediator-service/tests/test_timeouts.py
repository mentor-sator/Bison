from __future__ import annotations

import json

import httpx
import pytest
from fastapi import Request

from mediator_service.api import on_broker_timeout
from mediator_service.broker import (
    BrokerClient,
    BrokerTimeoutError,
    BrokerUnreachableError,
    timed_out,
)
from mediator_service.dispatch import RouterClient, RouterError, RouterTimeoutError

BROKER_URL = "http://127.0.0.1:8300"
ROUTER_URL = "http://router.test"
PROJECT_ID = "p-1"
TASK_ID = "t-1"
REQUEST_ID = "r-1"
TIMEOUT_MS = 120000


def raising(error: Exception) -> httpx.MockTransport:
    def handler(request: httpx.Request) -> httpx.Response:
        raise error

    return httpx.MockTransport(handler)


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


async def test_a_slow_tree_build_names_the_seconds_it_waited() -> None:
    broker = BrokerClient(BROKER_URL, 3600.0, 5.0, transport=raising(httpx.ReadTimeout("r")))

    with pytest.raises(BrokerTimeoutError) as caught:
        await broker.tree("m", "p", REQUEST_ID, TIMEOUT_MS)

    assert caught.value.seconds == 3600.0
    assert str(caught.value) == f"model-broker at {BROKER_URL} timed out after 3600 s"
    assert not isinstance(caught.value, BrokerUnreachableError)

    await broker.close()


async def test_a_slow_bindings_read_names_the_connect_budget() -> None:
    broker = BrokerClient(BROKER_URL, 3600.0, 5.0, transport=raising(httpx.ReadTimeout("r")))

    with pytest.raises(BrokerTimeoutError) as caught:
        await broker.bindings(PROJECT_ID)

    assert caught.value.seconds == 5.0

    await broker.close()


async def test_a_broker_that_refuses_the_connection_is_still_unreachable() -> None:
    broker = BrokerClient(BROKER_URL, 3600.0, 5.0, transport=raising(httpx.ConnectTimeout("c")))

    with pytest.raises(BrokerUnreachableError):
        await broker.tree("m", "p", REQUEST_ID, TIMEOUT_MS)

    await broker.close()


async def test_a_router_that_answers_too_slowly_is_named_as_timed_out() -> None:
    router = RouterClient(ROUTER_URL, 3600.0, 1.0, transport=raising(httpx.ReadTimeout("r")))

    with pytest.raises(RouterTimeoutError) as caught:
        await router.plan(PROJECT_ID, TASK_ID, REQUEST_ID)

    assert caught.value.seconds == 3600.0
    assert str(caught.value) == f"router-service at {ROUTER_URL} timed out after 3600 s"

    await router.close()


async def test_a_broker_timeout_inside_the_router_reaches_the_mediator_as_the_reason() -> None:
    detail = f"model-broker at {BROKER_URL} timed out after 3600 s"

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(504, json={"error": "broker_timeout", "detail": detail})

    router = RouterClient(ROUTER_URL, 3600.0, 1.0, transport=httpx.MockTransport(handler))

    with pytest.raises(RouterError) as caught:
        await router.plan(PROJECT_ID, TASK_ID, REQUEST_ID)

    assert caught.value.status == 504
    assert caught.value.detail == detail

    await router.close()


async def test_a_broker_timeout_answers_504_with_the_reason() -> None:
    response = await on_broker_timeout(
        Request({"type": "http"}), BrokerTimeoutError(BROKER_URL, 3600.0)
    )

    assert response.status_code == 504
    assert json.loads(bytes(response.body)) == {
        "error": "broker_timeout",
        "detail": f"model-broker at {BROKER_URL} timed out after 3600 s",
    }
