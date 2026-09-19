import json
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
from unittest import IsolatedAsyncioTestCase

from code_harness.tools.bash import BashTool
from code_harness.tools.edit_file import EditFile
from code_harness.tools.read_file import ReadFile
from code_harness.tools.tools import run_tool
from code_harness.tools.write_file import WriteFile


def tool_call(name: str, arguments: dict) -> SimpleNamespace:
    return SimpleNamespace(
        id=f"call-{name}",
        function=SimpleNamespace(
            name=name,
            arguments=json.dumps(arguments),
        ),
    )


class WorkspaceToolTests(IsolatedAsyncioTestCase):
    async def test_file_tools_resolve_relative_paths_in_workspace(self):
        with TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)

            write_result = await run_tool(
                WriteFile(),
                tool_call("write_file", {"path": "note.txt", "content": "old"}),
                workspace_root=root,
            )
            edit_result = await run_tool(
                EditFile(),
                tool_call(
                    "edit_file",
                    {"path": "note.txt", "old_text": "old", "new_text": "new"},
                ),
                workspace_root=root,
            )
            read_result = await run_tool(
                ReadFile(),
                tool_call("read_file", {"path": "note.txt"}),
                workspace_root=root,
            )

            self.assertIsNone(write_result.error)
            self.assertIsNone(edit_result.error)
            self.assertEqual(read_result.content, "new")
            self.assertEqual((root / "note.txt").read_text(), "new")

    async def test_absolute_path_outside_workspace_is_denied(self):
        with TemporaryDirectory() as workspace, TemporaryDirectory() as outside:
            outside_path = Path(outside) / "escape.txt"

            result = await run_tool(
                WriteFile(),
                tool_call(
                    "write_file",
                    {"path": str(outside_path), "content": "denied"},
                ),
                workspace_root=Path(workspace),
            )

            self.assertIsNotNone(result.error)
            self.assertIn("outside active workspace", result.content)
            self.assertFalse(outside_path.exists())

    async def test_symlink_escape_is_denied(self):
        with TemporaryDirectory() as workspace, TemporaryDirectory() as outside:
            root = Path(workspace)
            (root / "link").symlink_to(Path(outside), target_is_directory=True)

            result = await run_tool(
                WriteFile(),
                tool_call(
                    "write_file",
                    {"path": "link/escape.txt", "content": "denied"},
                ),
                workspace_root=root,
            )

            self.assertIsNotNone(result.error)
            self.assertFalse((Path(outside) / "escape.txt").exists())

    async def test_bash_defaults_to_workspace_root(self):
        with TemporaryDirectory() as workspace:
            root = Path(workspace).resolve()

            result = await run_tool(
                BashTool(),
                tool_call("bash", {"command": "pwd"}),
                workspace_root=root,
            )

            self.assertIsNone(result.error)
            self.assertIn("Exit code: 0", result.content)
            self.assertIn(f"Stdout:\n{root}", result.content)

    async def test_bash_rejects_cwd_outside_workspace(self):
        with TemporaryDirectory() as workspace, TemporaryDirectory() as outside:
            result = await run_tool(
                BashTool(),
                tool_call("bash", {"command": "pwd", "cwd": outside}),
                workspace_root=Path(workspace),
            )

            self.assertIsNotNone(result.error)
            self.assertIn("outside active workspace", result.content)

    async def test_bash_resolves_relative_cwd_inside_workspace(self):
        with TemporaryDirectory() as workspace:
            root = Path(workspace).resolve()
            subdirectory = root / "src"
            subdirectory.mkdir()

            result = await run_tool(
                BashTool(),
                tool_call("bash", {"command": "pwd", "cwd": "src"}),
                workspace_root=root,
            )

            self.assertIsNone(result.error)
            self.assertIn("Exit code: 0", result.content)
            self.assertIn(f"Stdout:\n{subdirectory}", result.content)
