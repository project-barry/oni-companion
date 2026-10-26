"""Tool registry and the two entry points the API uses.

  list_tools()                         -> ToolList            (GET /tools)
  form_screen(tool_id, data)           -> Screen with a form  (GET /tools/<id>)
  run_tool(tool_id, values, data)      -> Screen with result  (POST /tools/<id>)

Errors: UnknownTool (404), ToolError (400, message names the field). A tool whose
game data is missing gets a Screen with a notice instead (DataProblem); no number
is invented.
"""

from . import common as c
from . import critter_ranch, element_state, geyser, heat, o2, power

TOOLS = [heat.TOOL, element_state.TOOL, geyser.TOOL, o2.TOOL, critter_ranch.TOOL, power.TOOL]
_BY_ID = {t.id: t for t in TOOLS}


def _tool(tool_id):
    if tool_id not in _BY_ID:
        raise c.UnknownTool(tool_id)
    return _BY_ID[tool_id]


def list_tools():
    return {"tools": [{"id": t.id, "title": t.title, "summary": t.summary} for t in TOOLS]}


def _notice_screen(tool, message, source, as_of):
    return {
        "schema": 1, "title": tool.title, "subtitle": tool.summary,
        "source": source, "asOf": as_of or c.now_utc(),
        "nav": {"back": "home"},
        "blocks": [c.notice("warn", message)],
    }


def form_screen(tool_id, data, source="mod-export", as_of=None):
    """The start Screen of a tool: the form with defaults filled in."""
    tool = _tool(tool_id)
    try:
        fields = tool.fields(data)
    except c.DataProblem as e:
        return _notice_screen(tool, str(e), source, as_of)
    return {
        "schema": 1, "title": tool.title, "subtitle": tool.summary,
        "nav": {"back": "home"},
        "blocks": [c.form_block(tool.id, fields, tool.submit_label)],
    }


def run_tool(tool_id, values, data, source="mod-export", as_of=None):
    """Submit a form. Returns the form pre-filled with the values, then the result blocks."""
    tool = _tool(tool_id)
    try:
        fields = tool.fields(data)
    except c.DataProblem as e:
        return _notice_screen(tool, str(e), source, as_of)
    parsed = c.parse_values(fields, values, data)
    try:
        result = tool.run(parsed, data)
    except c.DataProblem as e:
        result = [c.notice("warn", str(e))]
    form = c.form_block(tool.id, c.prefilled_fields(fields, parsed), tool.submit_label)
    return {
        "schema": 1, "title": tool.title, "subtitle": tool.summary,
        "source": source, "asOf": as_of or c.now_utc(),
        "nav": {"back": "home"},
        "blocks": [form] + result,
    }
