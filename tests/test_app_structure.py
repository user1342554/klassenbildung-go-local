"""Structural guards for app.py.

A refactor once dropped the call to the result view and left ~750 lines of unreachable
Streamlit code behind, including the only path that could create a manual rule. Nothing
failed, because unreachable UI code still imports and still passes its unit tests. These
tests watch the call graph instead.
"""

from __future__ import annotations

import ast
from pathlib import Path

APP_PATH = Path(__file__).resolve().parent.parent / "app.py"

# main() is the Streamlit entry point; _solver_debug_payload is called by the test suite.
ENTRY_POINTS = {"main", "_solver_debug_payload"}


def _module_functions() -> dict[str, ast.FunctionDef]:
    tree = ast.parse(APP_PATH.read_text(encoding="utf-8"))
    return {node.name: node for node in tree.body if isinstance(node, ast.FunctionDef)}


def _reachable_from(entry_points: set[str], functions: dict[str, ast.FunctionDef]) -> set[str]:
    reachable: set[str] = set()
    pending = list(entry_points)
    while pending:
        name = pending.pop()
        if name in reachable or name not in functions:
            continue
        reachable.add(name)
        pending.extend(
            node.id
            for node in ast.walk(functions[name])
            if isinstance(node, ast.Name) and node.id in functions
        )
    return reachable


def test_every_app_function_is_reachable_from_an_entry_point() -> None:
    functions = _module_functions()

    unreachable = sorted(set(functions) - _reachable_from(ENTRY_POINTS, functions))

    assert unreachable == [], (
        "These app.py functions cannot be reached from main(). Either wire them into the "
        f"UI or delete them: {unreachable}"
    )


def test_result_tab_shows_the_pedagogical_numbers_itself() -> None:
    """These belong in the result view, not buried inside 'Technische Details'."""
    functions = _module_functions()

    assert "_render_result_check" in _reachable_from({"_result_tab"}, functions)
