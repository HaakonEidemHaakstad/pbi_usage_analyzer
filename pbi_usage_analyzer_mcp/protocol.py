"""Minimal Model Context Protocol server over stdio, standard library only.

Supports tools and prompts in both protocol eras (a "dual-era" server):

- legacy revisions (2025-11-25 and earlier): an `initialize` handshake selects the
  version; results carry no `resultType`;
- modern revisions (2026-07-28): every request names its version and client
  capabilities in `_meta`; `server/discover` is required; results carry
  `resultType` and the server's identity in `_meta`.

Framing is one JSON-RPC message per line on stdin/stdout (UTF-8). Nothing else may
be written to stdout, so `serve` points `sys.stdout` at stderr while it runs.
Specification: https://modelcontextprotocol.io/specification/2026-07-28
"""
from __future__ import annotations

import json
import sys
import traceback
from collections.abc import Callable
from dataclasses import dataclass, field

MODERN_VERSIONS = ("2026-07-28",)
LEGACY_VERSIONS = ("2025-11-25", "2025-06-18", "2025-03-26", "2024-11-05")

META_VERSION = "io.modelcontextprotocol/protocolVersion"
META_CAPABILITIES = "io.modelcontextprotocol/clientCapabilities"
META_SERVER_INFO = "io.modelcontextprotocol/serverInfo"

PARSE_ERROR = -32700
INVALID_REQUEST = -32600
METHOD_NOT_FOUND = -32601
INVALID_PARAMS = -32602
INTERNAL_ERROR = -32603
UNSUPPORTED_PROTOCOL_VERSION = -32022


class RpcError(Exception):
    """A JSON-RPC error response."""

    def __init__(self, code: int, message: str, data=None):
        super().__init__(message)
        self.code, self.message, self.data = code, message, data


class ToolError(Exception):
    """A tool execution error: reported to the model as a result with isError."""


@dataclass(frozen=True)
class Tool:
    name: str
    title: str
    description: str
    input_schema: dict
    handler: Callable[..., str]  # keyword arguments from the call -> text
    annotations: dict = field(default_factory=dict)

    def definition(self) -> dict:
        definition = {"name": self.name, "title": self.title, "description": self.description,
                      "inputSchema": self.input_schema}
        if self.annotations:
            definition["annotations"] = dict(self.annotations)
        return definition


@dataclass(frozen=True)
class PromptArgument:
    name: str
    description: str
    required: bool = False


@dataclass(frozen=True)
class PromptTemplate:
    name: str
    title: str
    description: str
    arguments: tuple[PromptArgument, ...]
    handler: Callable[..., str]  # keyword arguments (strings) -> user message text

    def definition(self) -> dict:
        return {"name": self.name, "title": self.title, "description": self.description,
                "arguments": [{"name": a.name, "description": a.description, "required": a.required}
                              for a in self.arguments]}


def _check_arguments(schema: dict, arguments: dict) -> str | None:
    """Problem with `arguments` under the small schema subset the tools use, or None."""
    properties = schema.get("properties", {})
    for name in schema.get("required", ()):
        if name not in arguments:
            return f"Missing required argument '{name}'."
    for name, value in arguments.items():
        spec = properties.get(name)
        if spec is None:
            return f"Unknown argument '{name}'."
        kind = spec.get("type")
        if kind == "string" and not isinstance(value, str):
            return f"Argument '{name}' must be a string."
        if kind == "boolean" and not isinstance(value, bool):
            return f"Argument '{name}' must be true or false."
        if kind == "string" and "enum" in spec and value not in spec["enum"]:
            return f"Argument '{name}' must be one of: {', '.join(spec['enum'])}."
        if kind == "array":
            if not isinstance(value, list):
                return f"Argument '{name}' must be a list."
            if spec.get("items", {}).get("type") == "object":
                # Item fields are checked by the tool, which explains problems per item.
                if not all(isinstance(item, dict) for item in value):
                    return f"Argument '{name}' must be a list of objects."
                continue
            allowed = spec.get("items", {}).get("enum")
            for item in value:
                if not isinstance(item, str) or (allowed is not None and item not in allowed):
                    return f"Argument '{name}' may only contain: {', '.join(allowed or ['strings'])}."
    return None


