import asyncio
import json
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

from code_harness.tools.llm_summarize_python_files import (
    LLMSummarizePythonFiles,
    LLMSummarizePythonFilesInput,
    _cache_key,
    _filter_files,
    _load_cache,
    _render_completion_message,
    _summarize_files,
    _summarize_one_file,
    _write_cache,
)
from code_harness.tools.summarize_python_files import _summarize_file
from code_harness.core.tracing import pop_nested_llm_calls


class FakeLLMClient:
    def __init__(self):
        self.calls = []

    async def send(self, **kwargs):
        self.calls.append(kwargs)
        content = json.dumps(
            {
                "summary": "Defines a reusable run function.",
                "responsibilities": ["Expose run behavior"],
                "key_objects": ["run"],
                "side_effects": ["none"],
            },
            sort_keys=True,
        )
        message = SimpleNamespace(content=content)
        choice = SimpleNamespace(message=message)
        return SimpleNamespace(choices=[choice])


class FailsOnceLLMClient(FakeLLMClient):
    async def send(self, **kwargs):
        self.calls.append(kwargs)
        if len(self.calls) == 1:
            raise RuntimeError("temporary model failure")
        content = json.dumps(
            {
                "summary": "Second file summarized.",
                "responsibilities": ["Summarize second file"],
                "key_objects": ["second"],
                "side_effects": ["none"],
            },
            sort_keys=True,
        )
        message = SimpleNamespace(content=content)
        choice = SimpleNamespace(message=message)
        return SimpleNamespace(choices=[choice])


class SlowLLMClient(FakeLLMClient):
    def __init__(self):
        super().__init__()
        self.active = 0
        self.max_active = 0

    async def send(self, **kwargs):
        self.calls.append(kwargs)
        self.active += 1
        self.max_active = max(self.max_active, self.active)
        await asyncio.sleep(0.01)
        self.active -= 1
        content = json.dumps(
            {
                "summary": "File summarized.",
                "responsibilities": ["Summarize file"],
                "key_objects": ["module"],
                "side_effects": ["none"],
            },
            sort_keys=True,
        )
        message = SimpleNamespace(content=content)
        choice = SimpleNamespace(message=message)
        return SimpleNamespace(choices=[choice])


class CodeCopyingLLMClient(FakeLLMClient):
    async def send(self, **kwargs):
        self.calls.append(kwargs)
        content = json.dumps(
            {
                "summary": "import os\n\ndef run():\n    return True",
                "responsibilities": ["class Runner:", "Describe behavior"],
                "key_objects": ["def run():", "run"],
                "side_effects": ["none"],
            },
            sort_keys=True,
        )
        message = SimpleNamespace(content=content)
        choice = SimpleNamespace(message=message)
        return SimpleNamespace(choices=[choice])


