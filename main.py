import argparse
import asyncio
from pathlib import Path

PACKAGE_ROOT = Path(__file__).resolve().parent


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="code-harness",
        description="Run the terminal coding-agent harness.",
    )
    parser.add_argument(
        "--workspace",
        type=Path,
        default=Path.cwd(),
        help="Repository the agent may edit (default: current directory).",
    )
    parser.add_argument(
        "--settings",
        type=Path,
        default=PACKAGE_ROOT / "settings.json",
        help="Permission and MCP configuration file.",
    )
    parser.add_argument(
        "--state-dir",
        type=Path,
        default=None,
        help="Directory for runtime state (default: WORKSPACE/.code-harness).",
    )
    return parser


async def main(
    workspace: Path | None = None,
    *,
    settings_path: Path = PACKAGE_ROOT / "settings.json",
    state_root: Path | None = None,
) -> None:
    from code_harness.core.application import run_application

    workspace = (workspace or Path.cwd()).expanduser().resolve()
    await run_application(
        workspace,
        state_root=state_root or workspace / ".code-harness",
        settings_path=settings_path,
    )


def cli() -> None:
    args = build_parser().parse_args()
    asyncio.run(
        main(
            args.workspace,
            settings_path=args.settings,
            state_root=args.state_dir,
        )
    )


if __name__ == "__main__":
    cli()
