from enum import Enum
import fnmatch
import json
import re
import shlex
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, Field, ValidationError

PROJECT_ROOT = Path(__file__).resolve().parents[1]
PATH_FIELD_NAMES = {"path", "file_path", "dir_path", "directory", "cwd"}
TOOL_NAME_ALIASES = {
    "bash": "bash",
    "read": "read_file",
    "read_file": "read_file",
    "edit": "edit_file",
    "edit_file": "edit_file",
    "write": "write_file",
    "write_file": "write_file",
    "write file": "write_file",
    "todo": "todo",
}

class Rule:

    def __init__(self, tool_name, pattern="*"):
        self.tool_name = normalize_tool_name(tool_name)
        self.pattern = pattern or "*"

    @classmethod
    def from_text(cls, rule_text: str) -> "Rule":
        match = re.fullmatch(r"\s*([^()\s][^()]*)\s*(?:\((.*)\))?\s*", rule_text)
        if not match:
            raise ValueError(f"Invalid permission rule: {rule_text}")

        tool_name = match.group(1).strip()
        pattern = match.group(2).strip() if match.group(2) is not None else "*"
        return cls(tool_name, pattern)


def normalize_tool_name(tool_name: str) -> str:
    key = tool_name.strip().lower()
    return TOOL_NAME_ALIASES.get(key, key)

class PermissionDecision(Enum):
    ALLOW = "allow"
    DENY = "deny"
    ASK = "ask"

GRAY_AREA_PATTERNS = [
    r"[|;&]",                 # pipes / command chaining
    r">\s*|>>\s*|<\s*",       # redirection
    r"\$\(|`",                # substitution
    r"\b(npm|pip|brew|apt|cargo|go)\s+(install|add|get)\b",
    r"\b(curl|wget|ssh|scp|rsync)\b",
    r"\b(/etc|/var|/usr|/bin|/sbin|~/.ssh)\b",
    r"\b(env|printenv|cat)\b.*(\.env|secret|token|key|credentials)\b",
    r"\b(chmod|chown)\b",
    r"\b(find|xargs)\b",
]


class CommandSafetyReview(BaseModel):
    risk: Literal["low", "medium", "high"]
    decision: Literal["allow", "ask_user", "deny"]
    reason: str = Field(min_length=1)
    safer_alternative: str = ""


def is_gray_area_command(command: str) -> bool:
    return any(re.search(pattern, command) for pattern in GRAY_AREA_PATTERNS)


def parse_safety_review(text: str) -> CommandSafetyReview | None:
    try:
        return CommandSafetyReview.model_validate_json(text)
    except ValidationError:
        return None


async def review_command_with_llm(
    command: str,
    llm_client=None,
    model: str | None = None,
) -> CommandSafetyReview:
    if llm_client is None:
        from code_harness.core.llm_client import LLMClient

        llm_client = LLMClient()
    if model is None:
        from code_harness.models import ROUTER_MODEL

        model = ROUTER_MODEL

    prompt = f"""You are a command safety reviewer for a coding-agent workspace.

Decide whether this shell command is safe to run. Consider pipes, redirects,
substitution, package installs, network access, secrets, system paths, and
commands that may touch many files.

Command:
{command}

Return ONLY valid JSON with this exact schema:
{{
  "risk": "low|medium|high",
  "decision": "allow|ask_user|deny",
  "reason": "...",
  "safer_alternative": "..."
}}
"""

    response = await llm_client.send(
        model=model,
        messages=[
            {"role": "system", "content": "You output strict JSON only."},
            {"role": "user", "content": prompt},
        ],
        tools=[],
    )
    text = response.choices[0].message.content or "{}"
    review = parse_safety_review(text)
    if review is None:
        raise ValueError("LLM safety review did not match the expected schema")
    return review


