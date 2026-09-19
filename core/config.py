import os
from pathlib import Path

from dotenv import load_dotenv

MODEL_ID_ENV_VAR = "MODEL_ID"

load_dotenv()


def get_model_id() -> str:
    """Return the configured model identifier or fail with a useful message."""
    model_id = os.getenv(MODEL_ID_ENV_VAR, "").strip()
    if not model_id:
        raise RuntimeError(
            f"{MODEL_ID_ENV_VAR} is required. Add it to .env, for example: "
            f"{MODEL_ID_ENV_VAR}=openrouter/provider/model-name"
        )
    return model_id


def get_worktree_repository_root(default: Path) -> Path:
    """Return the optional target repository for managed Git worktrees."""
    configured_root = os.getenv("WORKTREE_REPOSITORY_ROOT", "").strip()
    if not configured_root:
        return default.expanduser().resolve()
    return Path(configured_root).expanduser().resolve()
