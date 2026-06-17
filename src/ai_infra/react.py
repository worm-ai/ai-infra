from __future__ import annotations

import hashlib
import json
import os
import re
import time
import urllib.error
import urllib.request
from dataclasses import dataclass
from typing import Any

from .tools import _render_template, build_tool_invocation, execute_tool


@dataclass(frozen=True)
class ReActModelConfig:
    provider: str
    model: str
    prompt: str
    max_steps: int
    base_url: str | None = None
    api_key_env: str | None = None
    timeout_ms: int | None = None

    def to_summary(self) -> dict[str, Any]:
        return {
            "provider": self.provider,
            "model": self.model,
            "base_url": self.base_url,
            "api_key_env": self.api_key_env,
            "prompt_sha256": hashlib.sha256(self.prompt.encode("utf-8")).hexdigest(),
            "max_steps": self.max_steps,
            "timeout_ms": self.timeout_ms,
        }


@dataclass(frozen=True)
class ReActStepEvidence:
    index: int
    thought_summary: str
    action: dict[str, Any]
    observation: dict[str, Any]
    tool_invocation: dict[str, Any] | None = None

    def to_dict(self) -> dict[str, Any]:
        payload = {
            "index": self.index,
            "thought_summary": self.thought_summary,
            "action": self.action,
            "observation": self.observation,
        }
        if self.tool_invocation is not None:
            payload["tool_invocation"] = self.tool_invocation
        return payload


@dataclass(frozen=True)
class ReActExecution:
    status: str
    output: dict[str, Any]


def execute_react_node(config: dict[str, Any], context: dict[str, Any]) -> ReActExecution:
    started = time.perf_counter()
    model_config = _model_config(config)
    model_summary = model_config.to_summary()
    steps: list[dict[str, Any]] = []
    latest_tool_invocation: dict[str, Any] | None = None
    tool_calls_used = 0
    max_tool_calls = _max_tool_calls(config, model_config.max_steps)

    try:
        _render_template(model_config.prompt, context)
    except Exception as exc:
        return _execution(
            status="failed",
            model=model_summary,
            steps=steps,
            max_steps=model_config.max_steps,
            max_tool_calls=max_tool_calls,
            tool_calls_used=tool_calls_used,
            budget_status="model_error",
            started=started,
            error=f"react prompt render failed: {exc}",
        )

    if model_config.provider == "openai-compatible":
        return _execute_openai_compatible_node(
            model_config=model_config,
            config=config,
            context=context,
            started=started,
            model_summary=model_summary,
            max_tool_calls=max_tool_calls,
        )
    if model_config.provider != "mock":
        return _execution(
            status="failed",
            model=model_summary,
            steps=steps,
            max_steps=model_config.max_steps,
            max_tool_calls=max_tool_calls,
            tool_calls_used=tool_calls_used,
            budget_status="unsupported_provider",
            started=started,
            error=f"react provider {model_config.provider!r} is unsupported",
        )

    tools = config.get("tools", [])
    if not isinstance(tools, list):
        tools = []

    if tools:
        tool_config = tools[0]
        if tool_calls_used >= max_tool_calls:
            return _execution(
                status="failed",
                model=model_summary,
                steps=steps,
                max_steps=model_config.max_steps,
                max_tool_calls=max_tool_calls,
                tool_calls_used=tool_calls_used,
                budget_status="tool_budget_exhausted",
                started=started,
                error="react node exceeded max_tool_calls before final answer",
            )

        try:
            invocation = build_tool_invocation(tool_config, context)
            tool_execution = execute_tool(tool_config, context)
        except Exception as exc:
            return _execution(
                status="failed",
                model=model_summary,
                steps=steps,
                max_steps=model_config.max_steps,
                max_tool_calls=max_tool_calls,
                tool_calls_used=tool_calls_used,
                budget_status="tool_error",
                started=started,
                error=f"react tool execution failed: {exc}",
            )

        tool_calls_used += 1
        latest_tool_invocation = _tool_invocation_from_output(tool_execution.output)
        action = {
            "type": "tool",
            "adapter": invocation.adapter,
            "identity": invocation.identity,
        }
        observation = {
            "status": tool_execution.status,
            "output": _observation_output(tool_execution.output),
        }
        steps.append(
            ReActStepEvidence(
                index=len(steps) + 1,
                thought_summary="selected the first declared tool inside the DAG node boundary",
                action=action,
                observation=observation,
                tool_invocation=latest_tool_invocation,
            ).to_dict()
        )

        if tool_execution.status != "completed":
            return _execution(
                status="failed",
                model=model_summary,
                steps=steps,
                max_steps=model_config.max_steps,
                max_tool_calls=max_tool_calls,
                tool_calls_used=tool_calls_used,
                budget_status="tool_failed",
                started=started,
                error=str(tool_execution.output.get("error") or "react tool execution failed"),
                latest_tool_invocation=latest_tool_invocation,
            )

        if len(steps) >= model_config.max_steps:
            return _execution(
                status="failed",
                model=model_summary,
                steps=steps,
                max_steps=model_config.max_steps,
                max_tool_calls=max_tool_calls,
                tool_calls_used=tool_calls_used,
                budget_status="max_steps_exhausted",
                started=started,
                error="react node exceeded max_steps before final answer",
                latest_tool_invocation=latest_tool_invocation,
            )

        answer = _answer_from_tool_output(tool_execution.output)
    else:
        answer = _render_template(model_config.prompt, context)

    steps.append(
        ReActStepEvidence(
            index=len(steps) + 1,
            thought_summary="produced the terminal answer within the bounded ReAct node",
            action={"type": "final_answer"},
            observation={"status": "completed", "answer": answer},
        ).to_dict()
    )
    return _execution(
        status="completed",
        model=model_summary,
        steps=steps,
        max_steps=model_config.max_steps,
        max_tool_calls=max_tool_calls,
        tool_calls_used=tool_calls_used,
        budget_status="within_limits",
        started=started,
        answer=answer,
        latest_tool_invocation=latest_tool_invocation,
    )


