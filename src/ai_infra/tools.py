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
class ToolInvocation:
    adapter: str
    identity: str
    input: dict[str, Any]
    reserved: bool = False

    def to_dict(self) -> dict[str, Any]:
        return {
            "adapter": self.adapter,
            "identity": self.identity,
            "input": self.input,
            "reserved": self.reserved,
        }


@dataclass(frozen=True)
class ToolInvocationEvidence:
    adapter: str
    identity: str
    input: dict[str, Any]
    output: Any
    error: str | None
    status: str
    duration_ms: int
    reserved: bool = False

    def to_dict(self) -> dict[str, Any]:
        return {
            "adapter": self.adapter,
            "identity": self.identity,
            "input": self.input,
            "output": self.output,
            "error": self.error,
            "status": self.status,
            "duration_ms": self.duration_ms,
            "reserved": self.reserved,
        }


@dataclass(frozen=True)
class ToolExecution:
    status: str
    output: dict[str, Any]


ToolCallable = Callable[[dict[str, Any]], Any]


class ToolRegistry:
    def __init__(self) -> None:
        self._flaky_attempts: dict[str, int] = {}
        self._python_tools: dict[str, ToolCallable] = {
            "echo": _echo_tool,
            "flaky_once": self._flaky_once_tool,
            "always_fails": _always_fails_tool,
        }

    def register_python(self, name: str, tool: ToolCallable) -> None:
        self._python_tools[name] = tool

    def execute(self, config: dict[str, Any], context: dict[str, Any]) -> ToolExecution:
        started = time.perf_counter()
        adapter = str(config.get("adapter", ""))
        invocation: ToolInvocation | None = None
        raw_output: dict[str, Any] = {}
        try:
            invocation = build_tool_invocation(config, context)
            adapter = invocation.adapter
            if invocation.adapter == "python":
                raw_output = self._execute_python(invocation)
            elif invocation.adapter == "shell":
                raw_output = self._execute_shell(invocation)
            elif invocation.adapter == "http":
                raw_output = self._execute_http(invocation)
            elif invocation.adapter == "mcp":
                raw_output = self._execute_mcp(invocation)
            else:
                raise RuntimeError(f"unsupported tool adapter {invocation.adapter!r}")
            status = "completed"
        except ToolFailure as exc:
            status = "failed"
            raw_output = dict(exc.output)
        except Exception as exc:  # tool errors are run evidence, not process crashes
            status = "failed"
            raw_output = {"error": str(exc)}
        output = dict(raw_output)
        output["adapter"] = adapter
        duration_ms = int((time.perf_counter() - started) * 1000)
        output["duration_ms"] = duration_ms
        if invocation is not None:
            output["tool_invocation"] = ToolInvocationEvidence(
                adapter=invocation.adapter,
                identity=invocation.identity,
                input=invocation.input,
                output=_invocation_output(invocation, raw_output),
                error=raw_output.get("error") if isinstance(raw_output.get("error"), str) else None,
                status=status,
                duration_ms=duration_ms,
                reserved=invocation.reserved,
            ).to_dict()
        return ToolExecution(status=status, output=output)

    def _execute_python(self, invocation: ToolInvocation) -> dict[str, Any]:
        name = str(invocation.input.get("name", ""))
        if name not in self._python_tools:
            raise RuntimeError(f"unknown python tool {name!r}")
        args = invocation.input.get("args", {})
        if not isinstance(args, dict):
            raise RuntimeError("python tool args must be a mapping")
        result = self._python_tools[name](args)
        return {"name": name, "args": args, "result": result}

    def _execute_shell(self, invocation: ToolInvocation) -> dict[str, Any]:
        command = invocation.input.get("command")
        if not isinstance(command, str) or not command.strip():
            raise RuntimeError("shell tool requires command")
        timeout_seconds = int(invocation.input.get("timeout_seconds", 30))
        completed = subprocess.run(
            shlex.split(command),
            text=True,
            capture_output=True,
            check=False,
            timeout=timeout_seconds,
        )
        output = {
            "command": command,
            "exit_code": completed.returncode,
            "stdout": completed.stdout,
            "stderr": completed.stderr,
        }
        if completed.returncode != 0:
            output["error"] = f"shell tool exited with exit code {completed.returncode}"
            raise ToolFailure(output)
        return output

    def _execute_http(self, invocation: ToolInvocation) -> dict[str, Any]:
        method = str(invocation.input.get("method", "GET")).upper()
        url = str(invocation.input.get("url", ""))
        body = invocation.input.get("json")
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
            with urllib.request.urlopen(request, timeout=int(invocation.input.get("timeout_seconds", 30))) as response:
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

    def _execute_mcp(self, invocation: ToolInvocation) -> dict[str, Any]:
        if invocation.reserved:
            raise ToolFailure({"error": "mcp adapter is reserved and not implemented"})
        runtime = str(invocation.input.get("runtime", ""))
        server = str(invocation.input.get("server", ""))
        tool_name = str(invocation.input.get("tool", ""))
        args = invocation.input.get("args", {})
        if not isinstance(args, dict):
            raise RuntimeError("mcp tool args must be a mapping")
        timeout_seconds = int(invocation.input.get("timeout_seconds", 30))
        mcp_base = _mcp_summary(
            runtime=runtime,
            server=server,
            tool_name=tool_name,
            status="running",
            args=args,
            timeout_seconds=timeout_seconds,
        )
        if runtime != "local":
            message = f"unsupported mcp runtime {runtime!r}"
            raise ToolFailure(_mcp_failure_output(mcp_base, message, "unsupported_runtime", retryable=False))
        if server != "local-memory":
            message = f"unknown mcp server {server!r}"
            raise ToolFailure(_mcp_failure_output(mcp_base, message, "server_error", retryable=False))
        if tool_name == "echo":
            result = dict(args)
            mcp = dict(mcp_base)
            mcp["status"] = "completed"
            mcp["response"] = _mcp_response_summary(result)
            return {
                "server": server,
                "tool": tool_name,
                "runtime": runtime,
                "result": result,
                "mcp": mcp,
            }
        if tool_name == "fail":
            message_arg = args.get("message", "mcp tool failed")
            message = f"mcp tool {server}.{tool_name} failed: {message_arg}"
            raise ToolFailure(_mcp_failure_output(mcp_base, message, "tool_error", retryable=False))
        if tool_name == "timeout":
            message = f"mcp tool {server}.{tool_name} timed out after {timeout_seconds}s"
            raise ToolFailure(_mcp_failure_output(mcp_base, message, "timeout", retryable=True))
        if tool_name == "malformed":
            message = f"mcp tool {server}.{tool_name} returned malformed response"
            raise ToolFailure(_mcp_failure_output(mcp_base, message, "malformed_response", retryable=False))
        message = f"unknown mcp tool {server}.{tool_name}"
        raise ToolFailure(_mcp_failure_output(mcp_base, message, "tool_not_found", retryable=False))

    def _flaky_once_tool(self, args: dict[str, Any]) -> Any:
        key = json.dumps(args, ensure_ascii=False, sort_keys=True)
        attempt = self._flaky_attempts.get(key, 0) + 1
        self._flaky_attempts[key] = attempt
        if attempt == 1:
            raise RuntimeError("temporary outage")
        return args.get("value")