class LLMSummarizePythonFilesTests(unittest.IsolatedAsyncioTestCase):
    async def test_one_file_uses_structured_json_output(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            pop_nested_llm_calls()
            root = Path(tmpdir)
            path = root / "app.py"
            source = "def run():\n    return True\n"
            path.write_text(source, encoding="utf-8")
            client = FakeLLMClient()
            expected_content = json.dumps(
                {
                    "summary": "Defines a reusable run function.",
                    "responsibilities": ["Expose run behavior"],
                    "key_objects": ["run"],
                    "side_effects": ["none"],
                },
                sort_keys=True,
            )

            summary = await _summarize_one_file(
                client=client,
                model="test-model",
                path=path,
                root=root,
                source=source,
                ast_summary=_summarize_file(path, root),
                max_chars=20000,
            )

            self.assertEqual(summary["path"], "app.py")
            self.assertEqual(summary["summary"], "Defines a reusable run function.")
            self.assertEqual(client.calls[0]["response_format"], {"type": "json_object"})
            events = pop_nested_llm_calls()
            self.assertEqual(events[-1]["file_path"], "app.py")
            self.assertEqual(events[-1]["status"], "ok")
            self.assertEqual(events[-1]["response_content"], expected_content)

    async def test_code_like_llm_output_is_not_rendered_as_summary(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            path = root / "app.py"
            source = "def run():\n    return True\n"
            path.write_text(source, encoding="utf-8")

            summary = await _summarize_one_file(
                client=CodeCopyingLLMClient(),
                model="test-model",
                path=path,
                root=root,
                source=source,
                ast_summary=_summarize_file(path, root),
                max_chars=20000,
            )

            self.assertEqual(summary["summary"], "Defines functions run.")
            self.assertEqual(summary["responsibilities"], ["Describe behavior"])
            self.assertEqual(summary["key_objects"], ["run"])

    async def test_cache_key_and_cache_file_are_stable(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            path = root / "app.py"
            source = "def run():\n    return True\n"
            path.write_text(source, encoding="utf-8")
            cache_path = root / ".summary-cache.json"
            arguments = LLMSummarizePythonFilesInput(
                root_path=str(root),
                cache_path=str(cache_path),
                model="test-model",
            )
            cached_summary = {"path": "app.py", "summary": "Cached summary"}

            first_key = _cache_key(arguments, path, source)
            second_key = _cache_key(arguments, path, source)
            _write_cache(str(cache_path), {first_key: cached_summary})

            self.assertEqual(first_key, second_key)
            self.assertEqual(_load_cache(str(cache_path)), {first_key: cached_summary})
            self.assertEqual(LLMSummarizePythonFiles.input_model, LLMSummarizePythonFilesInput)

    async def test_summarize_files_continues_after_file_error(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            (root / "a.py").write_text("def first():\n    return True\n", encoding="utf-8")
            (root / "b.py").write_text("def second():\n    return True\n", encoding="utf-8")
            arguments = LLMSummarizePythonFilesInput(
                root_path=str(root),
                model="test-model",
                print_progress=False,
            )

            summaries = await _summarize_files(FailsOnceLLMClient(), arguments)

            self.assertEqual([item["path"] for item in summaries], ["a.py", "b.py"])
            self.assertEqual([item["file_index"] for item in summaries], [1, 2])
            self.assertEqual([item["file_count"] for item in summaries], [2, 2])
            self.assertEqual(summaries[0]["status"], "error")
            self.assertEqual(summaries[1]["status"], "ok")

    async def test_summarize_files_respects_max_concurrency_and_keeps_order(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            pop_nested_llm_calls()
            root = Path(tmpdir)
            for name in ["e.py", "d.py", "c.py", "b.py", "a.py"]:
                (root / name).write_text(f"def {name[0]}():\n    return True\n", encoding="utf-8")
            client = SlowLLMClient()
            arguments = LLMSummarizePythonFilesInput(
                root_path=str(root),
                model="test-model",
                max_concurrency=2,
                print_progress=False,
            )

            summaries = await _summarize_files(client, arguments)

            self.assertLessEqual(client.max_active, 2)
            self.assertEqual(len(client.calls), 5)
            self.assertEqual([item["path"] for item in summaries], ["a.py", "b.py", "c.py", "d.py", "e.py"])
            self.assertEqual([item["file_index"] for item in summaries], [1, 2, 3, 4, 5])
            self.assertEqual(
                sorted(event["file_path"] for event in pop_nested_llm_calls()),
                ["a.py", "b.py", "c.py", "d.py", "e.py"],
            )

    async def test_summarize_files_skips_tests_by_default(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            (root / "app.py").write_text("def run():\n    return True\n", encoding="utf-8")
            tests_dir = root / "tests"
            tests_dir.mkdir()
            (tests_dir / "test_app.py").write_text("def test_run():\n    assert True\n", encoding="utf-8")
            arguments = LLMSummarizePythonFilesInput(
                root_path=str(root),
                model="test-model",
                print_progress=False,
            )

            summaries = await _summarize_files(FakeLLMClient(), arguments)

            self.assertEqual([item["path"] for item in summaries], ["app.py"])

    async def test_filter_files_supports_include_and_exclude_globs(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            paths = []
            for relative_path in ["core/app.py", "core/test_app.py", "tools/bash.py", "main.py"]:
                path = root / relative_path
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text("VALUE = 1\n", encoding="utf-8")
                paths.append(path)

            selected = _filter_files(
                paths,
                root=root,
                include_globs=["core/**", "tools/**"],
                exclude_globs=["**/test_*.py"],
            )

            self.assertEqual(
                [path.relative_to(root).as_posix() for path in selected],
                ["core/app.py", "tools/bash.py"],
            )

    async def test_completion_message_tells_agent_not_to_rerun(self):
        summaries = [
            {"status": "ok"},
            {"status": "error"},
        ]

        message = _render_completion_message(summaries, Path("summary.md"))

        self.assertIn("Summary complete.", message)
        self.assertIn("Do not call this tool again", message)


if __name__ == "__main__":
    unittest.main()
