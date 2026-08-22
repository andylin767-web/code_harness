import asyncio
import fnmatch
import hashlib
import json
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, Field

from code_harness.models import ROUTER_MODEL
from code_harness.tools.summarize_python_files import (
    _python_files,
    _summarize_file,
)
from code_harness.tools.tools import BaseTool


PROMPT_VERSION = "python-file-summary-v2"


class LLMSummarizePythonFilesInput(BaseModel):
    root_path: str = "."
    output_path: str | None = None
    cache_path: str | None = None
    model: str = ROUTER_MODEL
    format: Literal["markdown", "json"] = "markdown"
    include_tests: bool = False
    max_chars_per_file: int = 20000
    fail_fast: bool = False
    max_concurrency: int = Field(default=4, ge=1, le=16)
    print_progress: bool = True
    include_globs: list[str] = Field(default_factory=list)
    exclude_globs: list[str] = Field(default_factory=list)


class LLMSummarizePythonFiles(BaseTool):
    name = "llm_summarize_python_files"
    description = (
        "Summarize Python files with an LLM using bounded concurrency, progress "
        "printing, structured JSON output, per-file errors, and optional content-hash cache."
    )
    input_model = LLMSummarizePythonFilesInput
    project_path_fields = {"root_path", "output_path", "cache_path"}
    concurrent_safe = False
    terminal_after_run = True

    async def run(self, arguments: LLMSummarizePythonFilesInput) -> str:
        from code_harness.core.llm_client import LLMClient, RetryConfig

        client = LLMClient(RetryConfig(jitter_seconds=0))
        summaries = await _summarize_files(client, arguments)

        root = Path(arguments.root_path)
        rendered = _render_json(summaries) if arguments.format == "json" else _render_markdown(summaries, root)

        if arguments.output_path:
            output_path = Path(arguments.output_path)
            output_path.parent.mkdir(parents=True, exist_ok=True)
            output_path.write_text(rendered + "\n", encoding="utf-8")
            completed = sum(1 for item in summaries if item.get("status") == "ok")
            failed = sum(1 for item in summaries if item.get("status") == "error")
            if arguments.print_progress:
                print(f"summary complete: {len(summaries)} files ({completed} ok, {failed} error)")
            return _render_completion_message(summaries, output_path)

        if arguments.print_progress:
            completed = sum(1 for item in summaries if item.get("status") == "ok")
            failed = sum(1 for item in summaries if item.get("status") == "error")
            print(f"summary complete: {len(summaries)} files ({completed} ok, {failed} error)")
        return rendered


def _render_completion_message(summaries: list[dict[str, object]], output_path: Path) -> str:
    completed = sum(1 for item in summaries if item.get("status") == "ok")
    failed = sum(1 for item in summaries if item.get("status") == "error")
    return (
        f"Summary complete. Wrote LLM summaries for {len(summaries)} Python files "
        f"to {output_path} ({completed} ok, {failed} error). Do not call this tool again "
        "for the same repo unless the user asks to rerun it."
    )


