from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from code_harness.core.agent import LeadAgent


_lead_agent: "LeadAgent | None" = None


def set_lead_agent(agent: "LeadAgent | None") -> None:
    global _lead_agent
    _lead_agent = agent


def get_lead_agent() -> "LeadAgent":
    if _lead_agent is None:
        raise RuntimeError("Lead agent is not configured")
    return _lead_agent
