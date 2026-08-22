from collections.abc import Iterable
from pathlib import Path

from pydantic import BaseModel

from code_harness.tools.tools import BaseTool


DEFAULT_SKILL_DIRS = (
    Path(__file__).resolve().parents[1] / "skills",
    #Path(__file__).resolve().parents[2] / "harness_engineer" / "skills",
)


class Skill(BaseModel):
    name: str
    description: str
    content: str
    path: Path


class SkillLoader:
    def __init__(self, skill_dirs: Iterable[Path | str] | Path | str):
        self.skills: dict[str, Skill] = {}

        if isinstance(skill_dirs, (str, Path)):
            skill_dirs = [skill_dirs]

        for skill_dir in skill_dirs:
            self.load_from_dir(skill_dir)

    def load_from_dir(self, skill_dir: Path | str) -> None:
        skill_dir = Path(skill_dir)
        if not skill_dir.exists():
            return

        for file in skill_dir.rglob("SKILL.md"):
            content = file.read_text()
            metadata = self._parse_frontmatter(content)
            name = metadata.get("name", file.parent.name)
            description = metadata.get("description", "")

            self.skills[name] = Skill(
                name=name,
                description=description,
                content=content,
                path=file,
            )

    def _normalize_name(self, name: str) -> str:
        return name.strip().replace("_", "-")

    def list_skills_for_prompt(self) -> str:
        return "\n".join(
            f"- {s.name}: {s.description}"
            for s in self.skills.values()
        )

    def get_skill(self, name: str) -> str:
        normalized_name = self._normalize_name(name)
        skill = self.skills.get(name) or self.skills.get(normalized_name)
        if skill is None:
            return f"Skill not found: {name}"
        return skill.content
    
    def _parse_frontmatter(self, content: str) -> dict:
        if not content.startswith("---"):
            return {}

        parts = content.split("---", 2)
        if len(parts) < 3:
            return {}

        metadata = {}
        for line in parts[1].splitlines():
            if ":" not in line:
                continue
            key, value = line.split(":", 1)
            metadata[key.strip()] = value.strip().strip("\"'")
        return metadata

class LoadSkillInput(BaseModel):
    name: str
   


class LoadSkillTool(BaseTool):
    name = "load_skill"
    description = "Load detailed instructions for a named skill"
    input_model = LoadSkillInput
    concurrent_safe = True

    def __init__(self, skill_loader: SkillLoader | None = None):
        self.skill_loader = skill_loader or SkillLoader(DEFAULT_SKILL_DIRS)

    def run(self, arguments: LoadSkillInput) -> str:
        return self.skill_loader.get_skill(arguments.name)