def _model_config(config: dict[str, Any]) -> ReActModelConfig:
    return ReActModelConfig(
        provider=str(config.get("provider", "")),
        model=str(config.get("model", "")),
        prompt=str(config.get("prompt", "")),
        max_steps=int(config.get("max_steps", 1)),
        base_url=config.get("base_url") if isinstance(config.get("base_url"), str) else None,
        api_key_env=config.get("api_key_env") if isinstance(config.get("api_key_env"), str) else None,
        timeout_ms=config.get("timeout_ms") if isinstance(config.get("timeout_ms"), int) else None,
    )


def _max_tool_calls(config: dict[str, Any], max_steps: int) -> int:
    budget = config.get("budget")
    if isinstance(budget, dict) and isinstance(budget.get("max_tool_calls"), int):
        return int(budget["max_tool_calls"])
    tools = config.get("tools", [])
    if isinstance(tools, list) and tools:
        return min(1, max_steps)
    return 0


def _execute_openai_compatible_node(
    *,
    model_config: ReActModelConfig,
    config: dict[str, Any],
    context: dict[str, Any],
    started: float,
    model_summary: dict[str, Any],
    max_tool_calls: int,
) -> ReActExecution:
    prompt = _render_template(model_config.prompt, context)
    provider_governance = {
        "api_key_env": model_config.api_key_env,
        "api_key_present": bool(model_config.api_key_env and os.environ.get(model_config.api_key_env)),
        "timeout_ms": model_config.timeout_ms,
    }
    if not provider_governance["api_key_present"]:
        provider = {
            "status": "missing_api_key",
            "governance": provider_governance,
            "request": _provider_request_summary(model_config, prompt),
        }
        return _execution(
            status="failed",
            model=model_summary,
            steps=[],
            max_steps=model_config.max_steps,
            max_tool_calls=max_tool_calls,
            tool_calls_used=0,
            budget_status="missing_api_key",
            started=started,
            error=f"react openai-compatible provider missing required environment variable {model_config.api_key_env!r}",
            provider=provider,
        )

    response = _call_openai_compatible_provider(model_config, prompt)
    usage = _provider_usage(prompt, response, config.get("budget"))
    provider = {
        "status": response["status"],
        "governance": provider_governance,
        "request": _provider_request_summary(model_config, prompt),
        "response": _provider_response_summary(response),
        "usage": usage,
    }
    if isinstance(response.get("error"), dict):
        provider["error"] = response["error"]
    if response["status"] == "timeout":
        return _provider_failure_execution(
            model_summary=model_summary,
            model_config=model_config,
            max_tool_calls=max_tool_calls,
            started=started,
            budget_status="timeout",
            error="react openai-compatible provider timed out",
            provider=provider,
        )
    if response["status"] == "provider_error":
        return _provider_failure_execution(
            model_summary=model_summary,
            model_config=model_config,
            max_tool_calls=max_tool_calls,
            started=started,
            budget_status="provider_error",
            error="react openai-compatible provider failed",
            provider=provider,
        )
    budget_status, budget_error = _provider_budget_status(usage, config.get("budget"))
    if budget_error is not None:
        provider["status"] = budget_status
        return _provider_failure_execution(
            model_summary=model_summary,
            model_config=model_config,
            max_tool_calls=max_tool_calls,
            started=started,
            budget_status=budget_status,
            error=budget_error,
            provider=provider,
        )

    answer = response["content"]
    steps = [
        ReActStepEvidence(
            index=1,
            thought_summary="called the configured OpenAI-compatible provider inside the DAG node boundary",
            action={"type": "provider_call", "provider": "openai-compatible"},
            observation={"status": "completed", "answer_sha256": _sha256(answer)},
        ).to_dict()
    ]
    return _execution(
        status="completed",
        model=model_summary,
        steps=steps,
        max_steps=model_config.max_steps,
        max_tool_calls=max_tool_calls,
        tool_calls_used=0,
        budget_status=budget_status,
        started=started,
        answer=answer,
        provider=provider,
    )


