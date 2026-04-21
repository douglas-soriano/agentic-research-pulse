"""
BaseAgent — shared agentic loop logic with retry, tracing, and tool dispatch.
All specialized agents inherit from this.

Uses the google-genai SDK:
- Contents is a list of Content objects (role + parts), not role/content dicts.
- Function calls arrive as Part.function_call on the model's Content.
- Function results are sent as Part.function_response in a user Content.
- "Done" = no function_call parts in the response (no separate stop_reason).
"""
import json
import random
import time
from typing import Any

from google import genai
from google.genai import types
from google.genai.errors import ClientError

from app.config import settings
from app.services.trace_service import TraceService


class BaseAgent:
    agent_name: str = "base_agent"

    def __init__(self, job_id: str):
        self.job_id = job_id
        self.client = genai.Client(api_key=settings.gemini_api_key)
        self.trace = TraceService()
        # Each subclass sets these:
        # self.tools = [types.Tool(function_declarations=[...])]
        # self.tool_map = {"fn_name": callable}
        self.tools: list[types.Tool] = []
        self.tool_map: dict[str, Any] = {}

    def _is_transient_llm_error(self, exc: BaseException) -> bool:
        """429 rate limits, overload, and short-lived server errors — worth backing off and retrying."""
        if isinstance(exc, ClientError):
            code = getattr(exc, "status_code", None)
            if code in (429, 500, 503):
                return True
        msg = str(exc)
        msg_lower = msg.lower()
        return (
            "429" in msg
            or "resource exhausted" in msg_lower
            or "resource_exhausted" in msg_lower
            or "503" in msg
            or "quota" in msg_lower
        )

    def _retry_delay(self, exc: BaseException, attempt: int) -> float:
        """
        Return how long to wait before the next attempt.
        Honours the Retry-After value when Gemini provides one (free-tier
        rate limits typically set it to 60 s).  Falls back to exponential
        backoff capped at llm_api_retry_max_seconds.
        """
        # Some SDKs expose the raw response headers on the exception
        headers = getattr(exc, "response", None)
        if headers is not None:
            headers = getattr(headers, "headers", {})
            retry_after = headers.get("Retry-After") or headers.get("retry-after")
            if retry_after:
                try:
                    return float(retry_after) + random.uniform(0, 2.0)
                except (TypeError, ValueError):
                    pass

        # Exponential backoff — minimum 30 s on the first 429 so we don't
        # burn through free-tier quota spinning.
        base = max(settings.llm_api_retry_base_seconds, 30.0)
        delay = min(base * (2 ** attempt), settings.llm_api_retry_max_seconds)
        return delay + random.uniform(0, 5.0)

    def _generate_content_with_retry(
        self,
        *,
        model: str,
        contents: list[types.Content],
        config: types.GenerateContentConfig,
    ) -> types.GenerateContentResponse:
        max_attempts = max(1, settings.llm_api_max_retries)
        for attempt in range(max_attempts):
            try:
                return self.client.models.generate_content(
                    model=model,
                    contents=contents,
                    config=config,
                )
            except Exception as exc:
                if not self._is_transient_llm_error(exc) or attempt >= max_attempts - 1:
                    raise
                delay = self._retry_delay(exc, attempt)
                import logging
                logging.getLogger(__name__).warning(
                    "Gemini %s (attempt %d/%d) — retrying in %.0fs",
                    str(exc)[:120], attempt + 1, max_attempts, delay,
                )
                time.sleep(delay)

    # ------------------------------------------------------------------
    # Agentic loop
    # ------------------------------------------------------------------

    def _run_loop(
        self,
        messages: list[dict],
        system: str | None = None,
        max_iterations: int = 20,
    ) -> types.GenerateContentResponse:
        """
        Core agentic loop. Runs until there are no function_call parts
        in the response or max_iterations is reached.
        """
        contents = self._to_contents(messages)
        config = types.GenerateContentConfig(
            tools=self.tools if self.tools else None,
            system_instruction=system,
            max_output_tokens=4096,
        )

        for _ in range(max_iterations):
            response = self._generate_content_with_retry(
                model=settings.llm_model,
                contents=contents,
                config=config,
            )

            candidate = response.candidates[0]
            function_calls = [
                p.function_call
                for p in candidate.content.parts
                if p.function_call is not None
            ]

            if not function_calls:
                # No tool calls — agent is done
                return response

            # Append model turn to history
            contents.append(candidate.content)

            # Execute all tool calls and collect results
            result_parts = []
            for fc in function_calls:
                result_parts.append(self._execute_tool_with_retry(fc.name, dict(fc.args)))

            contents.append(
                types.Content(role="user", parts=result_parts)
            )

        return response

    # ------------------------------------------------------------------
    # Tool dispatch with retry
    # ------------------------------------------------------------------

    def _execute_tool_with_retry(self, name: str, inputs: dict) -> types.Part:
        attempt = 0
        last_error: Exception | None = None
        while attempt < settings.max_tool_retries:
            start = time.monotonic()
            try:
                fn = self.tool_map.get(name)
                if fn is None:
                    raise ValueError(f"Unknown tool: {name}")
                output = fn(**inputs)
                duration_ms = int((time.monotonic() - start) * 1000)
                self.trace.record_step(
                    job_id=self.job_id,
                    agent=self.agent_name,
                    tool=name,
                    input_data=inputs,
                    output_data=output if isinstance(output, dict) else {"result": output},
                    duration_ms=duration_ms,
                    success=True,
                )
                return types.Part(
                    function_response=types.FunctionResponse(
                        name=name,
                        response=output if isinstance(output, dict) else {"result": output},
                    )
                )
            except Exception as exc:
                last_error = exc
                attempt += 1
                duration_ms = int((time.monotonic() - start) * 1000)
                self.trace.record_step(
                    job_id=self.job_id,
                    agent=self.agent_name,
                    tool=name,
                    input_data=inputs,
                    output_data={"error": str(exc)},
                    duration_ms=duration_ms,
                    success=False,
                    error=str(exc),
                )
                if attempt < settings.max_tool_retries:
                    time.sleep(2 ** attempt)

        return types.Part(
            function_response=types.FunctionResponse(
                name=name,
                response={"error": str(last_error)},
            )
        )

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _to_contents(self, messages: list[dict]) -> list[types.Content]:
        """Convert simple [{role, content}] dicts to Gemini Content objects."""
        contents = []
        for m in messages:
            role = "user" if m["role"] == "user" else "model"
            text = m["content"] if isinstance(m["content"], str) else json.dumps(m["content"])
            contents.append(types.Content(role=role, parts=[types.Part(text=text)]))
        return contents

    def _extract_text(self, response: types.GenerateContentResponse) -> str:
        try:
            return response.candidates[0].content.parts[0].text or ""
        except (IndexError, AttributeError):
            return ""
