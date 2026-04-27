"""
BaseAgent — shared agentic loop logic with retry, tracing, and tool dispatch.
All specialized agents inherit from this.

Uses the openai SDK pointed at Gemini's OpenAI-compatible endpoint:
- Messages are plain dicts: {role, content} / {role, tool_calls} / {role: tool, tool_call_id, content}
- Tool declarations follow the OpenAI function-calling format.
- "Done" = no tool_calls on the response message.
"""
import json
import os
import random
import time
from datetime import datetime, timezone
from typing import Any, Type

import instructor
import structlog
from openai import OpenAI, APIStatusError
from pydantic import BaseModel

from app.config import settings, ProviderConfig
from app.observability.cost import estimate_cost_usd
from app.resilience.circuit_breaker import get_circuit_breaker, CircuitOpenError
from app.services.trace_service import TraceService

logger = structlog.get_logger(__name__)

LLM_LOG_DIR = "/data/llm_logs"
LLM_LOG_FILE = os.path.join(LLM_LOG_DIR, "latest.log")


def _wrap_openai_if_enabled(client: OpenAI) -> OpenAI:
    """Wrap the OpenAI client with LangSmith tracing when enabled."""
    try:
        from langsmith.wrappers import wrap_openai
        return wrap_openai(client)
    except Exception:
        return client


def init_llm_log(topic: str, job_id: str) -> None:
    """Call once at the start of each pipeline run to reset the log."""
    os.makedirs(LLM_LOG_DIR, exist_ok=True)
    with open(LLM_LOG_FILE, "w", encoding="utf-8") as f:
        ts = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")
        f.write(f"{'=' * 72}\n")
        f.write(f"PIPELINE START: {topic}\n")
        f.write(f"Job ID:         {job_id}\n")
        f.write(f"Started at:     {ts}\n")
        f.write(f"{'=' * 72}\n")


class LLMCallBudget:
    """
    Shared call counter for all agents in the same pipeline job.
    Pass one instance to every agent so they all draw from the same budget.

    Raises BudgetExhaustedError when the hard cap is reached, which
    propagates up through the orchestrator and marks the job as failed
    with a clear message — not a silent loop.
    """

    def __init__(self, limit: int):
        self.limit = limit
        self.used = 0

    def consume(self, agent: str) -> None:
        self.used += 1
        if self.used > self.limit:
            raise BudgetExhaustedError(
                f"LLM call budget exhausted ({self.limit} calls). "
                f"Triggered by {agent}. Raise MAX_LLM_CALLS_PER_JOB to increase the cap."
            )

    @property
    def remaining(self) -> int:
        return max(0, self.limit - self.used)


class BudgetExhaustedError(RuntimeError):
    """Raised when a pipeline job exceeds its LLM API call budget."""


