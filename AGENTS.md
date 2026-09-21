# Repository Guidelines

## Project Structure & Module Organization

This repository implements a Python terminal-based coding-agent harness. `main.py` is the interactive entry point. Core orchestration lives in `core/` (`loop.py`, permissions, tracing, agent runtime), while conversation storage and context compaction live in `memory/`. Agent-callable capabilities belong in `tools/`; scheduled execution is implemented in `cron_scheduler/`, and teammate messaging is under `team/`.

Place automated tests in `tests/` using the existing `test_*.py` pattern. `test_workspace/` contains sample files used for agent exercises. Skills are Markdown instruction packages under `skills/<skill-name>/SKILL.md`. Runtime artifacts under `.code-harness/` are generated state, not source modules.

## Build, Test, and Development Commands

Run commands from the repository directory:

```bash
python -m venv .venv
source .venv/bin/activate
python -m pip install -e ".[dev]"
code-harness --workspace .
python -m pytest
python -m pytest tests/test_agent.py -q
```

There is no compilation step. The first three commands create the environment and install dependencies; `code-harness` launches the interactive agent; `pytest` runs the full or targeted test suite.

## Coding Style & Naming Conventions

Use Python 3.12-compatible code, four-space indentation, type hints for public interfaces, and short docstrings where behavior is not obvious. Follow standard Python naming: `snake_case` for functions and modules, `PascalCase` for classes, and `UPPER_CASE` for constants. Tool implementations should subclass `BaseTool`, define a Pydantic input model, and expose a stable lowercase tool name. Ruff formatting and lint checks are enforced by pre-commit and CI.

## Testing Guidelines

Tests use `pytest`, although some suites use `unittest.TestCase` assertions. Name files `test_<feature>.py` and test methods `test_<behavior>`. Add focused coverage for permission decisions, tool validation, persistence, and async/background behavior when modifying those areas. Avoid live LLM calls; mock external responses and use temporary directories for generated state.

## Commit & Pull Request Guidelines

The repository currently has no commit history establishing a convention. Use concise, imperative subjects such as `Add task dependency validation`. Keep commits scoped to one logical change. Pull requests should explain the motivation, summarize implementation choices, list test commands and results, and call out configuration or permission changes. Include screenshots only for changes to `trace_viewer.html` or other visible output.

## Security & Configuration

Keep API keys in `.env` and never commit them. Treat edits to `settings.json` as security-sensitive. Preserve project-root path checks and do not weaken deny rules without documenting the risk.
