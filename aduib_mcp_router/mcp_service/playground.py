from __future__ import annotations

import json
from typing import Any

from starlette.responses import HTMLResponse, JSONResponse

from aduib_mcp_router.app import app

mcp = app.mcp
router_manager = app.router_manager


PLAYGROUND_HTML = """<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1.0" />
  <title>MCP Router Playground</title>
  <style>
    :root {
      font-family: "Segoe UI", Arial, sans-serif;
      color: #111;
      background-color: #f5f5f7;
    }
    body {
      margin: 0;
      padding: 0 1.5rem 2rem;
      min-height: 100vh;
    }
    header {
      padding: 2rem 0 1rem;
    }
    h1 {
      margin: 0 0 0.5rem;
      font-size: 2rem;
    }
    .summary {
      display: flex;
      gap: 1rem;
      flex-wrap: wrap;
    }
    .card {
      background: #fff;
      border-radius: 0.75rem;
      box-shadow: 0 10px 30px rgba(15,23,42,0.08);
      padding: 1rem 1.25rem;
      flex: 1 1 200px;
      min-width: 220px;
    }
    .card h3 {
      margin: 0;
      font-size: 0.9rem;
      color: #64748b;
      text-transform: uppercase;
      letter-spacing: 0.05em;
    }
    .card span {
      display: block;
      margin-top: 0.4rem;
      font-size: 1.8rem;
      font-weight: 600;
      color: #0f172a;
    }
    section {
      margin-top: 2rem;
    }
    section h2 {
      margin-bottom: 0.5rem;
    }
    table {
      width: 100%;
      border-collapse: collapse;
      background: #fff;
      border-radius: 0.75rem;
      overflow: hidden;
      box-shadow: 0 10px 30px rgba(15,23,42,0.08);
    }
    th, td {
      padding: 0.75rem 1rem;
      text-align: left;
      border-bottom: 1px solid #f1f5f9;
      vertical-align: top;
    }
    th {
      background: #f8fafc;
      font-size: 0.85rem;
      color: #475569;
    }
    tr:last-child td {
      border-bottom: none;
    }
    .pagination {
      display: flex;
      align-items: center;
      justify-content: flex-end;
      gap: 0.5rem;
      margin-top: 0.4rem;
      font-size: 0.9rem;
      color: #475569;
    }
    .pagination button {
      border: none;
      background: #0ea5e9;
      color: #fff;
      padding: 0.3rem 0.8rem;
      border-radius: 999px;
      cursor: pointer;
      font-size: 0.85rem;
    }
    .pagination button:disabled {
      background: #cbd5f5;
      cursor: not-allowed;
    }
    code, pre {
      font-family: "JetBrains Mono", "Fira Code", monospace;
      font-size: 0.85rem;
    }
    pre {
      margin: 0.25rem 0 0;
      white-space: pre-wrap;
    }
    .tag {
      display: inline-flex;
      align-items: center;
      padding: 0.15rem 0.5rem;
      margin: 0.1rem;
      border-radius: 999px;
      background-color: #e2e8f0;
      font-size: 0.75rem;
      color: #0f172a;
    }
    footer {
      margin-top: 2rem;
      text-align: center;
      color: #94a3b8;
      font-size: 0.85rem;
    }
    .muted {
      color: #94a3b8;
    }
  </style>
</head>
<body>
  <header>
    <h1>MCP Router Playground</h1>
    <p class="muted">Inspect the servers, tools, resources, and prompts currently loaded into the router.</p>
    <div class="summary" id="summary">
      <div class="card">
        <h3>Servers</h3>
        <span id="summary-servers">-</span>
      </div>
      <div class="card">
        <h3>Tools</h3>
        <span id="summary-tools">-</span>
      </div>
      <div class="card">
        <h3>Resources</h3>
        <span id="summary-resources">-</span>
      </div>
      <div class="card">
        <h3>Prompts</h3>
        <span id="summary-prompts">-</span>
      </div>
    </div>
  </header>

  <section>
    <h2>Servers</h2>
    <table id="servers-table">
      <thead>
        <tr>
          <th>Name</th>
          <th>Type</th>
          <th>Command / URL</th>
          <th>Tool Count</th>
        </tr>
      </thead>
      <tbody></tbody>
    </table>
    <div class="pagination" id="servers-pagination"></div>
  </section>

  <section>
    <h2>Tools</h2>
    <table id="tools-table">
      <thead>
        <tr>
          <th>Name</th>
          <th>Description</th>
          <th>Input Schema</th>
          <th>Server</th>
        </tr>
      </thead>
      <tbody></tbody>
    </table>
    <div class="pagination" id="tools-pagination"></div>
  </section>

  <section>
    <h2>Resources</h2>
    <table id="resources-table">
      <thead>
        <tr>
          <th>Name</th>
          <th>URI</th>
          <th>Description</th>
          <th>Server</th>
        </tr>
      </thead>
      <tbody></tbody>
    </table>
    <div class="pagination" id="resources-pagination"></div>
  </section>

  <section>
    <h2>Prompts</h2>
    <table id="prompts-table">
      <thead>
        <tr>
          <th>Name</th>
          <th>Description</th>
          <th>Arguments</th>
          <th>Server</th>
        </tr>
      </thead>
      <tbody></tbody>
    </table>
    <div class="pagination" id="prompts-pagination"></div>
  </section>

  <footer>Generated by MCP Router Playground</footer>

  <script>
    const text = (value) => (value === null || value === undefined || value === '' ? '<span class="muted">n/a</span>' : value);
    const tableState = {
      servers: { data: [], page: 1, pageSize: 10 },
      tools: { data: [], page: 1, pageSize: 10 },
      resources: { data: [], page: 1, pageSize: 10 },
      prompts: { data: [], page: 1, pageSize: 10 }
    };

    function renderTable(id, rows) {
      document.querySelector(`#${id} tbody`).innerHTML = rows.length ? rows.join('') : '<tr><td colspan="4" class="muted">No data</td></tr>';
    }

    function formatJSON(value) {
      return value ? `<pre>${escapeHtml(value)}</pre>` : '<span class="muted">n/a</span>';
    }

    async function loadData() {
      const resp = await fetch('./playground/data');
      if (!resp.ok) {
        throw new Error('Failed to load Playground data');
      }
      return resp.json();
    }

    function escapeHtml(str) {
      return str.replace(/[&<>'"]/g, (c) => ({
        '&': '&amp;',
        '<': '&lt;',
        '>': '&gt;',
        '"': '&quot;',
        "'": '&#39;'
      }[c]));
    }

    function renderSummary(data) {
      document.getElementById('summary-servers').textContent = data.servers.length;
      document.getElementById('summary-tools').textContent = data.tools.length;
      document.getElementById('summary-resources').textContent = data.resources.length;
      document.getElementById('summary-prompts').textContent = data.prompts.length;
    }

    function paginate(list, page, pageSize) {
      const start = (page - 1) * pageSize;
      return list.slice(start, start + pageSize);
    }

    function renderPagination(name, total) {
      const state = tableState[name];
      const totalPages = Math.max(1, Math.ceil(total / state.pageSize));
      state.page = Math.min(state.page, totalPages);
      const container = document.getElementById(`${name}-pagination`);
      container.innerHTML = `
        <button onclick="changePage('${name}', -1)" ${state.page <= 1 ? 'disabled' : ''}>Prev</button>
        <span>Page ${state.page} / ${totalPages}</span>
        <button onclick="changePage('${name}', 1)" ${state.page >= totalPages ? 'disabled' : ''}>Next</button>
      `;
    }

    window.changePage = (name, delta) => {
      const state = tableState[name];
      state.page = Math.max(1, state.page + delta);
      renderAll();
    };

    function renderServers() {
      const state = tableState.servers;
      const rows = paginate(state.data, state.page, state.pageSize).map((server) => `
        <tr>
          <td><strong>${escapeHtml(server.name)}</strong><br/><span class="muted">${escapeHtml(server.id)}</span></td>
          <td>${escapeHtml(server.type || 'stdio')}</td>
          <td>${formatJSON(server.details)}</td>
          <td>${server.tool_count}</td>
        </tr>
      `);
      renderTable('servers-table', rows);
      renderPagination('servers', state.data.length);
    }

    function renderTools() {
      const state = tableState.tools;
      const rows = paginate(state.data, state.page, state.pageSize).map((tool) => `
        <tr>
          <td><strong>${escapeHtml(tool.name)}</strong></td>
          <td>${escapeHtml(tool.description || '')}</td>
          <td>${formatJSON(tool.input_schema)}</td>
          <td>${escapeHtml(tool.server_name || '')}</td>
        </tr>
      `);
      renderTable('tools-table', rows);
      renderPagination('tools', state.data.length);
    }

    function renderResources() {
      const state = tableState.resources;
      const rows = paginate(state.data, state.page, state.pageSize).map((resource) => `
        <tr>
          <td>${escapeHtml(resource.name || '')}</td>
          <td>${escapeHtml(resource.uri || '')}</td>
          <td>${escapeHtml(resource.description || '')}</td>
          <td>${escapeHtml(resource.server_name || '')}</td>
        </tr>
      `);
      renderTable('resources-table', rows);
      renderPagination('resources', state.data.length);
    }

    function renderPrompts() {
      const state = tableState.prompts;
      const rows = paginate(state.data, state.page, state.pageSize).map((prompt) => `
        <tr>
          <td>${escapeHtml(prompt.name)}</td>
          <td>${escapeHtml(prompt.description || '')}</td>
          <td>
            ${(prompt.arguments || []).map(arg => `<span class="tag">${escapeHtml(arg.name)}${arg.required ? '*' : ''}</span>`).join('')}
          </td>
          <td>${escapeHtml(prompt.server_name || '')}</td>
        </tr>
      `);
      renderTable('prompts-table', rows);
      renderPagination('prompts', state.data.length);
    }

    function renderAll() {
      renderServers();
      renderTools();
      renderResources();
      renderPrompts();
    }

    async function init() {
      try {
        const data = await loadData();
        renderSummary(data);
        tableState.servers.data = data.servers;
        tableState.tools.data = data.tools;
        tableState.resources.data = data.resources;
        tableState.prompts.data = data.prompts;
        renderAll();
      } catch (err) {
        document.body.innerHTML = '<p style="color:#ef4444;font-size:1.2rem;">Failed to load Playground data.</p><pre>' + err.message + '</pre>';
      }
    }

    init();
  </script>
</body>
</html>
"""