class PermissionEngine:

    DANGEROUS_PATTERNS = [
            r"rm\s+-rf\s+/",
            r"mkfs",
            r"dd\s+if=",
            r":\(\)\s*\{.*\}",   # fork bomb
            r">\s*/dev/sd",
        ]
    
    def __init__(self, workspace_root: str | Path = PROJECT_ROOT):
        self.allow_rules=[]
        self.deny_rules=[]
        self.ask_rules=[]
        self.set_workspace_root(workspace_root)

    def set_workspace_root(self, workspace_root: str | Path) -> None:
        self.workspace_root = Path(workspace_root).expanduser().resolve()

    def load_settings_json(self, path: str | Path = PROJECT_ROOT / "settings.json", clear_existing: bool = True) -> None:
        settings_path = Path(path).expanduser()
        if not settings_path.is_absolute():
            settings_path = PROJECT_ROOT / settings_path

        data = json.loads(settings_path.read_text(encoding="utf-8"))
        permissions = data.get("permissions", {})

        if clear_existing:
            self.allow_rules.clear()
            self.ask_rules.clear()
            self.deny_rules.clear()

        for rule_text in permissions.get("allow", []):
            self.allow(Rule.from_text(rule_text))
        for rule_text in permissions.get("ask", []):
            self.ask(Rule.from_text(rule_text))
        for rule_text in permissions.get("deny", []):
            self.deny(Rule.from_text(rule_text))

    def resolve_in_workspace(self, path: str | Path) -> Path:
        candidate = Path(path).expanduser()
        if not candidate.is_absolute():
            candidate = self.workspace_root / candidate

        resolved = candidate.resolve()
        if not resolved.is_relative_to(self.workspace_root):
            raise PermissionError(f"Path outside active workspace: {resolved}")
        return resolved

    def resolve_in_project(self, path: str | Path) -> Path:
        """Compatibility alias using the active workspace."""
        return self.resolve_in_workspace(path)

    def command_references_outside_workspace(self, command: str) -> bool:
        try:
            tokens = shlex.split(command)
        except ValueError:
            return True

        for token in tokens:
            if token in {"|", "&&", "||", ";", ">", ">>", "<"}:
                continue
            if token.startswith("-"):
                continue
            if "/" not in token and token not in {".", ".."}:
                continue

            try:
                self.resolve_in_workspace(token)
            except PermissionError:
                return True

        return False

    def command_references_outside_project(self, command: str) -> bool:
        """Compatibility alias using the active workspace."""
        return self.command_references_outside_workspace(command)

    def command_references_denied_read_path(self, command: str) -> bool:
        try:
            tokens = shlex.split(command)
        except ValueError:
            return True

        for token in tokens:
            if token in {"|", "&&", "||", ";", ">", ">>", "<", "2>", "2>>"}:
                continue
            if token.startswith("-"):
                continue
            if not self._looks_like_path_token(token):
                continue

            read_rule = Rule("read_file", json.dumps({"path": token}))
            if self._matches_any_rule(self.deny_rules, read_rule):
                return True

        return False

    def _looks_like_path_token(self, token: str) -> bool:
        return (
            token in {".", ".."}
            or token.startswith(".")
            or "/" in token
            or "\\" in token
        )


    def _has_tool_rule(self,rules, tool_name: str) -> bool:
        normalized_tool_name = normalize_tool_name(tool_name)
        return any(rule.tool_name == normalized_tool_name for rule in rules)

    def _matches_rule(self, permission_rule: Rule, tool_call: Rule) -> bool:
        if permission_rule.tool_name != tool_call.tool_name:
            return False

        return any(
            fnmatch.fnmatchcase(content, pattern)
            for content in self._contents_for_match(tool_call)
            for pattern in self._pattern_candidates(permission_rule.pattern)
        )

    def _matches_any_rule(self, rules: list[Rule], tool_call: Rule) -> bool:
        return any(self._matches_rule(rule, tool_call) for rule in rules)

    def _content_for_match(self, tool_call: Rule) -> str:
        return self._contents_for_match(tool_call)[0]

    def _contents_for_match(self, tool_call: Rule) -> list[str]:
        try:
            arguments = json.loads(tool_call.pattern or "{}")
        except json.JSONDecodeError:
            arguments = {}

        if tool_call.tool_name == "bash":
            return [str(arguments.get("command", tool_call.pattern or ""))]

        for field_name in ("path", "cwd", "file_path", "dir_path", "directory"):
            value = arguments.get(field_name)
            if value:
                return self._path_match_candidates(str(value))

        return [tool_call.pattern or ""]

    def _path_match_candidates(self, path: str) -> list[str]:
        candidates = [path]
        candidate = Path(path).expanduser()
        if not candidate.is_absolute():
            candidate = self.workspace_root / candidate

        try:
            resolved = candidate.resolve()
            relative = resolved.relative_to(self.workspace_root).as_posix()
        except ValueError:
            relative = Path(path).as_posix()

        candidates.append(relative)
        candidates.append(f"/{relative}")
        candidates.append(Path(relative).name)
        return list(dict.fromkeys(candidates))

    def _pattern_candidates(self, pattern: str) -> list[str]:
        candidates = [pattern]
        if "**/" in pattern:
            candidates.append(pattern.replace("**/", ""))
        return list(dict.fromkeys(candidates))
    
    def allow(self, rule:Rule):
        self.allow_rules.append(rule)

    def ask(self, rule:Rule):
        self.ask_rules.append(rule)

    def deny(self, rule:Rule):
        self.deny_rules.append(rule)



    def decide(self, rule: Rule)->PermissionDecision:

        content = self._content_for_match(rule)

        if self._matches_any_rule(self.deny_rules, rule):
            return PermissionDecision.DENY

        if rule.tool_name == "bash":
            for pattern in PermissionEngine.DANGEROUS_PATTERNS:
                if re.search(pattern, content):
                    return PermissionDecision.DENY

        if rule.tool_name == "bash" and self.command_references_outside_workspace(content):
            return PermissionDecision.DENY

        if rule.tool_name == "bash" and self.command_references_denied_read_path(content):
            return PermissionDecision.DENY

        if self._matches_any_rule(self.ask_rules, rule):
            return PermissionDecision.ASK
                
        
        if self._matches_any_rule(self.allow_rules, rule):
            return PermissionDecision.ALLOW
        
        return PermissionDecision.ASK

    async def decide_bash_with_llm_fallback(
        self,
        command: str,
        llm_client=None,
        model: str | None = None,
    ) -> PermissionDecision:
        rule = Rule("bash", json.dumps({"command": command}))
        deterministic_decision = self.decide(rule)

        if deterministic_decision in {PermissionDecision.ALLOW, PermissionDecision.DENY}:
            return deterministic_decision

        if not is_gray_area_command(command):
            return PermissionDecision.ASK

        try:
            review = await review_command_with_llm(
                command,
                llm_client=llm_client,
                model=model,
            )
        except Exception:
            return PermissionDecision.ASK

        if review.decision == "allow":
            return PermissionDecision.ALLOW
        if review.decision == "deny":
            return PermissionDecision.DENY
        return PermissionDecision.ASK
