import unittest

from code_harness.tools.bash import BashInput, BashTool


class BashToolTests(unittest.IsolatedAsyncioTestCase):
    async def test_reports_success_exit_code_and_separate_streams(self):
        result = await BashTool().run(
            BashInput(command=("printf 'standard output'; printf 'standard error' >&2"))
        )

        self.assertIn("Exit code: 0", result)
        self.assertIn("Stdout:\nstandard output", result)
        self.assertIn("Stderr:\nstandard error", result)

    async def test_reports_nonzero_exit_code(self):
        result = await BashTool().run(BashInput(command="printf 'failed' >&2; exit 7"))

        self.assertIn("Exit code: 7", result)
        self.assertIn("Stderr:\nfailed", result)


if __name__ == "__main__":
    unittest.main()