async def _summarize_files(
    client: Any,
    arguments: LLMSummarizePythonFilesInput,
) -> list[dict[str, object]]:
    from code_harness.core.tracing import init_nested_llm_calls

    root = Path(arguments.root_path)
    files = _filter_files(
        _python_files(root, include_tests=arguments.include_tests),
        root=root,
        include_globs=arguments.include_globs,
        exclude_globs=arguments.exclude_globs,
    )
    cache = _load_cache(arguments.cache_path)
    cache_lock = asyncio.Lock()
    semaphore = asyncio.Semaphore(arguments.max_concurrency)
    file_count = len(files)
    summaries: list[dict[str, object] | None] = [None] * file_count
    init_nested_llm_calls()
    if arguments.print_progress:
        print(f"selected {file_count} Python files from {root}", flush=True)

    async def summarize_path(index: int, path: Path) -> dict[str, object]:
        relative_path = path.relative_to(root).as_posix() if path != root else path.name
        source = path.read_text(encoding="utf-8")
        ast_summary = _summarize_file(path, root)
        cache_key = _cache_key(arguments, path, source)
        cached = cache.get(cache_key)
        if cached is not None:
            if arguments.print_progress:
                print(f"[{index}/{file_count}] cached {relative_path}", flush=True)
            return _with_run_metadata(cached, index, file_count, cache_hit=True)

        try:
            async with semaphore:
                if arguments.print_progress:
                    print(f"[{index}/{file_count}] summarizing {relative_path}", flush=True)
                summary = await _summarize_one_file(
                    client=client,
                    model=arguments.model,
                    path=path,
                    root=root,
                    source=source,
                    ast_summary=ast_summary,
                    max_chars=arguments.max_chars_per_file,
                )
        except Exception as exc:
            if arguments.fail_fast:
                raise
            if arguments.print_progress:
                print(f"[{index}/{file_count}] error {relative_path}: {exc}", flush=True)
            return _error_summary(relative_path, ast_summary, arguments.model, index, file_count, exc)

        async with cache_lock:
            cache[cache_key] = summary
            _write_cache(arguments.cache_path, cache)
        if arguments.print_progress:
            print(f"[{index}/{file_count}] done {relative_path}", flush=True)
        return _with_run_metadata(summary, index, file_count, cache_hit=False)

    tasks = [
        asyncio.create_task(summarize_path(index, path))
        for index, path in enumerate(files, start=1)
    ]
    if arguments.fail_fast:
        return await asyncio.gather(*tasks)

    for index, task in enumerate(tasks):
        summaries[index] = await task

    _write_cache(arguments.cache_path, cache)
    return [summary for summary in summaries if summary is not None]


def _filter_files(
    files: list[Path],
    root: Path,
    include_globs: list[str],
    exclude_globs: list[str],
) -> list[Path]:
    selected = []
    for path in files:
        relative_path = path.relative_to(root).as_posix() if path != root else path.name
        if include_globs and not any(fnmatch.fnmatch(relative_path, pattern) for pattern in include_globs):
            continue
        if exclude_globs and any(fnmatch.fnmatch(relative_path, pattern) for pattern in exclude_globs):
            continue
        selected.append(path)
    return selected


def _with_run_metadata(
    summary: dict[str, object],
    file_index: int,
    file_count: int,
    cache_hit: bool,
) -> dict[str, object]:
    enriched = dict(summary)
    enriched["status"] = enriched.get("status", "ok")
    enriched["file_index"] = file_index
    enriched["file_count"] = file_count
    enriched["cache_hit"] = cache_hit
    return enriched


def _error_summary(
    relative_path: str,
    ast_summary: dict[str, object],
    model: str,
    file_index: int,
    file_count: int,
    exc: Exception,
) -> dict[str, object]:
    return {
        "path": relative_path,
        "line_count": ast_summary.get("line_count", 0),
        "kind": ast_summary.get("kind", "module"),
        "summary": "LLM summary failed for this file.",
        "responsibilities": [],
        "key_objects": [],
        "side_effects": [],
        "imports": ast_summary.get("imports", []),
        "functions": ast_summary.get("functions", []),
        "classes": ast_summary.get("classes", []),
        "prompt_version": PROMPT_VERSION,
        "model": model,
        "status": "error",
        "error": f"{type(exc).__name__}: {exc}",
        "file_index": file_index,
        "file_count": file_count,
        "cache_hit": False,
    }