def _provider_failure_execution(
    *,
    model_summary: dict[str, Any],
    model_config: ReActModelConfig,
    max_tool_calls: int,
    started: float,
    budget_status: str,
    error: str,
    provider: dict[str, Any],
) -> ReActExecution:
    return _execution(
        status="failed",
        model=model_summary,
        steps=[],
        max_steps=model_config.max_steps,
        max_tool_calls=max_tool_calls,
        tool_calls_used=0,
        budget_status=budget_status,
        started=started,
        error=error,
        provider=provider,
    )


def _call_openai_compatible_provider(model_config: ReActModelConfig, prompt: str) -> dict[str, Any]:
    base_url = model_config.base_url or ""
    if base_url == "memory://fake-openai":
        return {"status": "completed", "content": _fake_answer(prompt), "finish_reason": "stop"}
    if base_url == "memory://timeout":
        return {"status": "timeout", "content": "", "finish_reason": None}
    if base_url == "memory://provider-error":
        return {"status": "provider_error", "content": "", "finish_reason": None}
    if base_url.startswith(("http://", "https://")):
        return _call_http_provider(model_config, prompt)
    return {"status": "provider_error", "content": "", "finish_reason": None}


def _call_http_provider(model_config: ReActModelConfig, prompt: str) -> dict[str, Any]:
    url = f"{(model_config.base_url or '').rstrip('/')}/chat/completions"
    payload = json.dumps(
        {
            "model": model_config.model,
            "messages": [{"role": "user", "content": prompt}],
        }
    ).encode("utf-8")
    headers = {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {_api_key_value(model_config)}",
    }
    request = urllib.request.Request(url, data=payload, headers=headers, method="POST")
    try:
        with urllib.request.urlopen(request, timeout=_timeout_seconds(model_config.timeout_ms)) as response:
            body = json.loads(response.read().decode("utf-8"))
            status_code = int(getattr(response, "status", 200))
            if status_code >= 400:
                return _provider_http_error(status_code, body, secret_value=_api_key_value(model_config))
    except urllib.error.HTTPError as exc:
        return _http_error_response(exc, secret_value=_api_key_value(model_config))
    except TimeoutError:
        return {"status": "timeout", "content": "", "finish_reason": None}
    except urllib.error.URLError as exc:
        if isinstance(getattr(exc, "reason", None), TimeoutError):
            return {"status": "timeout", "content": "", "finish_reason": None}
        return _provider_exception_error(exc, secret_value=_api_key_value(model_config))
    except Exception as exc:
        return _provider_exception_error(exc, secret_value=_api_key_value(model_config))
    return _parse_http_provider_response(body)


def _parse_http_provider_response(body: dict[str, Any]) -> dict[str, Any]:
    choices = body.get("choices")
    if not isinstance(choices, list) or not choices:
        return _provider_parse_error("missing choices")
    first = choices[0]
    if not isinstance(first, dict):
        return _provider_parse_error("invalid first choice")
    message = first.get("message")
    content = message.get("content") if isinstance(message, dict) else first.get("text")
    if not isinstance(content, str):
        return _provider_parse_error("missing message content")
    finish_reason = first.get("finish_reason")
    return {
        "status": "completed",
        "content": content,
        "finish_reason": finish_reason if isinstance(finish_reason, str) else None,
        "usage": _http_usage(body.get("usage")),
    }


