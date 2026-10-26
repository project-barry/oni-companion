"""Calculators (v1): pure functions with form and result Screens.

Entry points: list_tools, form_screen, run_tool (see registry.py).
Numbers come from the game-data object passed in (mod-export shape), never from
constants in this package.
"""

from .common import DataProblem, ToolError, UnknownTool
from .registry import form_screen, list_tools, run_tool

__all__ = ["DataProblem", "ToolError", "UnknownTool", "form_screen", "list_tools", "run_tool"]
