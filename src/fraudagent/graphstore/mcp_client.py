"""TigerGraph MCP client — the agent's graph tools, served over MCP.

The agent does not hold a database connection of its own. It starts the
official TigerGraph MCP server (`tigergraph-mcp`, https://github.com/tigergraph/
tigergraph-mcp) as a stdio subprocess and calls its tools:

    tigergraph__run_installed_query   every investigation query in graph/queries/
    tigergraph__get_node              transaction lookup by id
    tigergraph__get_node_edges        device and email-domain edges of a transaction

and nothing else: writes go through the installed `case_write` query (run via
run_installed_query), and `add_node` / `add_edge` / schema tools are refused by
the client-side allow-list (`TG_ALLOWED_TOOLS`).

The method names mirror pyTigerGraph's, so `TigerGraphStore` can use this
object and a direct `TigerGraphConnection` interchangeably, and fall back from
one to the other per call.

MCP is asynchronous; the agent is not. A private event loop runs on a daemon
thread for the life of the process, and each call is submitted to it, which
also makes the client safe to share across the UI server's worker threads.
"""

from __future__ import annotations

import asyncio
import atexit
import json
import os
import re
import sys
import threading
from contextlib import AsyncExitStack
from typing import Any

from ..config import TG

_JSON_BLOCK = re.compile(r"```json\s*(\{.*?\})\s*```", re.S)


DEFAULT_ALLOWED_TOOLS = ("tigergraph__run_installed_query", "tigergraph__get_node",
                         "tigergraph__get_node_edges")


def allowed_tools() -> frozenset[str]:
    raw = os.environ.get("TG_ALLOWED_TOOLS", "").strip()
    return frozenset(x.strip() for x in raw.split(",") if x.strip()) if raw         else frozenset(DEFAULT_ALLOWED_TOOLS)


class MCPToolError(RuntimeError):
    """The MCP server answered, but the tool reported a failure."""


class TigerGraphMCPClient:
    transport = "mcp"

    def __init__(self, start_timeout_s: float = 90.0) -> None:
        self.calls = 0
        self.tools: list[str] = []
        self._loop = asyncio.new_event_loop()
        self._thread = threading.Thread(target=self._loop.run_forever, daemon=True,
                                        name="tigergraph-mcp")
        self._thread.start()
        self._stack: AsyncExitStack | None = None
        self._session: Any = None
        self._errlog = open(os.devnull, "w")
        self._submit(self._open(), start_timeout_s)
        atexit.register(self.close)

    # ------------------------------------------------------------ plumbing ----
    def _server_env(self) -> dict[str, str]:
        """Our `.env` names (TG_GRAPH_NAME) mapped onto the server's (TG_GRAPHNAME)."""
        env = dict(os.environ)
        env.update({
            "TG_HOST": TG.host, "TG_GRAPHNAME": TG.graph, "TG_USERNAME": TG.username,
            "TG_PASSWORD": TG.password, "TG_SECRET": TG.secret or "",
            "TG_API_TOKEN": TG.token or "", "TG_RESTPP_PORT": str(TG.restpp_port),
            "TG_GS_PORT": str(TG.gsql_port),
            "TG_TGCLOUD": "true" if "tgcloud.io" in TG.host else "false",
        })
        return env

    async def _open(self) -> None:
        from mcp import ClientSession, StdioServerParameters
        from mcp.client.stdio import stdio_client

        params = StdioServerParameters(
            command=sys.executable,
            args=["-c", "from tigergraph_mcp.main import main; main()"],
            env=self._server_env())
        self._stack = AsyncExitStack()
        read, write = await self._stack.enter_async_context(
            stdio_client(params, errlog=self._errlog))
        self._session = await self._stack.enter_async_context(ClientSession(read, write))
        await self._session.initialize()
        self.tools = [t.name for t in (await self._session.list_tools()).tools]
        if "tigergraph__run_installed_query" not in self.tools:
            raise RuntimeError("tigergraph-mcp started but exposes no run_installed_query tool")

    def _submit(self, coro, timeout: float) -> Any:
        return asyncio.run_coroutine_threadsafe(coro, self._loop).result(timeout)

    def call(self, tool: str, args: dict[str, Any], timeout: float = 120.0) -> Any:
        """Call one MCP tool and return its `data` payload. Only allow-listed
        tools: the server exposes add_node / add_edge / schema tools too, and
        the agent must not be able to reach them."""
        drill = os.environ.get("DRILL_MCP_FAIL_AFTER", "").strip()
        if drill.isdigit() and self.calls >= int(drill):
            raise MCPToolError(f"drill: MCP server killed after {drill} calls")
        if tool not in allowed_tools():
            raise PermissionError(f"MCP tool {tool!r} is not on the agent allow-list "
                                  f"(TG_ALLOWED_TOOLS)")
        res = self._submit(self._session.call_tool(tool, args), timeout)
        self.calls += 1
        text = "".join(getattr(c, "text", "") for c in res.content)
        m = _JSON_BLOCK.search(text)
        payload = json.loads(m.group(1)) if m else {"success": not res.is_error, "data": text}
        if res.is_error or not payload.get("success", False):
            raise MCPToolError(f"{tool}: {payload.get('error') or payload.get('summary') or text[:300]}")
        return payload.get("data")

    def close(self) -> None:
        if self._stack is not None and self._loop.is_running():
            try:
                self._submit(self._stack.aclose(), 10)
            except Exception:
                pass
            self._stack = None
        if self._loop.is_running():
            self._loop.call_soon_threadsafe(self._loop.stop)

    # --------------------------------------------- pyTigerGraph-shaped API ----
    def runInstalledQuery(self, name: str, params: dict[str, Any] | None = None,
                          timeout: int | None = None) -> list[dict[str, Any]]:
        data = self.call("tigergraph__run_installed_query",
                         {"query_name": name, "params": params or {}},
                         timeout=max(60.0, (timeout or 60_000) / 1000))
        return (data or {}).get("result", [])

    def getVerticesById(self, vertex_type: str, vertex_id: str) -> list[dict[str, Any]]:
        try:
            node = self.call("tigergraph__get_node",
                             {"vertex_type": vertex_type, "vertex_id": str(vertex_id)})
        except MCPToolError as exc:
            if "not found" in str(exc).lower() or "not a valid vertex id" in str(exc).lower():
                return []
            raise
        if not node:
            return []
        return node if isinstance(node, list) else [node]

    def getEdges(self, vertex_type: str, vertex_id: str,
                 edge_type: str | None = None) -> list[dict[str, Any]]:
        args: dict[str, Any] = {"vertex_type": vertex_type, "vertex_id": str(vertex_id)}
        if edge_type:
            args["edge_type"] = edge_type
        data = self.call("tigergraph__get_node_edges", args) or {}
        return data.get("edges", []) if isinstance(data, dict) else list(data)
