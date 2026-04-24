"""
BaseAgent — shared agentic loop logic with retry, tracing, and tool dispatch.
All specialized agents inherit from this.

Uses the openai SDK pointed at Groq's OpenAI-compatible endpoint:
- Messages are plain dicts: {role, content} / {role, tool_calls} / {role: tool, tool_call_id, content}
- Tool declarations follow the OpenAI function-calling format.
- "Done" = no tool_calls on the response message.
"""
import json
import logging
import os
import random
import time
from datetime import datetime, timezone
from typing import Any, Type

import instructor
from openai import OpenAI, APIStatusError
from pydantic import BaseModel

from app.config import settings, ProviderConfig
from app.services.trace_service import TraceService

logger = logging.getLogger(__name__)

LLM_LOG_DIR = "/data/llm_logs"
LLM_LOG_FILE = os.path.join(LLM_LOG_DIR, "latest.log")


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
        # Build one (raw_client, instructor_client) pair per provider in the chain.
        self._provider_clients: list[tuple[ProviderConfig, OpenAI, Any]] = []
        for p in settings.get_provider_chain():
            raw = OpenAI(api_key=p.api_key, base_url=p.base_url)
            instr = instructor.from_openai(raw, mode=instructor.Mode.JSON)
            self._provider_clients.append((p, raw, instr))

        # Primary provider clients exposed for _run_loop / legacy usage.
        self.client = self._provider_clients[0][1]
        self._structured_client = self._provider_clients[0][2]
        self.trace = TraceService()
        self.budget = budget or LLMCallBudget(settings.max_llm_calls_per_job)
        # Each subclass sets these:
        # self.tools = [{"type": "function", "function": {...}}]
        # self.tool_map = {"fn_name": callable}
        self.tools: list[dict] = []
        self.tool_map: dict[str, Any] = {}

    # ------------------------------------------------------------------
    # Retry helpers
    # ------------------------------------------------------------------

    def _is_transient_llm_error(self, exc: BaseException) -> bool:
        if isinstance(exc, APIStatusError):
            if exc.status_code in (429, 500, 503):
                return True
        msg = str(exc).lower()
        return (
            "429" in msg
            or "rate limit" in msg
            # "resource exhausted" excluded — daily quota exhaustion is not transient
            or "503" in msg
        )

    def _is_provider_fatal_error(self, exc: BaseException) -> bool:
        """True when the provider is permanently unavailable for this job — quota
        exhausted or auth failure. Triggers a switch to the next provider in the chain.
        Transient errors (rate limit, 5xx) are NOT fatal: they fail fast without switching."""
        if isinstance(exc, APIStatusError):
            if exc.status_code in (401, 403):
                return True
            if exc.status_code == 429:
                msg = str(exc).lower()
                return "resource exhausted" in msg or "quota" in msg
        msg = str(exc).lower()
        return "resource exhausted" in msg or "quota" in msg or "invalid api key" in msg

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

    def _generate_content_with_retry(
        self,
        messages: list[dict],
        tool_choice: str = "auto",
    ):
        # Check budget before making the call (not inside the retry loop —
        # retries on the *same* call don't count as additional calls).
        self.budget.consume(self.agent_name)

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
                return self.client.chat.completions.create(**create_kwargs)
            except Exception as exc:
                if not self._is_transient_llm_error(exc) or attempt >= max_attempts - 1:
                    raise
                delay = self._retry_delay(exc, attempt)
                logger.warning(
                    "Groq %s (attempt %d/%d) — retrying in %.0fs",
                    str(exc)[:120], attempt + 1, max_attempts, delay,
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
    ) -> BaseModel:
        """
        Single LLM call that returns a validated Pydantic object.

        If the model's output fails Pydantic validation, instructor automatically
        sends the validation error back to the LLM as a corrective prompt and retries
        up to max_retries times before raising. Each initial call counts against the
        budget; corrective retries do not (they are bounded and short).
        """
        self.budget.consume(self.agent_name)

        msgs: list[dict] = []
        if system:
            msgs.append({"role": "system", "content": system})
        for m in messages:
            msgs.append({"role": m["role"], "content": m["content"]})

        last_exc: Exception | None = None
        for idx, (p_cfg, _, instr_client) in enumerate(self._provider_clients):
            try:
                result = instr_client.chat.completions.create(
                    model=p_cfg.model,
                    messages=msgs,
                    response_model=response_model,
                    max_retries=max_retries,
                )
                self._log_structured(msgs, response_model.__name__, result=result)
                return result
            except Exception as exc:
                last_exc = exc
                if not self._is_provider_fatal_error(exc):
                    # Transient error — fail fast, no provider switch.
                    self._log_structured(msgs, response_model.__name__, error=str(exc))
                    raise
                self._log_structured(msgs, response_model.__name__, error=f"[{p_cfg.name}] {exc}")
                if idx < len(self._provider_clients) - 1:
                    next_name = self._provider_clients[idx + 1][0].name
                    logger.warning(
                        "%s: %s fatal error — switching to %s: %s",
                        self.agent_name, p_cfg.name, next_name, str(exc)[:120],
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
                        output_data={"to": next_name, "reason": str(exc)[:200]},
                        duration_ms=0,
                        success=False,
                        error=str(exc)[:200],
                    )
        raise last_exc  # type: ignore[misc]  — loop always sets last_exc

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

        force_tool_first=True uses tool_choice="required" on the first iteration
        so the model cannot respond with plain text before calling at least one tool.

        force_json_on_completion=True: when the model exits naturally with no
        tool calls, force one more "none"-mode call demanding JSON-only output.
        Only fires when the response text doesn't already start with '{'.
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
                    # Model returned prose instead of JSON — demand JSON-only.
                    # Only fires when the response isn't already valid JSON, so
                    # we avoid an unnecessary extra API call on clean responses.
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

            # Append assistant message with tool_calls
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

            # Execute all tool calls and collect results
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
            pass  # logging must never crash the agent

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
