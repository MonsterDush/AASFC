from __future__ import annotations

import ast
import json
from pathlib import Path


REPO_DIR = Path(__file__).resolve().parents[1]
BACKEND_APP_DIR = REPO_DIR / "backend" / "app"
REGEX_CALLS = {
    "re.compile",
    "re.findall",
    "re.finditer",
    "re.fullmatch",
    "re.match",
    "re.search",
    "re.split",
    "re.sub",
    "re.subn",
}


def dotted_name(node: ast.AST) -> str:
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute):
        prefix = dotted_name(node.value)
        return f"{prefix}.{node.attr}" if prefix else node.attr
    return ""


def is_regex_pattern(node: ast.Constant, parent: ast.AST | None) -> bool:
    return (
        isinstance(parent, ast.Call)
        and bool(parent.args)
        and parent.args[0] is node
        and dotted_name(parent.func) in REGEX_CALLS
    )


def docstring_nodes(tree: ast.AST) -> set[int]:
    result: set[int] = set()
    for node in ast.walk(tree):
        if not isinstance(node, (ast.Module, ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        if not node.body or not isinstance(node.body[0], ast.Expr):
            continue
        value = node.body[0].value
        if isinstance(value, ast.Constant) and isinstance(value.value, str):
            result.add(id(value))
    return result


def collect_file(file_path: Path) -> list[tuple[str, str]]:
    tree = ast.parse(file_path.read_text(encoding="utf-8"), filename=str(file_path))
    parent_by_id = {id(child): node for node in ast.walk(tree) for child in ast.iter_child_nodes(node)}
    ignored_docstrings = docstring_nodes(tree)
    relative = str(file_path.relative_to(REPO_DIR))
    result: list[tuple[str, str]] = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Constant) or not isinstance(node.value, str):
            continue
        parent = parent_by_id.get(id(node))
        if id(node) in ignored_docstrings or isinstance(parent, ast.JoinedStr) or is_regex_pattern(node, parent):
            continue
        result.append((node.value, relative))
    for node in ast.walk(tree):
        if not isinstance(node, ast.JoinedStr):
            continue
        for value in node.values:
            if isinstance(value, ast.Constant) and isinstance(value.value, str):
                result.append((value.value, relative))
    return result


def main() -> None:
    sources: list[tuple[str, str]] = []
    for file_path in sorted(BACKEND_APP_DIR.rglob("*.py")):
        sources.extend(collect_file(file_path))
    print(json.dumps(sources, ensure_ascii=False))


if __name__ == "__main__":
    main()