async def _summarize_one_file(
    client: Any,
    model: str,
    path: Path,
    root: Path,
    source: str,
    ast_summary: dict[str, object],
    max_chars: int,
) -> dict[str, object]:
    from code_harness.core.tracing import record_nested_llm_call, utc_now_iso

    relative_path = path.relative_to(root).as_posix() if path != root else path.name
    messages = _messages(relative_path, source, ast_summary, max_chars)
    options: dict[str, Any] = {
        "response_format": {"type": "json_object"},
    }

    started_at = utc_now_iso()
    try:
        response = await client.send(
            model=model,
            messages=messages,
            tools=[],
            **options,
        )
    except Exception as exc:
        record_nested_llm_call(
            {
                "type": "llm_summarize_python_file",
                "file_path": relative_path,
                "model": model,
                "started_at": started_at,
                "ended_at": utc_now_iso(),
                "status": "error",
                "messages": messages,
                "options": options,
                "error": f"{type(exc).__name__}: {exc}",
            }
        )
        raise

    ended_at = utc_now_iso()
    message = response.choices[0].message
    response_message = message.model_dump() if hasattr(message, "model_dump") else vars(message)
    content = message.content or "{}"
    record_nested_llm_call(
        {
            "type": "llm_summarize_python_file",
            "file_path": relative_path,
            "model": model,
            "started_at": started_at,
            "ended_at": ended_at,
            "status": "ok",
            "messages": messages,
            "options": options,
            "response_message": response_message,
            "response_content": content,
        }
    )
    payload = _parse_json_object(content)

    return {
        "path": relative_path,
        "line_count": ast_summary["line_count"],
        "kind": ast_summary["kind"],
        "summary": _safe_summary(payload.get("summary"), ast_summary),
        "responsibilities": _safe_string_list(payload.get("responsibilities")),
        "key_objects": _safe_string_list(payload.get("key_objects")),
        "side_effects": _safe_string_list(payload.get("side_effects")),
        "imports": ast_summary.get("imports", []),
        "functions": ast_summary.get("functions", []),
        "classes": ast_summary.get("classes", []),
        "prompt_version": PROMPT_VERSION,
        "model": model,
    }


def _messages(
    relative_path: str,
    source: str,
    ast_summary: dict[str, object],
    max_chars: int,
) -> list[dict[str, str]]:
    clipped_source = source[:max_chars]
    truncation_note = ""
    if len(source) > max_chars:
        truncation_note = f"\n\n[Source clipped from {len(source)} to {max_chars} characters.]"

    return [
        {
            "role": "system",
            "content": (
                "You summarize Python source files for codebase documentation. "
                "Return only valid JSON. Be concise and factual. Do not infer behavior "
                "that is not supported by the file. Never copy source code, imports, "
                "function bodies, class definitions, or code blocks into the response."
            ),
        },
        {
            "role": "user",
            "content": (
                f"Prompt version: {PROMPT_VERSION}\n"
                f"File path: {relative_path}\n"
                f"AST metadata JSON:\n{json.dumps(ast_summary, sort_keys=True)}\n\n"
                "Return this exact JSON shape:\n"
                "{\n"
                '  "summary": "one sentence purpose of the file",\n'
                '  "responsibilities": ["2-5 concrete responsibilities"],\n'
                '  "key_objects": ["important classes/functions/constants"],\n'
                '  "side_effects": ["I/O, network, process, environment, persistence, or none"]\n'
                "}\n\n"
                "Use the following Python source only as reference material. Summarize it in prose; "
                "do not quote or reproduce code from it.\n"
                f"<python_source_reference>\n{clipped_source}\n</python_source_reference>"
                f"{truncation_note}"
            ),
        },
    ]


def _cache_key(arguments: LLMSummarizePythonFilesInput, path: Path, source: str) -> str:
    payload = {
        "format": "summary-json",
        "max_chars_per_file": arguments.max_chars_per_file,
        "model": arguments.model,
        "path": path.as_posix(),
        "prompt_version": PROMPT_VERSION,
        "source_sha256": hashlib.sha256(source.encode("utf-8")).hexdigest(),
    }
    encoded = json.dumps(payload, sort_keys=True).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _load_cache(cache_path: str | None) -> dict[str, dict[str, object]]:
    if not cache_path:
        return {}
    path = Path(cache_path)
    if not path.exists():
        return {}
    data = json.loads(path.read_text(encoding="utf-8"))
    return data if isinstance(data, dict) else {}


