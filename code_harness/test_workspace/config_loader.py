"""
config_loader.py - Reusable Configuration Loader

Supports YAML and JSON config files, merges multiple config sources
with priority ordering, and allows environment variable overrides.

Usage:
    from config_loader import ConfigLoader

    config = ConfigLoader()
    config.add_file("base.yaml")
    config.add_file("override.json")
    config.enable_env_overrides(prefix="APP_")
    settings = config.load()
"""

import json
import os
import re
from pathlib import Path
from typing import Any


class ConfigError(Exception):
    """Base exception for configuration loading errors."""


class ConfigFileNotFoundError(ConfigError):
    """Raised when a config file does not exist."""


class ConfigParseError(ConfigError):
    """Raised when a config file cannot be parsed."""


class ConfigMergeError(ConfigError):
    """Raised when config merging fails."""


def _deep_merge(base: dict, override: dict) -> dict:
    """
    Recursively merge two dictionaries.

    Values in *override* take priority over *base*.
    Nested dicts are merged recursively; all other values are replaced.
    """
    if not isinstance(base, dict) or not isinstance(override, dict):
        raise ConfigMergeError(
            f"Cannot merge non-dict types: {type(base).__name__} and {type(override).__name__}"
        )

    merged = base.copy()
    for key, value in override.items():
        if key in merged and isinstance(merged[key], dict) and isinstance(value, dict):
            merged[key] = _deep_merge(merged[key], value)
        else:
            merged[key] = value
    return merged


def _parse_yaml_simple(text: str) -> dict:
    """
    Minimal YAML parser sufficient for flat/nested key-value configs.

    Supports:
      - Nested keys via indentation (2-space)
      - Quoted and unquoted string values
      - Integer, float, boolean, and null literals
      - Comments (#)

    For production use, consider installing PyYAML or ruamel.yaml.
    """
    root: dict = {}
    stack: list[tuple[int, dict]] = [(0, root)]

    for raw_line in text.splitlines():
        # Skip blank lines and comments
        stripped = raw_line.rstrip()
        if not stripped or stripped.lstrip().startswith("#"):
            continue

        indent = len(raw_line) - len(raw_line.lstrip())
        line = stripped.lstrip()

        # Pop stack back to parent of current indent level
        while len(stack) > 1 and indent <= stack[-1][0]:
            stack.pop()

        if ":" not in line:
            raise ConfigParseError(f"Invalid YAML line (no colon): {line!r}")

        key, _, value = line.partition(":")
        key = key.strip().strip("'\"")
        value = value.strip()

        parent = stack[-1][1]

        if value == "" or value == "|":
            # Nested mapping (child lines will follow)
            new_dict: dict = {}
            parent[key] = new_dict
            stack.append((indent, new_dict))
        else:
            parent[key] = _cast_value(value)

    return root


def _cast_value(value: str) -> Any:
    """Cast a YAML/JSON string value to its Python equivalent."""
    # Remove surrounding quotes
    if (value.startswith('"') and value.endswith('"')) or (
        value.startswith("'") and value.endswith("'")
    ):
        return value[1:-1]

    # Booleans
    if value.lower() in ("true", "yes", "on"):
        return True
    if value.lower() in ("false", "no", "off"):
        return False

    # Null
    if value.lower() in ("null", "none", "~"):
        return None

    # Integer
    try:
        return int(value)
    except ValueError:
        pass

    # Float
    try:
        return float(value)
    except ValueError:
        pass

    # String (default)
    return value