class ToolFailure(RuntimeError):
    def __init__(self, output: dict[str, Any]) -> None:
        super().__init__(str(output.get("error", "tool failed")))
        self.output = output


def _echo_tool(args: dict[str, Any]) -> Any:
    return args.get("value")


def _always_fails_tool(args: dict[str, Any]) -> Any:
    raise RuntimeError(f"permanent outage for {args.get('value')}")


def build_tool_invocation(config: dict[str, Any], context: dict[str, Any]) -> ToolInvocation:
    adapter = str(config.get("adapter", ""))
    if adapter == "python":
        name = str(config.get("name", ""))
        args = _render_value(config.get("args", {}), context)
        if not isinstance(args, dict):
            raise RuntimeError("python tool args must be a mapping")
        return ToolInvocation(
            adapter=adapter,
            identity=name,
            input={"args": args, "name": name},
        )
    if adapter == "shell":
        command = config.get("command")
        if not isinstance(command, str) or not command.strip():
            raise RuntimeError("shell tool requires command")
        rendered_command = _render_template(command, context)
        tool_input: dict[str, Any] = {"command": rendered_command}
        if "timeout_seconds" in config:
            tool_input["timeout_seconds"] = int(config["timeout_seconds"])
        return ToolInvocation(adapter=adapter, identity=rendered_command, input=tool_input)
    if adapter == "http":
        method = str(config.get("method", "GET")).upper()
        url = str(config.get("url", ""))
        tool_input = {"method": method, "url": url}
        if "json" in config:
            tool_input["json"] = _render_value(config.get("json"), context)
        if "timeout_seconds" in config:
            tool_input["timeout_seconds"] = int(config["timeout_seconds"])
        return ToolInvocation(
            adapter=adapter,
            identity=f"{method} {url}",
            input=tool_input,
        )
    if adapter == "mcp":
        server = str(config.get("server", ""))
        tool_name = str(config.get("tool", ""))
        args = _render_value(config.get("args", {}), context)
        if not isinstance(args, dict):
            raise RuntimeError("mcp tool args must be a mapping")
        tool_input: dict[str, Any] = {"server": server, "tool": tool_name, "args": args}
        runtime = config.get("runtime")
        if runtime is not None:
            tool_input = {"runtime": str(runtime), **tool_input}
        if "timeout_seconds" in config:
            tool_input["timeout_seconds"] = int(config["timeout_seconds"])
        return ToolInvocation(
            adapter=adapter,
            identity=f"{server}.{tool_name}",
            input=tool_input,
            reserved=runtime is None,
        )
    return ToolInvocation(adapter=adapter, identity=adapter, input=dict(config))