class BaseAgent:
    agent_name: str = "base_agent"

    def __init__(self, job_id: str, budget: LLMCallBudget | None = None):
        self.job_id = job_id
        self._provider_clients: list[tuple[ProviderConfig, OpenAI, Any]] = []
        for p in settings.get_provider_chain():
            raw = _wrap_openai_if_enabled(OpenAI(api_key=p.api_key, base_url=p.base_url))
            instr = instructor.from_openai(raw, mode=instructor.Mode.JSON)
            self._provider_clients.append((p, raw, instr))

        self.client = self._provider_clients[0][1]
        self._structured_client = self._provider_clients[0][2]
        self.trace = TraceService()
        self.budget = budget or LLMCallBudget(settings.max_llm_calls_per_job)
        self.tools: list[dict] = []
        self.tool_map: dict[str, Any] = {}

    # ------------------------------------------------------------------
    # Retry helpers
    # ------------------------------------------------------------------

    def _is_transient_llm_error(self, exc: BaseException) -> bool:
        """Transient infrastructure errors — worth retrying on the same provider."""
        if isinstance(exc, APIStatusError):
            if exc.status_code in (429, 500, 503):
                return True
        msg = str(exc).lower()
        return (
            "429" in msg
            or "rate limit" in msg
            or "503" in msg
        )

    def _is_provider_fatal_error(self, exc: BaseException) -> bool:
        """
        Permanent provider-level failures that should trigger a provider switch.

        IMPORTANT: instructor wraps API errors in InstructorRetryException, so
        isinstance(exc, APIStatusError) is often False here. All detection must
        also work via text patterns on str(exc), which includes the original error.

        Auth failures (401, 403, 400 API_KEY_INVALID) and quota exhaustion belong
        here — they will never recover on this provider for this job.
        """
        if isinstance(exc, APIStatusError):
            if exc.status_code in (401, 403):
                return True
            if exc.status_code == 400:
                # Gemini returns 400 for invalid API keys
                msg = str(exc).lower()
                return (
                    "api_key_invalid" in msg
                    or "api key not valid" in msg
                    or "invalid api key" in msg
                )
            if exc.status_code == 429:
                msg = str(exc).lower()
                return "resource exhausted" in msg or "quota" in msg

        # Text-based fallback — catches instructor-wrapped exceptions where
        # isinstance(exc, APIStatusError) is False but the original error text
        # is embedded in str(exc).
        msg = str(exc).lower()
        return (
            "resource exhausted" in msg
            or "quota" in msg
            # Auth errors (provider-specific phrasing)
            or "api_key_invalid" in msg          # Gemini: reason=API_KEY_INVALID
            or "api key not valid" in msg        # Gemini: 'API key not valid'
            or "invalid api key" in msg          # generic
            or "invalid_api_key" in msg          # generic snake_case
            or "incorrect api key" in msg        # OpenAI phrasing
            or "insufficient_quota" in msg       # OpenAI quota
            or "permission denied" in msg        # GCP 403-style in 400 body
        )

    def _retry_delay(self, exc: BaseException, attempt: int) -> float:
        if isinstance(exc, APIStatusError) and exc.response is not None:
            retry_after = (
                exc.response.headers.get("retry-after")
                or exc.response.headers.get("Retry-After")
            )
            if retry_after:
                try:
                    return float(retry_after) + random.uniform(0, 2.0)
                except (TypeError, ValueError):
                    pass

        base = max(settings.llm_api_retry_base_seconds, 10.0)
        delay = min(base * (2 ** attempt), settings.llm_api_retry_max_seconds)
        return delay + random.uniform(0, 5.0)

    def _is_cb_countable_failure(self, exc: BaseException) -> bool:
        """
        Only transient infrastructure failures count toward the circuit breaker.
        Auth errors (wrong API key, quota exhausted) are permanent config failures
        and must NOT open the circuit — they should just trigger a provider switch.
        """
        return self._is_transient_llm_error(exc)

    def _generate_content_with_retry(
        self,
        messages: list[dict],
        tool_choice: str = "auto",
    ):
        self.budget.consume(self.agent_name)

        # Check primary provider circuit breaker
        primary_cfg = self._provider_clients[0][0]
        cb = get_circuit_breaker(primary_cfg.name)
        if not cb.allow_request():
            raise CircuitOpenError(
                f"LLM provider '{primary_cfg.name}' circuit is open — "
                "too many recent failures. Retry in 60 seconds."
            )

        create_kwargs: dict[str, Any] = {
            "model": settings.llm_model,
            "messages": messages,
            "max_tokens": 4096,
        }
        if self.tools:
            create_kwargs["tools"] = self.tools
            create_kwargs["tool_choice"] = tool_choice

        max_attempts = max(1, settings.llm_api_max_retries)
        for attempt in range(max_attempts):
            try:
                response = self.client.chat.completions.create(**create_kwargs)
                cb.record_success()
                return response
            except Exception as exc:
                if self._is_cb_countable_failure(exc):
                    cb.record_failure()
                if not self._is_transient_llm_error(exc) or attempt >= max_attempts - 1:
                    raise
                delay = self._retry_delay(exc, attempt)
                logger.warning(
                    "llm_retry",
                    error=str(exc)[:120],
                    attempt=attempt + 1,
                    max_attempts=max_attempts,
                    delay_s=round(delay),
                    agent=self.agent_name,
                )
                time.sleep(delay)

    # ------------------------------------------------------------------
    # Structured output (instructor + Pydantic)
    # ------------------------------------------------------------------

    def _run_structured(
        self,
        response_model: Type[BaseModel],
        messages: list[dict],
        system: str | None = None,
        max_retries: int = 2,
        phase_tool: str | None = None,
    ) -> tuple[BaseModel, dict]:
        """
        Single LLM call that returns (validated_pydantic_object, usage_info).
        usage_info contains: prompt_tokens, completion_tokens, total_tokens, model, cost_usd.

        If the model's output fails Pydantic validation, instructor automatically
        sends the validation error back and retries up to max_retries times.
        """
        self.budget.consume(self.agent_name)

        msgs: list[dict] = []
        if system:
            msgs.append({"role": "system", "content": system})
        for m in messages:
            msgs.append({"role": m["role"], "content": m["content"]})

        last_exc: Exception | None = None
        for idx, (p_cfg, _, instr_client) in enumerate(self._provider_clients):
            cb = get_circuit_breaker(p_cfg.name)
            if not cb.allow_request():
                logger.warning(
                    "circuit_skip_provider",
                    provider=p_cfg.name,
                    agent=self.agent_name,
                )
                last_exc = CircuitOpenError(f"Provider '{p_cfg.name}' circuit is open")
                continue

            try:
                result, completion = instr_client.chat.completions.create_with_completion(
                    model=p_cfg.model,
                    messages=msgs,
                    response_model=response_model,
                    max_retries=max_retries,
                )
                cb.record_success()
                usage = getattr(completion, "usage", None)
                prompt_tokens = int(getattr(usage, "prompt_tokens", 0) or 0)
                completion_tokens = int(getattr(usage, "completion_tokens", 0) or 0)
                cost = estimate_cost_usd(p_cfg.model, prompt_tokens, completion_tokens)
                usage_info = {
                    "prompt_tokens": prompt_tokens,
                    "completion_tokens": completion_tokens,
                    "total_tokens": prompt_tokens + completion_tokens,
                    "model": p_cfg.model,
                    "cost_usd": cost,
                }
                self._log_structured(msgs, response_model.__name__, result=result)
                return result, usage_info
            except Exception as exc:
                last_exc = exc
                if self._is_cb_countable_failure(exc):
                    cb.record_failure()

                is_fatal = self._is_provider_fatal_error(exc)
                error_snippet = str(exc)[:200]

                if not is_fatal:
                    # Non-fatal, non-transient (e.g. Pydantic validation failure from
                    # instructor): no provider switch, just raise immediately.
                    self._log_structured(msgs, response_model.__name__, error=error_snippet)
                    raise

                # Fatal provider error (auth, quota, circuit open) → log and try next.
                self._log_structured(msgs, response_model.__name__, error=f"[{p_cfg.name}] {error_snippet}")

                remaining = self._provider_clients[idx + 1:]
                if remaining:
                    next_name = remaining[0][0].name
                    logger.warning(
                        "provider_switch",
                        from_provider=p_cfg.name,
                        from_model=p_cfg.model,
                        to_provider=next_name,
                        reason=error_snippet,
                        agent=self.agent_name,
                        phase_tool=phase_tool or "",
                        job_id=self.job_id,
                    )
                    self.trace.record_step(
                        job_id=self.job_id,
                        agent=self.agent_name,
                        tool="provider_switch",
                        input_data={
                            "from": p_cfg.name,
                            "model": p_cfg.model,
                            "phase_tool": phase_tool or "",
                        },
                        output_data={"to": next_name, "reason": error_snippet},
                        duration_ms=0,
                        success=False,
                        error=error_snippet,
                    )
                    # Emit a LangSmith event for the switch if tracing is active.
                    try:
                        from langsmith import get_current_run_tree
                        run = get_current_run_tree()
                        if run:
                            run.add_event({
                                "name": "provider_switch",
                                "message": f"Switched from {p_cfg.name} to {next_name}: {error_snippet[:120]}",
                            })
                    except Exception:
                        pass
                else:
                    logger.error(
                        "all_providers_exhausted",
                        last_provider=p_cfg.name,
                        reason=error_snippet,
                        agent=self.agent_name,
                        job_id=self.job_id,
                    )

        if last_exc is None:
            last_exc = CircuitOpenError("All LLM providers unavailable (circuits open)")
        raise last_exc  # type: ignore[misc]

    # ------------------------------------------------------------------
    # Agentic loop
    # ------------------------------------------------------------------

    def _run_loop(
        self,
        messages: list[dict],
        system: str | None = None,
        max_iterations: int = 20,
        force_tool_first: bool = False,
        force_json_on_completion: bool = False,
    ):
        """
        Core agentic loop. Runs until there are no tool_calls in the response
        or max_iterations is reached.
        """
        msgs: list[dict] = []
        if system:
            msgs.append({"role": "system", "content": system})
        for m in messages:
            content = m["content"] if isinstance(m["content"], str) else json.dumps(m["content"])
            msgs.append({"role": m["role"], "content": content})

        empty_rounds = 0
        MAX_EMPTY_ROUNDS = 2

        for iteration in range(max_iterations):
            tool_choice = (
                "required" if (force_tool_first and iteration == 0 and self.tools) else "auto"
            )

            response = self._generate_content_with_retry(msgs, tool_choice=tool_choice)
            self._log_llm(iteration, msgs, response)
            message = response.choices[0].message

            if not message.tool_calls:
                text = message.content or ""
                if (
                    force_json_on_completion
                    and (iteration > 0 or not self.tools)
                    and not text.strip().startswith("{")
                ):
                    msgs.append({"role": "assistant", "content": text})
                    msgs.append({
                        "role": "user",
                        "content": (
                            "Return ONLY the final JSON object now. "
                            "No prose, no step descriptions, no markdown — just the raw JSON."
                        ),
                    })
                    final = self._generate_content_with_retry(msgs, tool_choice="none")
                    self._log_llm(-1, msgs, final)
                    return final
                return response

            msgs.append({
                "role": "assistant",
                "content": message.content,
                "tool_calls": [
                    {
                        "id": tc.id,
                        "type": "function",
                        "function": {
                            "name": tc.function.name,
                            "arguments": tc.function.arguments,
                        },
                    }
                    for tc in message.tool_calls
                ],
            })

            result_msgs: list[dict] = []
            all_empty = True
            for tc in message.tool_calls:
                try:
                    args = json.loads(tc.function.arguments)
                except json.JSONDecodeError:
                    args = {}
                result_msg = self._execute_tool_with_retry(tc.function.name, args, tc.id)
                result_msgs.append(result_msg)
                try:
                    data = json.loads(result_msg["content"])
                    if any(isinstance(v, list) and len(v) > 0 for v in data.values()):
                        all_empty = False
                except (json.JSONDecodeError, AttributeError, TypeError):
                    pass

            msgs.extend(result_msgs)

            if all_empty:
                empty_rounds += 1
            else:
                empty_rounds = 0

            if empty_rounds >= MAX_EMPTY_ROUNDS:
                msgs.append({
                    "role": "user",
                    "content": (
                        "SYSTEM: All search results are empty. "
                        "Stop retrying. Return your final JSON response now "
                        "with whatever papers were found (an empty list is acceptable)."
                    ),
                })
                return self._generate_content_with_retry(msgs, tool_choice="none")

        return response

    # ------------------------------------------------------------------
    # Tool dispatch with retry
    # ------------------------------------------------------------------

    def _execute_tool_with_retry(self, name: str, inputs: dict, tool_call_id: str) -> dict:
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
                output_dict = output if isinstance(output, dict) else {"result": output}
                self.trace.record_step(
                    job_id=self.job_id,
                    agent=self.agent_name,
                    tool=name,
                    input_data=inputs,
                    output_data=output_dict,
                    duration_ms=duration_ms,
                    success=True,
                )
                logger.info(
                    "tool_call",
                    tool=name,
                    duration_ms=duration_ms,
                    success=True,
                    agent=self.agent_name,
                )
                return {
                    "role": "tool",
                    "tool_call_id": tool_call_id,
                    "content": json.dumps(output_dict),
                }
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
                logger.warning(
                    "tool_call_failed",
                    tool=name,
                    attempt=attempt,
                    error=str(exc)[:200],
                    agent=self.agent_name,
                )
                if attempt < settings.max_tool_retries:
                    time.sleep(min(2 ** attempt + random.uniform(0, 1.0), 30))

        return {
            "role": "tool",
            "tool_call_id": tool_call_id,
            "content": json.dumps({"error": str(last_error)}),
        }

    # ------------------------------------------------------------------
    # LLM conversation logger
    # ------------------------------------------------------------------

    def _log_llm(self, iteration: int, msgs: list[dict], response) -> None:
        try:
            path = LLM_LOG_FILE
            msg = response.choices[0].message
            ts = datetime.now(timezone.utc).strftime("%H:%M:%S")
            sep = "=" * 72
            with open(path, "a", encoding="utf-8") as f:
                f.write(f"\n{sep}\n")
                f.write(f"[{ts}] {self.agent_name}  iteration={iteration}  budget={self.budget.used}/{self.budget.limit}\n")
                f.write(f"{sep}\n")
                f.write("--- MESSAGES SENT ---\n")
                for m in msgs:
                    role = m.get("role", "?").upper()
                    content = m.get("content") or ""
                    tool_calls = m.get("tool_calls", [])
                    if role == "TOOL":
                        tool_id = m.get("tool_call_id", "")
                        preview = content[:300] + ("…" if len(content) > 300 else "")
                        f.write(f"[TOOL result id={tool_id}]\n{preview}\n\n")
                    elif tool_calls:
                        f.write(f"[ASSISTANT - called tools]\n")
                        for tc in tool_calls:
                            fn = tc.get("function", {})
                            f.write(f"  → {fn.get('name')}({fn.get('arguments', '')})\n")
                        f.write("\n")
                    else:
                        preview = str(content)[:600] + ("…" if len(str(content)) > 600 else "")
                        f.write(f"[{role}]\n{preview}\n\n")
                f.write("--- RESPONSE ---\n")
                if msg.tool_calls:
                    f.write("[ASSISTANT - calling tools]\n")
                    for tc in msg.tool_calls:
                        f.write(f"  → {tc.function.name}({tc.function.arguments})\n")
                else:
                    text = (msg.content or "")
                    preview = text[:800] + ("…" if len(text) > 800 else "")
                    f.write(f"[ASSISTANT - text]\n{preview}\n")
                f.write("\n")
        except Exception:
            pass

    def _log_structured(
        self,
        msgs: list[dict],
        model_name: str,
        result: BaseModel | None = None,
        error: str | None = None,
    ) -> None:
        try:
            ts = datetime.now(timezone.utc).strftime("%H:%M:%S")
            sep = "=" * 72
            with open(LLM_LOG_FILE, "a", encoding="utf-8") as f:
                f.write(f"\n{sep}\n")
                f.write(f"[{ts}] {self.agent_name}  structured={model_name}  budget={self.budget.used}/{self.budget.limit}\n")
                f.write(f"{sep}\n")
                f.write("--- MESSAGES SENT ---\n")
                for m in msgs:
                    role = m.get("role", "?").upper()
                    content = str(m.get("content") or "")
                    preview = content[:600] + ("…" if len(content) > 600 else "")
                    f.write(f"[{role}]\n{preview}\n\n")
                f.write("--- RESPONSE ---\n")
                if error:
                    f.write(f"[ERROR] {error[:400]}\n")
                elif result is not None:
                    text = result.model_dump_json()
                    preview = text[:800] + ("…" if len(text) > 800 else "")
                    f.write(f"[{model_name}]\n{preview}\n")
                f.write("\n")
        except Exception:
            pass

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _extract_text(self, response) -> str:
        try:
            return response.choices[0].message.content or ""
        except (IndexError, AttributeError):
            return ""
