"""LLM access for the four steps that need language understanding (D-03).

Every caller treats `None` as "no answer" and falls back to rule-based logic, so the
pipeline degrades gracefully when the API is down, a response is refused, or (in demo
mode) no cached fixture exists (trust design §7.1).

- ClaudeLLM: live Claude API calls, optionally recording responses as demo fixtures.
- GeminiLLM: same interface against Google's API. An alternative for running the pipeline without
  Anthropic credits; results from it describe that model, not the one this product would ship with.
- ReplayLLM: demo mode (PRD §3.4). Serves cached responses; never calls the API.
"""

from __future__ import annotations

import base64
import hashlib
import json
import os
import threading
import time
from pathlib import Path
from typing import Any, Protocol

import anthropic

from app.config import RunMode, Settings
from app.models import LLMCall

Content = str | list[dict[str, Any]]
FALLBACK_BETA = "server-side-fallback-2026-07-01"


class LLM(Protocol):
    calls: list[LLMCall]

    def json(self, task: str, system: str, content: Content, schema: dict) -> dict | None: ...


class FixtureStore:
    """Cached responses keyed by a hash of the full request (task, model, prompt, schema).

    Thread-safe. With autosave off, call flush() to write (bulk recording, e.g. the eval runner).
    """

    def __init__(self, path: Path, autosave: bool = True) -> None:
        self.path = path
        self.autosave = autosave
        self.entries: dict[str, dict] = json.loads(path.read_text()) if path.exists() else {}
        self._lock = threading.Lock()

    @staticmethod
    def key(task: str, model: str, system: str, content: Content, schema: dict) -> str:
        blob = json.dumps({"task": task, "model": model, "system": system, "content": content, "schema": schema},
                          sort_keys=True)
        return hashlib.sha256(blob.encode()).hexdigest()[:32]

    def get(self, key: str) -> dict | None:
        entry = self.entries.get(key)
        return entry["response"] if entry else None

    def put(self, key: str, task: str, response: dict) -> None:
        with self._lock:
            self.entries[key] = {"task": task, "response": response}
        if self.autosave:
            self.flush()

    def flush(self) -> None:
        with self._lock:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            self.path.write_text(json.dumps(self.entries, indent=2, sort_keys=True) + "\n")


class _Recorded:
    """Cache-first lookup shared by the live clients (settings.reuse_recorded).

    Lets a run extend an earlier one: requests already answered are replayed, and only genuinely
    new ones spend quota or money. Replayed calls are reported as cached, never as fresh.
    """

    fixtures: FixtureStore | None
    settings: Settings

    def _recorded(self, task: str, model: str, system: str, content: Content, schema: dict) -> dict | None:
        if not (self.fixtures and self.settings.reuse_recorded):
            return None
        return self.fixtures.get(FixtureStore.key(task, model, system, content, schema))


class ClaudeLLM(_Recorded):
    def __init__(self, settings: Settings, client: anthropic.Anthropic | None = None,
                 fixtures: FixtureStore | None = None) -> None:
        self.settings = settings
        self.client = client or anthropic.Anthropic()
        self.fixtures = fixtures or (FixtureStore(settings.fixtures_path) if settings.record_fixtures else None)
        self.calls: list[LLMCall] = []

    def json(self, task: str, system: str, content: Content, schema: dict) -> dict | None:
        model = self.settings.llm_model
        cached = self._recorded(task, model, system, content, schema)
        if cached is not None:
            self.calls.append(LLMCall(step=task, model=model, cached=True))
            return cached
        call = LLMCall(step=task, model=model)
        self.calls.append(call)
        start = time.monotonic()
        try:
            response = self.client.beta.messages.create(
                model=model,
                max_tokens=self.settings.llm_max_tokens,
                betas=[FALLBACK_BETA],
                fallbacks="default",
                system=system,
                messages=[{"role": "user", "content": content}],
                output_config={
                    "effort": self.settings.llm_effort,
                    "format": {"type": "json_schema", "schema": schema},
                },
            )
        except anthropic.RateLimitError as e:
            call.error = f"rate_limited: {e.message}"
            return None
        except anthropic.APIStatusError as e:
            call.error = f"api_error {e.status_code}: {e.message}"
            return None
        except anthropic.APIConnectionError as e:
            call.error = f"connection_error: {e}"
            return None
        finally:
            call.latency_ms = int((time.monotonic() - start) * 1000)

        call.model = response.model
        call.input_tokens = response.usage.input_tokens
        call.output_tokens = response.usage.output_tokens
        if response.stop_reason != "end_turn":
            call.error = f"stop_reason={response.stop_reason}"
            return None
        text = next((b.text for b in response.content if b.type == "text"), None)
        try:
            data = json.loads(text) if text else None
        except json.JSONDecodeError:
            data = None
        if data is None:
            call.error = "unparseable_response"
            return None
        if self.fixtures:
            self.fixtures.put(FixtureStore.key(task, model, system, content, schema), task, data)
        return data


