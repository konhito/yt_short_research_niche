"""Helpers for talking to MCP servers over stdio."""

from __future__ import annotations

import asyncio
import json
import os
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from .config import load_config


URL_RE = re.compile(r"https?://[^\s\"'<>]+", re.IGNORECASE)


@dataclass
class MCPServerSpec:
    command: str
    args: list[str] = field(default_factory=list)
    env: dict[str, str] = field(default_factory=dict)
    cwd: str | None = None


def _normalize_spec(raw: Any) -> MCPServerSpec:
    if not isinstance(raw, dict):
        raise ValueError("MCP server config must be a mapping")

    command = str(raw.get("command", "")).strip()
    if not command:
        raise ValueError("MCP server config missing command")

    args = raw.get("args") or []
    if not isinstance(args, list):
        raise ValueError("MCP server args must be a list")

    env = raw.get("env") or {}
    if not isinstance(env, dict):
        raise ValueError("MCP server env must be a mapping")

    cwd = raw.get("cwd")
    return MCPServerSpec(
        command=command,
        args=[str(a) for a in args],
        env={str(k): str(v) for k, v in env.items()},
        cwd=str(cwd) if cwd else None,
    )


def load_mcp_servers() -> dict[str, MCPServerSpec]:
    """Load MCP server configs from env or the main config file."""
    servers: dict[str, Any] = {}

    raw_env = os.environ.get("VERTICALS_MCP_SERVERS_JSON")
    if raw_env:
        try:
            servers = json.loads(raw_env)
        except Exception as exc:
            raise ValueError(f"VERTICALS_MCP_SERVERS_JSON is invalid JSON: {exc}") from exc
    else:
        cfg = load_config()
        raw_cfg = cfg.get("MCP_SERVERS", {})
        if isinstance(raw_cfg, dict):
            servers = raw_cfg

    return {name: _normalize_spec(spec) for name, spec in servers.items()}


def get_mcp_server(name: str) -> MCPServerSpec:
    servers = load_mcp_servers()
    if name not in servers:
        raise KeyError(f"MCP server '{name}' is not configured")
    return servers[name]


def _extract_text(content: Any) -> str:
    if content is None:
        return ""
    if isinstance(content, str):
        return content
    if isinstance(content, dict):
        if "text" in content and isinstance(content["text"], str):
            return content["text"]
        return json.dumps(content, ensure_ascii=False)

    text_bits: list[str] = []
    for item in content:
        if isinstance(item, dict):
            if isinstance(item.get("text"), str):
                text_bits.append(item["text"])
        else:
            text = getattr(item, "text", None)
            if isinstance(text, str):
                text_bits.append(text)
    return "\n".join(text_bits)


def _strip_code_fences(text: str) -> str:
    cleaned = text.strip()
    if cleaned.startswith("```"):
        cleaned = cleaned.split("```", 2)[1]
        cleaned = cleaned.removeprefix("json").strip()
    return cleaned


def parse_tool_payload(result: Any) -> Any:
    """Best-effort conversion of an MCP tool result into structured data."""
    text = _strip_code_fences(_extract_text(getattr(result, "content", result)))
    if not text:
        return None

    candidates = [text]
    for start, end in (("{", "}"), ("[", "]")):
        s = text.find(start)
        e = text.rfind(end)
        if s != -1 and e != -1 and e > s:
            candidates.append(text[s : e + 1])

    for candidate in candidates:
        try:
            return json.loads(candidate)
        except Exception:
            continue
    return text


def extract_urls(payload: Any) -> list[str]:
    """Extract URLs from a parsed payload or raw text."""
    urls: list[str] = []

    def walk(value: Any):
        if value is None:
            return
        if isinstance(value, str):
            urls.extend(URL_RE.findall(value))
            return
        if isinstance(value, dict):
            for v in value.values():
                walk(v)
            return
        if isinstance(value, list):
            for item in value:
                walk(item)

    walk(payload)

    seen: set[str] = set()
    unique: list[str] = []
    for url in urls:
        if url not in seen:
            seen.add(url)
            unique.append(url)
    return unique


async def _call_tool_async(server: MCPServerSpec, tool_name: str, arguments: dict[str, Any], timeout: float):
    from mcp import ClientSession, StdioServerParameters
    from mcp.client.stdio import stdio_client

    env = os.environ.copy()
    env.update(server.env)

    params = StdioServerParameters(
        command=server.command,
        args=server.args,
        env=env,
        cwd=server.cwd,
    )

    async with stdio_client(params) as (read, write):
        async with ClientSession(read, write) as session:
            await asyncio.wait_for(session.initialize(), timeout=timeout)
            return await asyncio.wait_for(
                session.call_tool(tool_name, arguments=arguments),
                timeout=timeout,
            )


def call_mcp_tool(server_name: str, tool_name: str, arguments: dict[str, Any] | None = None, timeout: float = 120.0):
    """Call a tool on a configured MCP server."""
    server = get_mcp_server(server_name)
    return asyncio.run(_call_tool_async(server, tool_name, arguments or {}, timeout))

