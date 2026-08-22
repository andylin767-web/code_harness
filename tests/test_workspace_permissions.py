from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import TestCase

import json

from code_harness.core.permissions import (
    PermissionDecision,
    PermissionEngine,
    Rule,
)


class WorkspacePermissionTests(TestCase):
    def test_relative_paths_resolve_against_active_workspace(self):
        with TemporaryDirectory() as workspace:
            root = Path(workspace).resolve()
            engine = PermissionEngine(workspace_root=root)

            self.assertEqual(
                engine.resolve_in_workspace("src/app.py"),
                root / "src/app.py",
            )

    def test_paths_outside_active_workspace_are_rejected(self):
        with TemporaryDirectory() as workspace, TemporaryDirectory() as outside:
            engine = PermissionEngine(workspace_root=Path(workspace))

            with self.assertRaises(PermissionError):
                engine.resolve_in_project(Path(outside) / "file.py")
            self.assertTrue(
                engine.command_references_outside_project(
                    f"cat {Path(outside) / 'file.py'}"
                )
            )

    def test_workspace_can_be_switched(self):
        with TemporaryDirectory() as first, TemporaryDirectory() as second:
            engine = PermissionEngine(workspace_root=Path(first))

            engine.set_workspace_root(Path(second))

            self.assertEqual(engine.workspace_root, Path(second).resolve())
            self.assertEqual(
                engine.resolve_in_workspace("file.py"),
                Path(second).resolve() / "file.py",
            )

    def test_permission_path_rules_are_relative_to_active_workspace(self):
        with TemporaryDirectory() as workspace:
            root = Path(workspace).resolve()
            engine = PermissionEngine(workspace_root=root)
            engine.allow(Rule("edit_file", "/*.py"))

            decision = engine.decide(
                Rule(
                    "edit_file",
                    json.dumps({"path": str(root / "app.py")}),
                )
            )

            self.assertEqual(decision, PermissionDecision.ALLOW)