class ConfigLoader:
    """
    Reusable configuration loader.

    Features:
      - Load YAML (.yaml, .yml) and JSON (.json) files
      - Merge multiple config sources with later files taking priority
      - Environment variable overrides with a configurable prefix
      - Proper error handling with descriptive exceptions

    Example::

        loader = ConfigLoader()
        loader.add_file("config/base.yaml")
        loader.add_file("config/production.json")
        loader.enable_env_overrides(prefix="MYAPP_")
        config = loader.load()
        print(config["database"]["host"])
    """

    def __init__(self) -> None:
        self._files: list[Path] = []
        self._env_prefix: str | None = None
        self._env_separator: str = "__"
        self._loaded: dict | None = None

    # ------------------------------------------------------------------
    # Configuration
    # ------------------------------------------------------------------

    def add_file(self, path: str | Path) -> "ConfigLoader":
        """Add a config file to the loader. Files are merged in order added."""
        p = Path(path).expanduser().resolve()
        if not p.exists():
            raise ConfigFileNotFoundError(f"Config file not found: {p}")
        suffix = p.suffix.lower()
        if suffix not in (".yaml", ".yml", ".json"):
            raise ConfigError(
                f"Unsupported config file format '{suffix}'. "
                "Use .yaml, .yml, or .json"
            )
        self._files.append(p)
        self._loaded = None  # Invalidate cache
        return self

    def enable_env_overrides(
        self, prefix: str = "", separator: str = "__"
    ) -> "ConfigLoader":
        """
        Enable environment variable overrides.

        Environment variables matching ``<prefix>*`` are mapped to config keys
        using *separator* to denote nesting.  For example, with prefix ``APP_``
        and default separator ``__``:

            APP_DATABASE__HOST=db.example.com   →   {"database": {"host": "db.example.com"}}
        """
        self._env_prefix = prefix
        self._env_separator = separator
        self._loaded = None
        return self

    # ------------------------------------------------------------------
    # Loading
    # ------------------------------------------------------------------

    def load(self) -> dict:
        """
        Load, merge, and return the final configuration dictionary.

        Later files override earlier ones. Environment variables override everything.
        """
        if self._loaded is not None:
            return self._loaded

        merged: dict = {}

        for fpath in self._files:
            raw = self._read_file(fpath)
            parsed = self._parse(fpath, raw)
            merged = _deep_merge(merged, parsed)

        if self._env_prefix is not None:
            env_overrides = self._collect_env_overrides()
            if env_overrides:
                merged = _deep_merge(merged, env_overrides)

        self._loaded = merged
        return merged

    # ------------------------------------------------------------------
    # Internals
    # ------------------------------------------------------------------

    @staticmethod
    def _read_file(path: Path) -> str:
        """Read a file and return its contents as a string."""
        try:
            return path.read_text(encoding="utf-8")
        except OSError as exc:
            raise ConfigFileNotFoundError(
                f"Cannot read config file: {path}"
            ) from exc

    @staticmethod
    def _parse(path: Path, content: str) -> dict:
        """Parse file content based on its extension."""
        suffix = path.suffix.lower()
        if suffix == ".json":
            try:
                return json.loads(content)
            except json.JSONDecodeError as exc:
                raise ConfigParseError(
                    f"Invalid JSON in {path}: {exc}"
                ) from exc
        else:
            # YAML
            try:
                return _parse_yaml_simple(content)
            except ConfigParseError:
                raise
            except Exception as exc:
                raise ConfigParseError(
                    f"Failed to parse YAML in {path}: {exc}"
                ) from exc

    def _collect_env_overrides(self) -> dict:
        """Scan environment variables and build an override dictionary."""
        result: dict = {}
        prefix = self._env_prefix or ""
        sep = self._env_separator

        for key, value in os.environ.items():
            if not key.startswith(prefix):
                continue

            # Strip prefix, then split on separator for nesting
            remainder = key[len(prefix):]
            parts = remainder.split(sep)

            # Build nested dict
            node = result
            for part in parts[:-1]:
                node = node.setdefault(part, {})
            node[parts[-1]] = _cast_value(value)

        return result


# ------------------------------------------------------------------
# Example usage
# ------------------------------------------------------------------

if __name__ == "__main__":
    import tempfile

    # Create example config files in a temporary directory
    tmp_dir = Path(tempfile.mkdtemp())

    base_yaml = tmp_dir / "base.yaml"
    base_yaml.write_text(
        "# Base configuration\n"
        "app:\n"
        "  name: MyApp\n"
        "  version: 1.0\n"
        "database:\n"
        "  host: localhost\n"
        "  port: 5432\n"
        "  name: mydb\n",
        encoding="utf-8",
    )

    override_json = tmp_dir / "override.json"
    override_json.write_text(
        json.dumps(
            {
                "database": {
                    "host": "prod-db.example.com",
                    "pool_size": 20,
                },
                "logging": {
                    "level": "WARNING",
                },
            },
            indent=2,
        ),
        encoding="utf-8",
    )

    print("=" * 50)
    print("Config Loader Demo")
    print("=" * 50)

    # Build config
    loader = ConfigLoader()
    loader.add_file(base_yaml)
    loader.add_file(override_json)

    # Simulate an env override
    os.environ["APP_DATABASE__PORT"] = "3306"
    os.environ["APP_DEBUG"] = "true"
    loader.enable_env_overrides(prefix="APP_")

    config = loader.load()

    # Display result
    print(f"\nLoaded config from:\n  - {base_yaml}\n  - {override_json}")
    print(f"  - Environment variables with prefix 'APP_'\n")
    print("Merged configuration:")
    print(json.dumps(config, indent=2))

    # Clean up env
    del os.environ["APP_DATABASE__PORT"]
    del os.environ["APP_DEBUG"]

    print(f"\nTemp files created in: {tmp_dir}")