def _provider_request_summary(model_config: ReActModelConfig, prompt: str) -> dict[str, Any]:
    return {
        "endpoint": "/chat/completions",
        "message_count": 1,
        "prompt_sha256": _sha256(prompt),
        "timeout_ms": model_config.timeout_ms,
    }


def _provider_response_summary(response: dict[str, Any]) -> dict[str, Any]:
    content = response.get("content")
    content_text = content if isinstance(content, str) else ""
    return {
        "finish_reason": response.get("finish_reason"),
        "content_sha256": _sha256(content_text) if content_text else None,
        "content_length": len(content_text),
    }


def _provider_usage(prompt: str, response: dict[str, Any], budget: Any) -> dict[str, Any]:
    provider_usage = response.get("usage")
    if isinstance(provider_usage, dict):
        prompt_tokens = _non_negative_int(provider_usage.get("prompt_tokens"))
        completion_tokens = _non_negative_int(provider_usage.get("completion_tokens"))
        total_tokens = _non_negative_int(provider_usage.get("total_tokens"))
        if prompt_tokens is not None and completion_tokens is not None:
            if total_tokens is None:
                total_tokens = prompt_tokens + completion_tokens
            return _usage_summary(
                prompt_tokens=prompt_tokens,
                completion_tokens=completion_tokens,
                total_tokens=total_tokens,
                budget=budget,
                source="provider",
            )
    completion = response.get("content", "")
    completion_text = completion if isinstance(completion, str) else ""
    prompt_tokens = _estimate_tokens(prompt)
    completion_tokens = _estimate_tokens(completion_text)
    return _usage_summary(
        prompt_tokens=prompt_tokens,
        completion_tokens=completion_tokens,
        total_tokens=prompt_tokens + completion_tokens,
        budget=budget,
        source="estimated",
    )


def _usage_summary(
    *,
    prompt_tokens: int,
    completion_tokens: int,
    total_tokens: int,
    budget: Any,
    source: str,
) -> dict[str, Any]:
    prompt_rate = _number_budget(budget, "prompt_cost_per_1k_tokens")
    completion_rate = _number_budget(budget, "completion_cost_per_1k_tokens")
    estimated_cost = round((prompt_tokens / 1000 * prompt_rate) + (completion_tokens / 1000 * completion_rate), 8)
    return {
        "prompt_tokens": prompt_tokens,
        "completion_tokens": completion_tokens,
        "total_tokens": total_tokens,
        "estimated_cost_usd": estimated_cost,
        "source": source,
    }


def _provider_budget_status(usage: dict[str, Any], budget: Any) -> tuple[str, str | None]:
    if not isinstance(budget, dict):
        return "within_limits", None
    max_tokens = budget.get("max_total_tokens")
    if isinstance(max_tokens, int) and int(usage["total_tokens"]) > max_tokens:
        return "token_budget_exhausted", "react openai-compatible provider exceeded token budget"
    max_cost = budget.get("max_cost_usd")
    if isinstance(max_cost, int | float) and float(usage["estimated_cost_usd"]) > float(max_cost):
        return "cost_budget_exhausted", "react openai-compatible provider exceeded cost budget"
    return "within_limits", None


def _number_budget(budget: Any, key: str) -> float:
    if isinstance(budget, dict) and isinstance(budget.get(key), int | float):
        return float(budget[key])
    return 0.0


def _non_negative_int(value: Any) -> int | None:
    if isinstance(value, int) and not isinstance(value, bool) and value >= 0:
        return value
    return None


def _http_usage(value: Any) -> dict[str, int] | None:
    if not isinstance(value, dict):
        return None
    usage = {
        key: parsed
        for key, parsed in (
            ("prompt_tokens", _non_negative_int(value.get("prompt_tokens"))),
            ("completion_tokens", _non_negative_int(value.get("completion_tokens"))),
            ("total_tokens", _non_negative_int(value.get("total_tokens"))),
        )
        if parsed is not None
    }
    return usage or None


def _api_key_value(model_config: ReActModelConfig) -> str:
    return os.environ.get(model_config.api_key_env or "", "")