class ReplayLLM:
    def __init__(self, settings: Settings) -> None:
        self.model = settings.model_name
        self.fixtures = FixtureStore(settings.fixtures_path)
        self.calls: list[LLMCall] = []

    def json(self, task: str, system: str, content: Content, schema: dict) -> dict | None:
        data = self.fixtures.get(FixtureStore.key(task, self.model, system, content, schema))
        self.calls.append(LLMCall(step=task, model=self.model, cached=True,
                                  error=None if data is not None else "no_fixture"))
        return data


# Google's structured-output schema is an OpenAPI subset: no additionalProperties, and nullability
# is a flag rather than a union with "null".
def to_google_schema(schema: dict) -> dict:
    if not isinstance(schema, dict):
        return schema
    branches = schema.get("anyOf")
    if branches and any(b.get("type") == "null" for b in branches):
        rest = [b for b in branches if b.get("type") != "null"]
        return to_google_schema(rest[0]) | {"nullable": True} if len(rest) == 1 else {"anyOf": [to_google_schema(b) for b in rest], "nullable": True}
    out = {k: v for k, v in schema.items() if k != "additionalProperties"}
    if "properties" in out:
        out["properties"] = {k: to_google_schema(v) for k, v in out["properties"].items()}
        out["propertyOrdering"] = list(out["properties"])
    if "items" in out:
        out["items"] = to_google_schema(out["items"])
    if "anyOf" in out:
        out["anyOf"] = [to_google_schema(b) for b in out["anyOf"]]
    return out


GOOGLE_RETRIES = 4
GOOGLE_BACKOFF_S = 5


def _rate_limited(error: Exception) -> bool:
    text = str(error).lower()
    return "429" in text or "resource_exhausted" in text or "rate limit" in text or "quota" in text


class GeminiLLM(_Recorded):
    """Google Gemini behind the same interface. Kept deliberately parallel to ClaudeLLM."""

    def __init__(self, settings: Settings, client=None, fixtures: FixtureStore | None = None) -> None:
        self.settings = settings
        self.model = settings.google_model
        self.fixtures = fixtures or (FixtureStore(settings.fixtures_path) if settings.record_fixtures else None)
        self.calls: list[LLMCall] = []
        if client is None:
            from google import genai  # imported lazily: an optional dependency
            client = genai.Client(api_key=os.environ.get("GOOGLE_API_KEY"))
        self.client = client

    def json(self, task: str, system: str, content: Content, schema: dict) -> dict | None:
        cached = self._recorded(task, self.model, system, content, schema)
        if cached is not None:
            self.calls.append(LLMCall(step=task, model=self.model, cached=True))
            return cached
        call = LLMCall(step=task, model=self.model)
        self.calls.append(call)
        start = time.monotonic()
        parts = [content] if isinstance(content, str) else [_google_part(b) for b in content]
        config = {
            "system_instruction": system,
            "response_mime_type": "application/json",
            "response_schema": to_google_schema(schema),
            "max_output_tokens": self.settings.llm_max_tokens,
            "automatic_function_calling": {"disable": True},
        }
        response = None
        try:
            for attempt in range(GOOGLE_RETRIES + 1):
                try:
                    response = self.client.models.generate_content(model=self.model, contents=parts, config=config)
                    break
                except Exception as e:  # the SDK raises provider-specific errors; degrade to rules either way
                    call.error = f"{type(e).__name__}: {str(e)[:200]}"
                    # Free-tier throttling is expected: wait rather than silently falling back to rules.
                    if attempt == GOOGLE_RETRIES or not _rate_limited(e):
                        return None
                    time.sleep(GOOGLE_BACKOFF_S * 2 ** attempt)
            call.error = None
        finally:
            call.latency_ms = int((time.monotonic() - start) * 1000)

        usage = getattr(response, "usage_metadata", None)
        if usage:
            call.input_tokens = usage.prompt_token_count or 0
            call.output_tokens = (usage.candidates_token_count or 0) + (usage.thoughts_token_count or 0)
        try:
            data = json.loads(response.text) if response.text else None
        except (json.JSONDecodeError, TypeError, ValueError):
            data = None
        if data is None:
            call.error = "unparseable_response"
            return None
        if self.fixtures:
            self.fixtures.put(FixtureStore.key(task, self.model, system, content, schema), task, data)
        return data


def _google_part(block: dict):
    """Translate an Anthropic-shaped content block (document or text) to Google's shape."""
    from google.genai import types

    if block.get("type") == "document":
        return types.Part.from_bytes(data=base64.b64decode(block["source"]["data"]),
                                     mime_type=block["source"]["media_type"])
    return block.get("text", "")


def make_llm(settings: Settings) -> LLM | None:
    if settings.mode == RunMode.LIVE:
        return GeminiLLM(settings) if settings.llm_provider == "google" else ClaudeLLM(settings)
    if settings.mode == RunMode.DEMO:
        return ReplayLLM(settings)
    return None
