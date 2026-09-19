import unittest
from pathlib import Path
from unittest.mock import patch

from code_harness.core.config import get_model_id, get_worktree_repository_root


class ConfigTests(unittest.TestCase):
    def test_model_id_comes_from_environment(self):
        with patch.dict("os.environ", {"MODEL_ID": " test-model "}, clear=True):
            self.assertEqual(get_model_id(), "test-model")

    def test_model_id_is_required(self):
        with (
            patch.dict("os.environ", {}, clear=True),
            self.assertRaisesRegex(RuntimeError, "MODEL_ID is required"),
        ):
            get_model_id()

    def test_worktree_repository_uses_default_when_unconfigured(self):
        default = Path("relative-repository")

        with patch.dict("os.environ", {}, clear=True):
            result = get_worktree_repository_root(default)

        self.assertEqual(result, default.resolve())

    def test_worktree_repository_comes_from_environment(self):
        with patch.dict(
            "os.environ",
            {"WORKTREE_REPOSITORY_ROOT": " configured-repository "},
            clear=True,
        ):
            result = get_worktree_repository_root(Path("unused"))

        self.assertEqual(result, Path("configured-repository").resolve())


if __name__ == "__main__":
    unittest.main()
