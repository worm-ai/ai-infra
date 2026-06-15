from __future__ import annotations

import json
import shlex
import subprocess
import time
import urllib.error
import urllib.request
from dataclasses import dataclass
from string import Formatter
from typing import Any, Callable


@dataclass(frozen=True)
class ToolExecution:
    status: str
    output: dict[str, Any]


ToolCallable = Callable[[dict[str, Any]], Any]


class ToolRegistry:
    def __init__(self) -> None:
        self._python_tools: dict[str, ToolCallable] = {"echo": _echo_tool}

    def register_python(self, name: str, tool: ToolCallable) -> None:
        self._python_tools[name] = tool

    def execute(self, config: dict[str, Any], context: dict[str, Any]) -> ToolExecution:
        started = time.perf_counter()
        adapter = str(config.get("adapter", ""))
        try:
            if adapter == "python":
                output = self._execute_python(config, context)
            elif adapter == "shell":
                output = self._execute_shell(config, context)
            elif adapter == "http":
                output = self._execute_http(config, context)
            else:
                raise RuntimeError(f"unsupported tool adapter {adapter!r}")
            status = "completed"
        except ToolFailure as exc:
            status = "failed"
            output = dict(exc.output)
        except Exception as exc:  # tool errors are run evidence, not process crashes
            status = "failed"
            output = {"error": str(exc)}
        output["adapter"] = adapter
        output["duration_ms"] = int((time.perf_counter() - started) * 1000)
        return ToolExecution(status=status, output=output)

    def _execute_python(self, config: dict[str, Any], context: dict[str, Any]) -> dict[str, Any]:
        name = str(config.get("name", ""))
        if name not in self._python_tools:
            raise RuntimeError(f"unknown python tool {name!r}")
        args = _render_value(config.get("args", {}), context)
        result = self._python_tools[name](args)
        return {"name": name, "args": args, "result": result}

    def _execute_shell(self, config: dict[str, Any], context: dict[str, Any]) -> dict[str, Any]:
        command = config.get("command")
        if not isinstance(command, str) or not command.strip():
            raise RuntimeError("shell tool requires command")
        rendered_command = _render_template(command, context)
        timeout_seconds = int(config.get("timeout_seconds", 30))
        completed = subprocess.run(
            shlex.split(rendered_command),
            text=True,
            capture_output=True,
            check=False,
            timeout=timeout_seconds,
        )
        output = {
            "command": rendered_command,
            "exit_code": completed.returncode,
            "stdout": completed.stdout,
            "stderr": completed.stderr,
        }
        if completed.returncode != 0:
            output["error"] = f"shell tool exited with exit code {completed.returncode}"
            raise ToolFailure(output)
        return output

    def _execute_http(self, config: dict[str, Any], context: dict[str, Any]) -> dict[str, Any]:
        method = str(config.get("method", "GET")).upper()
        url = str(config.get("url", ""))
        body = _render_value(config.get("json"), context)
        if url == "memory://echo":
            return {"method": method, "url": url, "status_code": 200, "body": body}
        if not url.startswith(("http://", "https://")):
            raise RuntimeError(f"unsupported http tool url {url!r}")
        request_body = None if body is None else json.dumps(body).encode("utf-8")
        request = urllib.request.Request(
            url,
            data=request_body,
            method=method,
            headers={"Content-Type": "application/json"},
        )
        try:
            with urllib.request.urlopen(request, timeout=int(config.get("timeout_seconds", 30))) as response:
                response_body = response.read().decode("utf-8")
                parsed_body = _parse_json_or_text(response_body)
                return {
                    "method": method,
                    "url": url,
                    "status_code": response.status,
                    "body": parsed_body,
                }
        except urllib.error.HTTPError as exc:
            raise RuntimeError(f"http tool returned status {exc.code}") from exc


class ToolFailure(RuntimeError):
    def __init__(self, output: dict[str, Any]) -> None:
        super().__init__(str(output.get("error", "tool failed")))
        self.output = output


def _echo_tool(args: dict[str, Any]) -> Any:
    return args.get("value")


def _render_value(value: Any, context: dict[str, Any]) -> Any:
    if isinstance(value, str):
        return _render_template(value, context)
    if isinstance(value, list):
        return [_render_value(item, context) for item in value]
    if isinstance(value, dict):
        return {key: _render_value(item, context) for key, item in value.items()}
    return value


def _render_template(template: str, context: dict[str, Any]) -> str:
    rendered = []
    for literal_text, field_name, format_spec, conversion in Formatter().parse(template):
        rendered.append(literal_text)
        if not field_name:
            continue
        value = _lookup_context(field_name, context)
        if conversion == "r":
            value = repr(value)
        elif conversion == "s":
            value = str(value)
        if format_spec:
            rendered.append(format(value, format_spec))
        else:
            rendered.append(str(value))
    return "".join(rendered)


def _lookup_context(field_name: str, context: dict[str, Any]) -> Any:
    current: Any = context
    for part in field_name.split("."):
        if isinstance(current, dict) and part in current:
            current = current[part]
        else:
            raise KeyError(field_name)
    return current


def _parse_json_or_text(value: str) -> Any:
    try:
        return json.loads(value)
    except json.JSONDecodeError:
        return value


default_tool_registry = ToolRegistry()


def execute_tool(config: dict[str, Any], context: dict[str, Any]) -> ToolExecution:
    return default_tool_registry.execute(config, context)
