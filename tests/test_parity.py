"""The sync and async halves are written by hand, so this keeps them identical.

All request building, parsing, auth and retry logic is shared (``_endpoints``,
``_plans``, ``_session``). What is written twice is the thin public surface,
and each pair below must match once ``async``/``await`` and the ``Async`` /
``Sync`` name prefixes are removed: same methods, same signatures, same
docstrings, same bodies.
"""

from __future__ import annotations

import ast
import difflib
from pathlib import Path

import pytest

SRC = Path(__file__).resolve().parent.parent / "src" / "beli"

PAIRS = [("_resources.py", "_async_resources.py"), ("_client.py", "_async_client.py")]

DUNDERS = {"__aenter__": "__enter__", "__aexit__": "__exit__"}


def _name(name: str) -> str:
    return DUNDERS.get(name, name).removeprefix("Async").removeprefix("Sync")


def _text(text: str) -> str:
    return text.replace("AsyncBeli", "Beli").replace("async with", "with").replace("await ", "")


class _Normalize(ast.NodeTransformer):
    def visit_Await(self, node: ast.Await) -> ast.AST:
        return self.visit(node.value)

    def visit_AsyncFunctionDef(self, node: ast.AsyncFunctionDef) -> ast.AST:
        fields = {name: getattr(node, name) for name in node._fields}
        return self.visit(ast.copy_location(ast.FunctionDef(**fields), node))

    def visit_FunctionDef(self, node: ast.FunctionDef) -> ast.AST:
        node.name = _name(node.name)
        # ``Beli.user_id`` is a property; ``AsyncBeli.user_id`` has to be awaited.
        if node.name == "user_id":
            node.decorator_list = []
        return self.generic_visit(node)

    def visit_ClassDef(self, node: ast.ClassDef) -> ast.AST:
        node.name = _name(node.name)
        return self.generic_visit(node)

    def visit_alias(self, node: ast.alias) -> ast.AST:
        node.name = _name(node.name)
        return node

    def visit_Name(self, node: ast.Name) -> ast.AST:
        node.id = _name(node.id)
        return node

    def visit_Attribute(self, node: ast.Attribute) -> ast.AST:
        node.attr = _name(node.attr)
        return self.generic_visit(node)

    def visit_Constant(self, node: ast.Constant) -> ast.AST:
        if isinstance(node.value, str):
            node.value = _text(node.value)
        return node


def normalized(path: Path) -> list[str]:
    tree = ast.parse(path.read_text())
    if ast.get_docstring(tree) is not None:
        tree.body = tree.body[1:]
    imports: set[str] = set()
    body: list[ast.stmt] = []
    for stmt in tree.body:
        # Import order depends on the module names, so compare imports as a set.
        if isinstance(stmt, ast.ImportFrom):
            module = (stmt.module or "").replace("_async_", "_")
            imports.update(f"from {module} import {_name(a.name)}" for a in stmt.names)
        elif isinstance(stmt, ast.Import):
            imports.update(f"import {a.name}" for a in stmt.names)
        else:
            body.append(stmt)
    tree.body = body
    code = ast.unparse(ast.fix_missing_locations(_Normalize().visit(tree)))
    return [*sorted(imports), *code.splitlines()]


@pytest.mark.parametrize(("sync_file", "async_file"), PAIRS)
def test_sync_and_async_match(sync_file: str, async_file: str) -> None:
    diff = list(
        difflib.unified_diff(
            normalized(SRC / sync_file),
            normalized(SRC / async_file),
            sync_file,
            async_file,
            lineterm="",
            n=2,
        )
    )
    assert not diff, "sync and async have drifted:\n" + "\n".join(diff)


def test_normalizer_notices_drift(tmp_path: Path) -> None:
    source = (SRC / "_async_resources.py").read_text()
    for old, new in [
        ('category: str = "RES"', 'category: str = "BAR"'),
        ("ep.photos(user)", "ep.photos(None)"),
        ("Your Want to Try list.", "Bookmarks."),
    ]:
        assert old in source
        changed = tmp_path / "changed.py"
        changed.write_text(source.replace(old, new, 1))
        assert normalized(changed) != normalized(SRC / "_resources.py")