class McpServer:
    def __init__(self, name: str, title: str, version: str, instructions: str,
                 tools: tuple[Tool, ...], prompts: tuple[PromptTemplate, ...]):
        self.info = {"name": name, "title": title, "version": version}
        self.instructions = instructions
        self.tools = {tool.name: tool for tool in tools}
        self.prompts = {prompt.name: prompt for prompt in prompts}

    @property
    def capabilities(self) -> dict:
        return {"tools": {}, "prompts": {}}

    # -- message handling -------------------------------------------------

    def handle(self, message) -> dict | None:
        """Response to one decoded message; None for notifications and responses."""
        if not isinstance(message, dict):
            return self._error(None, INVALID_REQUEST, "Expected a JSON-RPC object.")
        if "method" not in message:
            return None  # a response; this server sends no requests
        request_id = message.get("id")
        notification = "id" not in message
        if message.get("jsonrpc") != "2.0" or not isinstance(message["method"], str):
            return None if notification else self._error(request_id, INVALID_REQUEST, "Invalid JSON-RPC request.")
        if notification:
            return None  # initialized, cancelled: nothing to do for synchronous requests
        if isinstance(request_id, bool) or not isinstance(request_id, (str, int)):
            return self._error(None, INVALID_REQUEST, "Request id must be a string or an integer.")
        try:
            params = message.get("params") or {}
            if not isinstance(params, dict):
                raise RpcError(INVALID_PARAMS, "params must be an object.")
            modern = self._era(message["method"], params)
            result = self._dispatch(message["method"], params, modern)
            if modern:
                result = {"resultType": "complete", **result,
                          "_meta": {**result.get("_meta", {}), META_SERVER_INFO: self.info}}
            return {"jsonrpc": "2.0", "id": request_id, "result": result}
        except RpcError as exc:
            return self._error(request_id, exc.code, exc.message, exc.data)
        except Exception as exc:  # report, never crash the server
            traceback.print_exc(file=sys.stderr)
            return self._error(request_id, INTERNAL_ERROR, f"Internal error: {exc}")

    def _era(self, method: str, params: dict) -> bool:
        """True for a modern request; raise for an unsupported or malformed one."""
        if method == "initialize":
            return False
        meta = params.get("_meta")
        version = meta.get(META_VERSION) if isinstance(meta, dict) else None
        if version is None:
            if method == "server/discover":
                raise RpcError(INVALID_PARAMS, f"Missing _meta field {META_VERSION}.")
            return False  # legacy request after (or without) initialize
        if version in LEGACY_VERSIONS:
            return False
        if version not in MODERN_VERSIONS:
            raise RpcError(UNSUPPORTED_PROTOCOL_VERSION, "Unsupported protocol version",
                           {"supported": [*MODERN_VERSIONS, *LEGACY_VERSIONS], "requested": version})
        if not isinstance(meta.get(META_CAPABILITIES), dict):
            raise RpcError(INVALID_PARAMS, f"Missing _meta field {META_CAPABILITIES}.")
        return True

    def _dispatch(self, method: str, params: dict, modern: bool) -> dict:
        if method == "initialize":
            requested = params.get("protocolVersion")
            version = requested if requested in LEGACY_VERSIONS else LEGACY_VERSIONS[0]
            return {"protocolVersion": version, "capabilities": self.capabilities,
                    "serverInfo": self.info, "instructions": self.instructions}
        if method == "server/discover":
            return {"supportedVersions": list(MODERN_VERSIONS), "capabilities": self.capabilities,
                    "instructions": self.instructions}
        if method == "ping":
            return {}
        if method == "tools/list":
            return {"tools": [tool.definition() for tool in self.tools.values()]}
        if method == "tools/call":
            return self._call_tool(params)
        if method == "prompts/list":
            return {"prompts": [prompt.definition() for prompt in self.prompts.values()]}
        if method == "prompts/get":
            return self._get_prompt(params)
        raise RpcError(METHOD_NOT_FOUND, f"Method not found: {method}")

    def _call_tool(self, params: dict) -> dict:
        tool = self.tools.get(params.get("name"))
        if tool is None:
            raise RpcError(INVALID_PARAMS, f"Unknown tool: {params.get('name')}")
        arguments = params.get("arguments") or {}
        if not isinstance(arguments, dict):
            raise RpcError(INVALID_PARAMS, "arguments must be an object.")
        problem = _check_arguments(tool.input_schema, arguments)
        try:
            if problem:
                raise ToolError(problem)
            text, is_error = tool.handler(**arguments), False
        except ToolError as exc:
            text, is_error = str(exc), True
        return {"content": [{"type": "text", "text": text}], "isError": is_error}

    def _get_prompt(self, params: dict) -> dict:
        prompt = self.prompts.get(params.get("name"))
        if prompt is None:
            raise RpcError(INVALID_PARAMS, f"Unknown prompt: {params.get('name')}")
        arguments = params.get("arguments") or {}
        known = {argument.name for argument in prompt.arguments}
        if not isinstance(arguments, dict) or not all(isinstance(v, str) for v in arguments.values()):
            raise RpcError(INVALID_PARAMS, "Prompt arguments must be strings.")
        for argument in prompt.arguments:
            if argument.required and not arguments.get(argument.name, "").strip():
                raise RpcError(INVALID_PARAMS, f"Missing required argument '{argument.name}'.")
        try:
            text = prompt.handler(**{k: v for k, v in arguments.items() if k in known})
        except ToolError as exc:
            raise RpcError(INVALID_PARAMS, str(exc)) from exc
        return {"description": prompt.description,
                "messages": [{"role": "user", "content": {"type": "text", "text": text}}]}

    @staticmethod
    def _error(request_id, code: int, message: str, data=None) -> dict:
        error = {"code": code, "message": message}
        if data is not None:
            error["data"] = data
        return {"jsonrpc": "2.0", "id": request_id, "error": error}

    # -- stdio transport --------------------------------------------------

    def handle_line(self, line: bytes) -> bytes | None:
        try:
            # Tolerate a byte-order mark (Windows PowerShell adds one when piping).
            message = json.loads(line.removeprefix(b"\xef\xbb\xbf").decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            response = self._error(None, PARSE_ERROR, f"Parse error: {exc}")
        else:
            response = self.handle(message)
        if response is None:
            return None
        # json.dumps escapes newlines inside strings, so one message is one line.
        return json.dumps(response, ensure_ascii=False, separators=(",", ":")).encode("utf-8") + b"\n"

    def serve(self, stdin=None, stdout=None) -> None:
        """Answer requests until stdin closes."""
        stdin = stdin or sys.stdin.buffer
        stdout = stdout or sys.stdout.buffer
        saved, sys.stdout = sys.stdout, sys.stderr  # stray prints must not corrupt the protocol
        try:
            for line in stdin:
                if not line.strip():
                    continue
                reply = self.handle_line(line.strip())
                if reply is not None:
                    stdout.write(reply)
                    stdout.flush()
        finally:
            sys.stdout = saved
