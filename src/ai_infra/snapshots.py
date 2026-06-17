from __future__ import annotations

import yaml
from typing import Any


REDACTED_PROMPT_MARKER = "[REDACTED_PROMPT]"


def redacted_workflow_snapshot(snapshot: str) -> str:
    try:
        payload = yaml.safe_load(snapshot)
    except yaml.YAMLError:
        return _redact_prompt_lines(snapshot)
    if not isinstance(payload, dict):
        return _redact_prompt_lines(snapshot)
    redacted = _redact_prompt_values(payload)
    return yaml.safe_dump(redacted, allow_unicode=True, sort_keys=False).strip()


def _redact_prompt_values(value: Any) -> Any:
    if isinstance(value, dict):
        return {
            key: REDACTED_PROMPT_MARKER if key == "prompt" and isinstance(item, str) else _redact_prompt_values(item)
            for key, item in value.items()
        }
    if isinstance(value, list):
        return [_redact_prompt_values(item) for item in value]
    return value


def _redact_prompt_lines(snapshot: str) -> str:
    lines = []
    for line in snapshot.splitlines():
        stripped = line.lstrip()
        if stripped.startswith("prompt:"):
            indent = line[: len(line) - len(stripped)]
            lines.append(f"{indent}prompt: {REDACTED_PROMPT_MARKER}")
            continue
        lines.append(line)
    return "\n".join(lines)