def _http_error_response(exc: urllib.error.HTTPError, *, secret_value: str) -> dict[str, Any]:
    try:
        body = json.loads(exc.read().decode("utf-8"))
    except Exception:
        body = None
    return _provider_http_error(exc.code, body, secret_value=secret_value)


def _provider_http_error(status_code: int, body: Any, *, secret_value: str = "") -> dict[str, Any]:
    provider_error = body.get("error") if isinstance(body, dict) else None
    message = provider_error.get("message") if isinstance(provider_error, dict) else None
    error_type = provider_error.get("type") if isinstance(provider_error, dict) else None
    return {
        "status": "provider_error",
        "content": "",
        "finish_reason": None,
        "error": {
            "status_code": status_code,
            "error_type": error_type if isinstance(error_type, str) else None,
            "message": _redacted_error_message(message, secret_value=secret_value),
            "retryable": status_code in {408, 409, 425, 429} or status_code >= 500,
        },
    }


def _provider_parse_error(message: str) -> dict[str, Any]:
    return {
        "status": "provider_error",
        "content": "",
        "finish_reason": None,
        "error": {
            "error_type": "invalid_response",
            "message": message,
            "retryable": False,
        },
    }


def _provider_exception_error(exc: BaseException, *, secret_value: str = "") -> dict[str, Any]:
    return {
        "status": "provider_error",
        "content": "",
        "finish_reason": None,
        "error": {
            "error_type": type(exc).__name__,
            "message": _redacted_error_message(str(exc), secret_value=secret_value),
            "retryable": isinstance(exc, urllib.error.URLError),
        },
    }


def _redacted_error_message(value: Any, *, secret_value: str = "") -> str | None:
    if not isinstance(value, str):
        return None
    redacted = value.replace(secret_value, "[REDACTED]") if secret_value else value
    return re.sub(r"sk-[A-Za-z0-9._-]+", "[REDACTED]", redacted)


def _estimate_tokens(value: str) -> int:
    words = [part for part in value.strip().split() if part]
    return max(1, len(words)) if value else 0


def _fake_answer(prompt: str) -> str:
    if prompt.startswith("Answer "):
        return prompt
    if prompt.startswith("Echo "):
        return prompt.removeprefix("Echo ")
    return prompt


def _timeout_seconds(timeout_ms: int | None) -> float | None:
    if timeout_ms is None:
        return None
    return max(timeout_ms / 1000, 0.001)


def _sha256(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _execution(
    *,
    status: str,
    model: dict[str, Any],
    steps: list[dict[str, Any]],
    max_steps: int,
    max_tool_calls: int,
    tool_calls_used: int,
    budget_status: str,
    started: float,
    answer: Any | None = None,
    error: str | None = None,
    latest_tool_invocation: dict[str, Any] | None = None,
    provider: dict[str, Any] | None = None,
) -> ReActExecution:
    react: dict[str, Any] = {
        "status": status,
        "model": model,
        "budget": {
            "max_steps": max_steps,
            "steps_used": len(steps),
            "max_tool_calls": max_tool_calls,
            "tool_calls_used": tool_calls_used,
            "status": budget_status,
        },
        "steps": steps,
    }
    if provider is not None:
        react["provider"] = provider
    output: dict[str, Any] = {
        "react": react,
        "duration_ms": int((time.perf_counter() - started) * 1000),
    }
    if answer is not None:
        output["answer"] = answer
    if error is not None:
        output["error"] = error
    if latest_tool_invocation is not None:
        output["tool_invocation"] = latest_tool_invocation
    return ReActExecution(status=status, output=output)


def _tool_invocation_from_output(output: dict[str, Any]) -> dict[str, Any] | None:
    invocation = output.get("tool_invocation")
    return dict(invocation) if isinstance(invocation, dict) else None


def _observation_output(output: dict[str, Any]) -> Any:
    if "result" in output:
        return {"result": output["result"]}
    if "stdout" in output or "stderr" in output or "exit_code" in output:
        return {
            key: output[key]
            for key in ("exit_code", "stdout", "stderr")
            if key in output
        }
    if "body" in output or "status_code" in output:
        return {
            key: output[key]
            for key in ("status_code", "body")
            if key in output
        }
    return output


def _answer_from_tool_output(output: dict[str, Any]) -> Any:
    if "result" in output:
        return output["result"]
    if isinstance(output.get("stdout"), str):
        return str(output["stdout"]).strip()
    if "body" in output:
        return output["body"]
    return _observation_output(output)