def _invocation_output(invocation: ToolInvocation, output: dict[str, Any]) -> Any:
    if invocation.adapter == "python" and "result" in output:
        return {"result": output["result"]}
    if invocation.adapter == "shell":
        return {key: output[key] for key in ("exit_code", "stdout", "stderr") if key in output} or None
    if invocation.adapter == "http":
        return {key: output[key] for key in ("status_code", "body") if key in output} or None
    if invocation.adapter == "mcp" and not invocation.reserved:
        payload: dict[str, Any] = {}
        if "result" in output:
            payload["result"] = output["result"]
        if isinstance(output.get("mcp"), dict):
            payload["mcp"] = output["mcp"]
        return payload or None
    return None


def _mcp_summary(
    *,
    runtime: str,
    server: str,
    tool_name: str,
    status: str,
    args: dict[str, Any],
    timeout_seconds: int,
) -> dict[str, Any]:
    return {
        "runtime": runtime,
        "server": server,
        "tool": tool_name,
        "status": status,
        "request": {
            "args_keys": sorted(str(key) for key in args),
            "timeout_seconds": timeout_seconds,
        },
    }


def _mcp_response_summary(result: Any) -> dict[str, Any]:
    if isinstance(result, dict):
        return {"result_type": "object", "result_keys": sorted(str(key) for key in result)}
    if isinstance(result, list):
        return {"result_type": "array", "items": len(result)}
    return {"result_type": _type_name(result)}


def _mcp_failure_output(
    mcp: dict[str, Any],
    message: str,
    status: str,
    *,
    retryable: bool,
) -> dict[str, Any]:
    evidence = dict(mcp)
    evidence["status"] = status
    evidence["error"] = {"type": status, "message": message, "retryable": retryable}
    return {
        "server": evidence.get("server"),
        "tool": evidence.get("tool"),
        "runtime": evidence.get("runtime"),
        "error": message,
        "mcp": evidence,
    }


def _type_name(value: Any) -> str:
    if isinstance(value, dict):
        return "object"
    if isinstance(value, list):
        return "array"
    if isinstance(value, bool):
        return "boolean"
    if isinstance(value, int):
        return "integer"
    if isinstance(value, float):
        return "number"
    if isinstance(value, str):
        return "string"
    if value is None:
        return "null"
    return type(value).__name__


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
