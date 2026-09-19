import ast
from pathlib import Path

EXCLUDED_DIRS = {
    ".git",
    ".mypy_cache",
    ".pytest_cache",
    ".ruff_cache",
    "__pycache__",
    "node_modules",
    "venv",
    ".venv",
}


def _python_files(root: Path, include_tests: bool) -> list[Path]:
    if root.is_file():
        return (
            [root]
            if root.suffix == ".py" and _include_path(root, include_tests)
            else []
        )

    return sorted(
        path for path in root.rglob("*.py") if _include_path(path, include_tests)
    )


def _include_path(path: Path, include_tests: bool) -> bool:
    parts = set(path.parts)
    if parts & EXCLUDED_DIRS:
        return False
    if include_tests:
        return True
    return not any(part == "tests" or part.startswith("test_") for part in path.parts)


def _summarize_file(path: Path, root: Path) -> dict[str, object]:
    source = path.read_text(encoding="utf-8")
    relative_path = path.relative_to(root).as_posix() if path != root else path.name
    line_count = len(source.splitlines())

    try:
        tree = ast.parse(source)
    except SyntaxError as exc:
        return {
            "path": relative_path,
            "line_count": line_count,
            "kind": "syntax_error",
            "summary": f"Could not parse: {exc.msg} at line {exc.lineno}.",
            "imports": [],
            "classes": [],
            "functions": [],
            "entrypoint": False,
        }

    docstring = ast.get_docstring(tree)
    imports = _imports(tree)
    classes = [
        _class_summary(node) for node in tree.body if isinstance(node, ast.ClassDef)
    ]
    functions = [
        _function_name(node)
        for node in tree.body
        if isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef)
    ]
    assignments = _top_level_assignments(tree)
    entrypoint = _has_main_guard(tree)

    return {
        "path": relative_path,
        "line_count": line_count,
        "kind": _file_kind(relative_path, classes, functions, entrypoint),
        "summary": _summary_sentence(
            docstring, imports, classes, functions, assignments, entrypoint
        ),
        "imports": imports,
        "classes": classes,
        "functions": functions,
        "top_level_assignments": assignments,
        "entrypoint": entrypoint,
    }


def _imports(tree: ast.Module) -> list[str]:
    names: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                names.add(alias.name.split(".")[0])
        elif isinstance(node, ast.ImportFrom):
            if node.module:
                names.add(node.module.split(".")[0])
            elif node.level:
                names.add("." * node.level)
    return sorted(names)


def _class_summary(node: ast.ClassDef) -> dict[str, object]:
    bases = [_expr_name(base) for base in node.bases]
    methods = [
        _function_name(child)
        for child in node.body
        if isinstance(child, ast.FunctionDef | ast.AsyncFunctionDef)
    ]
    return {
        "name": node.name,
        "bases": bases,
        "methods": methods,
        "docstring": _first_sentence(ast.get_docstring(node)),
    }


def _function_name(node: ast.FunctionDef | ast.AsyncFunctionDef) -> str:
    prefix = "async " if isinstance(node, ast.AsyncFunctionDef) else ""
    return f"{prefix}{node.name}"


def _top_level_assignments(tree: ast.Module) -> list[str]:
    names: set[str] = set()
    for node in tree.body:
        targets = []
        if isinstance(node, ast.Assign):
            targets = list(node.targets)
        elif isinstance(node, ast.AnnAssign):
            targets = [node.target]
        for target in targets:
            names.update(_target_names(target))
    return sorted(names)


def _target_names(target: ast.expr) -> list[str]:
    if isinstance(target, ast.Name):
        return [target.id]
    if isinstance(target, ast.Tuple | ast.List):
        names = []
        for element in target.elts:
            names.extend(_target_names(element))
        return names
    return []


def _has_main_guard(tree: ast.Module) -> bool:
    for node in tree.body:
        if not isinstance(node, ast.If):
            continue
        comparison = node.test
        if not isinstance(comparison, ast.Compare):
            continue
        left = comparison.left
        comparators = comparison.comparators
        if (
            isinstance(left, ast.Name)
            and left.id == "__name__"
            and len(comparators) == 1
            and isinstance(comparators[0], ast.Constant)
            and comparators[0].value == "__main__"
        ):
            return True
    return False


def _file_kind(
    relative_path: str,
    classes: list[dict[str, object]],
    functions: list[str],
    entrypoint: bool,
) -> str:
    path = Path(relative_path)
    if path.name.startswith("test_") or "tests" in path.parts:
        return "test"
    if entrypoint:
        return "script"
    if classes and functions:
        return "module"
    if classes:
        return "class_module"
    if functions:
        return "function_module"
    return "module"


def _summary_sentence(
    docstring: str | None,
    imports: list[str],
    classes: list[dict[str, object]],
    functions: list[str],
    assignments: list[str],
    entrypoint: bool,
) -> str:
    if docstring:
        return _first_sentence(docstring)

    pieces = []
    if classes:
        pieces.append("classes " + ", ".join(str(item["name"]) for item in classes[:4]))
    if functions:
        pieces.append("functions " + ", ".join(functions[:6]))
    if assignments:
        pieces.append("constants/settings " + ", ".join(assignments[:5]))
    if imports:
        pieces.append("uses " + ", ".join(imports[:6]))
    if entrypoint:
        pieces.append("has a __main__ entrypoint")
    return (
        "Defines " + "; ".join(pieces) + "."
        if pieces
        else "Empty or metadata-only Python module."
    )


def _first_sentence(text: str | None) -> str:
    if not text:
        return ""
    normalized = " ".join(text.strip().split())
    for delimiter in (". ", "\n"):
        if delimiter in normalized:
            return normalized.split(delimiter, 1)[0].rstrip(".") + "."
    return normalized


def _expr_name(node: ast.expr) -> str:
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute):
        value = _expr_name(node.value)
        return f"{value}.{node.attr}" if value else node.attr
    if isinstance(node, ast.Subscript):
        return _expr_name(node.value)
    return type(node).__name__
