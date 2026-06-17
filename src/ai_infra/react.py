from __future__ import annotations

import hashlib
import time
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

    def to_summary(self) -> dict[str, Any]:
        return {
            "provider": self.provider,
            "model": self.model,
            "base_url": self.base_url,
            "api_key_env": self.api_key_env,
            "prompt_sha256": hashlib.sha256(self.prompt.encode("utf-8")).hexdigest(),
            "max_steps": self.max_steps,
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

    if model_config.provider != "mock":
        return _execution(
            status="failed",
            model=model_summary,
            steps=steps,
            max_steps=model_config.max_steps,
            max_tool_calls=max_tool_calls,
            tool_calls_used=tool_calls_used,
            budget_status="provider_reserved",
            started=started,
            error="react provider 'openai-compatible' is reserved for future live execution; use provider 'mock'",
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
    )


def _max_tool_calls(config: dict[str, Any], max_steps: int) -> int:
    budget = config.get("budget")
    if isinstance(budget, dict) and isinstance(budget.get("max_tool_calls"), int):
        return int(budget["max_tool_calls"])
    tools = config.get("tools", [])
    if isinstance(tools, list) and tools:
        return min(1, max_steps)
    return 0


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
) -> ReActExecution:
    output: dict[str, Any] = {
        "react": {
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
        },
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