def _write_cache(cache_path: str | None, cache: dict[str, dict[str, object]]) -> None:
    if not cache_path:
        return
    path = Path(cache_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(cache, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def _parse_json_object(content: str) -> dict[str, object]:
    try:
        parsed = json.loads(content)
    except json.JSONDecodeError:
        start = content.find("{")
        end = content.rfind("}")
        if start == -1 or end == -1 or end < start:
            return {}
        parsed = json.loads(content[start : end + 1])
    return parsed if isinstance(parsed, dict) else {}


def _string_list(value: object) -> list[str]:
    if value is None:
        return []
    if isinstance(value, str):
        return [value.strip()] if value.strip() else []
    if isinstance(value, list):
        return [str(item).strip() for item in value if str(item).strip()]
    return [str(value).strip()] if str(value).strip() else []


def _safe_summary(value: object, ast_summary: dict[str, object]) -> str:
    text = _clean_text(str(value or ""))
    if not text or _looks_like_code(text):
        return str(ast_summary.get("summary") or "Python module summary unavailable.")
    return text


def _safe_string_list(value: object) -> list[str]:
    return [item for item in (_clean_text(text) for text in _string_list(value)) if item and not _looks_like_code(item)]


def _clean_text(text: str) -> str:
    cleaned = text.replace("```python", "").replace("```", "")
    cleaned = " ".join(cleaned.split())
    return cleaned.strip()


def _looks_like_code(text: str) -> bool:
    stripped = text.strip()
    if not stripped:
        return False

    code_markers = (
        "import ",
        "from ",
        "def ",
        "async def ",
        "class ",
        "return ",
        "self.",
        "BaseModel",
    )
    if stripped.startswith(code_markers):
        return True
    if "\\n" in stripped and any(marker in stripped for marker in code_markers):
        return True
    if stripped.count(";") >= 2 or stripped.count("{") >= 2:
        return True
    return False


def _render_json(summaries: list[dict[str, object]]) -> str:
    return json.dumps(summaries, indent=2, sort_keys=True)


def _render_markdown(summaries: list[dict[str, object]], root: Path) -> str:
    completed = sum(1 for item in summaries if item.get("status") == "ok")
    failed = sum(1 for item in summaries if item.get("status") == "error")
    cache_hits = sum(1 for item in summaries if item.get("cache_hit") is True)
    lines = [
        f"# LLM Python File Summary: {root.as_posix()}",
        "",
        f"Total Python files: {len(summaries)}",
        f"Completed: {completed}",
        f"Failed: {failed}",
        f"Cache hits: {cache_hits}",
        f"Prompt version: `{PROMPT_VERSION}`",
        "",
        "| # | File | Status | Kind | Lines | Summary |",
        "|---:|---|---|---:|---:|---|",
    ]
    for item in summaries:
        lines.append(
            "| {file_index} | {path} | {status} | {kind} | {line_count} | {summary} |".format(
                file_index=item.get("file_index", ""),
                path=_escape_markdown(str(item["path"])),
                status=item.get("status", "ok"),
                kind=item["kind"],
                line_count=item["line_count"],
                summary=_escape_markdown(str(item["summary"])),
            )
        )

    lines.extend(["", "## Details", ""])
    for item in summaries:
        lines.append(f"### `{item['path']}`")
        lines.append(f"- Kind: `{item['kind']}`")
        lines.append(f"- Status: `{item.get('status', 'ok')}`")
        lines.append(f"- File index: {item.get('file_index', '?')} of {item.get('file_count', '?')}")
        lines.append(f"- Cache hit: {item.get('cache_hit', False)}")
        lines.append(f"- Lines: {item['line_count']}")
        lines.append(f"- Summary: {item['summary']}")
        if item.get("error"):
            lines.append(f"- Error: `{item['error']}`")
        lines.append(f"- Responsibilities: {_comma_list(item['responsibilities'])}")
        lines.append(f"- Key objects: {_comma_list(item['key_objects'])}")
        lines.append(f"- Side effects: {_comma_list(item['side_effects'])}")
        lines.append(f"- Model: `{item['model']}`")
        lines.append("")
    return "\n".join(lines).rstrip()


def _escape_markdown(text: str) -> str:
    return text.replace("|", "\\|").replace("\n", " ")


def _comma_list(values: object) -> str:
    if not values:
        return "none"
    return ", ".join(f"`{value}`" for value in values)