def _dump_model(value: Any) -> Any:
    """Try to convert Pydantic/attrs objects to plain dicts."""
    dump = getattr(value, "model_dump", None)
    if callable(dump):
        return dump()
    if hasattr(value, "__dict__"):
        return {k: v for k, v in value.__dict__.items() if not k.startswith("_")}
    return value


def _pretty_json(value: Any) -> str | None:
    if value is None:
        return None
    try:
        return json.dumps(value, ensure_ascii=False, indent=2)
    except TypeError:
        return str(value)


@mcp.custom_route("/playground", methods=["GET"])
async def playground_page(request):
    """Serve a lightweight HTML playground page."""
    return HTMLResponse(PLAYGROUND_HTML)


@mcp.custom_route("/playground/data", methods=["GET"])
async def playground_data(request):
    """Return JSON payload describing currently loaded servers/tools/resources/prompts."""
    tools = await router_manager.list_tools()
    resources = await router_manager.list_resources()
    prompts = await router_manager.list_prompts()

    server_lookup = {
        server_id: router_manager.get_mcp_server(server_id)
        for server_id in router_manager._mcp_server_cache  # noqa: SLF001
    }

    tool_server_lookup: dict[str, str | None] = {}
    for server_id, server_tools in router_manager._mcp_server_tools_cache.items():  # noqa: SLF001
        server = server_lookup.get(server_id)
        for tool in server_tools:
            name = getattr(tool, "name", None)
            if name:
                tool_server_lookup[name] = server.name if server else None

    resource_server_lookup: dict[str, str | None] = {}
    for server_id, server_resources in router_manager._mcp_server_resources_cache.items():  # noqa: SLF001
        server = server_lookup.get(server_id)
        for resource in server_resources:
            name = getattr(resource, "name", None)
            if name:
                resource_server_lookup[name] = server.name if server else None

    prompt_server_lookup: dict[str, str | None] = {}
    for server_id, server_prompts in router_manager._mcp_server_prompts_cache.items():  # noqa: SLF001
        server = server_lookup.get(server_id)
        for prompt in server_prompts:
            name = getattr(prompt, "name", None)
            if name:
                prompt_server_lookup[name] = server.name if server else None

    tool_payload = [
        {
            "name": getattr(tool, "name", None),
            "description": getattr(tool, "description", None),
            "input_schema": _pretty_json(_dump_model(getattr(tool, "inputSchema", None))),
            "server_name": tool_server_lookup.get(getattr(tool, "name", None)),
        }
        for tool in tools
    ]

    resource_payload = [
        {
            "name": getattr(resource, "name", None),
            "description": getattr(resource, "description", None),
            "uri": getattr(resource, "uri", None),
            "mime_type": getattr(resource, "mimeType", None),
            "server_name": resource_server_lookup.get(getattr(resource, "name", None)),
        }
        for resource in resources
    ]

    prompt_payload = [
        {
            "name": getattr(prompt, "name", None),
            "description": getattr(prompt, "description", None),
            "arguments": [
                _dump_model(arg) for arg in getattr(prompt, "arguments", []) or []
            ],
            "server_name": prompt_server_lookup.get(getattr(prompt, "name", None)),
        }
        for prompt in prompts
    ]

    servers_payload = []
    for server in router_manager._mcp_server_cache.values():  # noqa: SLF001
        args_dump = _dump_model(server.args)
        servers_payload.append(
            {
                "id": server.id,
                "name": server.name,
                "type": args_dump.get("type"),
                "details": (args_dump.get("command") or args_dump.get("url") or ""),
                "tool_count": len(router_manager._mcp_server_tools_cache.get(server.id, [])),  # noqa: SLF001
            }
        )

    return JSONResponse(
        {
            "servers": servers_payload,
            "tools": tool_payload,
            "resources": resource_payload,
            "prompts": prompt_payload,
        }
    )
