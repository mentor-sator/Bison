from __future__ import annotations

import json
from typing import Any

import httpx
import pytest
from bison_contracts import InvokeRequest

from model_broker_service import api
from model_broker_service.backends import (
    BackendModel,
    ModelBackend,
    OllamaBackend,
    OpenRouterBackend,
)
from model_broker_service.broker import ModelBroker

CONTEXT_TOKENS = 8192
TEMPERATURE = 0.2
REQUEST_ID = "3f1d9d54-2c4f-4d5f-9f0e-8a7c6b5d4e3f"


class Recorder:
    def __init__(self, payload: dict[str, Any]) -> None:
        self._payload = payload
        self.bodies: list[dict[str, Any]] = []

    def handler(self, request: httpx.Request) -> httpx.Response:
        self.bodies.append(json.loads(request.content.decode("utf-8")))

        return httpx.Response(200, json=self._payload)

    @property
    def body(self) -> dict[str, Any]:
        return self.bodies[-1]

    @property
    def options(self) -> dict[str, Any]:
        found = self.body.get("options")

        return found if isinstance(found, dict) else {}


def ollama_backend(recorder: Recorder) -> OllamaBackend:
    backend = OllamaBackend("http://127.0.0.1:11434", 5.0)
    backend._client = httpx.AsyncClient(
        base_url="http://127.0.0.1:11434", transport=httpx.MockTransport(recorder.handler)
    )

    return backend


def openrouter_backend(recorder: Recorder, catalog: Any = None) -> OpenRouterBackend:
    backend = OpenRouterBackend("https://openrouter.ai", "sk-test", 5.0, catalog)
    backend._client = httpx.AsyncClient(
        base_url="https://openrouter.ai", transport=httpx.MockTransport(recorder.handler)
    )

    return backend


class FakeBackend(ModelBackend):
    def __init__(self, name: str, locality: str) -> None:
        self.name = name
        self.locality = locality  # type: ignore[assignment]
        self.calls: list[dict[str, Any]] = []

    async def healthy(self) -> bool:
        return True

    async def list_models(self) -> list[BackendModel]:
        return [
            BackendModel(
                model_id="m-1",
                provider=self.name,
                locality=self.locality,
                size_gb=None,
                context_window=32768,
            )
        ]

    async def generate(
        self,
        model_id: str,
        prompt: str,
        *,
        structured: bool,
        timeout_seconds: float,
        context_tokens: int | None = None,
        temperature: float | None = None,
    ) -> str:
        self.calls.append({"context_tokens": context_tokens, "temperature": temperature})

        return "{}"

    def pull(self, model_id: str) -> Any:
        raise NotImplementedError

    async def close(self) -> None:
        return None


def broker_over(backend: FakeBackend) -> ModelBroker:
    return ModelBroker([backend], 1, 30.0, CONTEXT_TOKENS, TEMPERATURE)


def asked(mode: str) -> InvokeRequest:
    return InvokeRequest.model_validate(
        {
            "request_id": REQUEST_ID,
            "model_id": "m-1",
            "engine_id": None,
            "role": "mediator",
            "prompt": "plan the work",
            "mode": mode,
            "schema_name": None,
            "timeout_ms": 60000,
        }
    )


async def test_ollama_is_told_the_context_window_to_open() -> None:
    recorder = Recorder({"response": "{}"})
    backend = ollama_backend(recorder)

    try:
        await backend.generate(
            "qwen2.5-coder:14b",
            "plan",
            structured=True,
            timeout_seconds=30.0,
            context_tokens=CONTEXT_TOKENS,
            temperature=TEMPERATURE,
        )
    finally:
        await backend.close()

    assert recorder.options == {"num_ctx": CONTEXT_TOKENS, "temperature": TEMPERATURE}
    assert recorder.body["format"] == "json"


async def test_ollama_sends_no_options_when_none_are_given() -> None:
    recorder = Recorder({"response": "{}"})
    backend = ollama_backend(recorder)

    try:
        await backend.generate("qwen2.5-coder:14b", "plan", structured=False, timeout_seconds=30.0)
    finally:
        await backend.close()

    assert "options" not in recorder.body
    assert "format" not in recorder.body


async def test_openrouter_carries_the_temperature_but_no_window() -> None:
    recorder = Recorder({"choices": [{"message": {"content": "{}"}}]})
    backend = openrouter_backend(recorder)

    try:
        await backend.generate(
            "vendor/model",
            "plan",
            structured=True,
            timeout_seconds=30.0,
            context_tokens=CONTEXT_TOKENS,
            temperature=TEMPERATURE,
        )
    finally:
        await backend.close()

    assert recorder.body["temperature"] == TEMPERATURE
    assert "num_ctx" not in json.dumps(recorder.body)


async def test_a_local_structured_call_carries_both_settings() -> None:
    backend = FakeBackend("ollama", "local")

    await broker_over(backend).invoke(asked("structured"))

    assert backend.calls == [{"context_tokens": CONTEXT_TOKENS, "temperature": TEMPERATURE}]


async def test_a_local_completion_keeps_the_model_s_own_sampling() -> None:
    backend = FakeBackend("ollama", "local")

    await broker_over(backend).invoke(asked("completion"))

    assert backend.calls == [{"context_tokens": CONTEXT_TOKENS, "temperature": None}]


async def test_a_remote_call_is_never_told_a_window() -> None:
    backend = FakeBackend("openrouter", "remote")

    await broker_over(backend).invoke(asked("structured"))

    assert backend.calls == [{"context_tokens": None, "temperature": TEMPERATURE}]


@pytest.mark.parametrize(
    ("field", "value"),
    [("request_id", "key-check"), ("model_id", ""), ("prompt", "")],
)
async def test_a_body_the_contract_refuses_answers_422(field: str, value: str) -> None:
    body = {
        "model_id": "m-1",
        "prompt": "plan the work",
        "role": "mediator",
        "mode": "structured",
        field: value,
    }
    transport = httpx.ASGITransport(app=api.app)

    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.post("/invoke", json=body)

    assert response.status_code == 422
    assert field in json.dumps(response.json())
