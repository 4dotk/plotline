from dataclasses import replace

from plotline.agents import planner, scanner
from plotline.agents.stubs import stub_agents  # noqa: F401
from plotline.state import AgentSet


def default_agents() -> AgentSet:
    """The real agents that exist so far (A, B); stubs for the rest."""
    return replace(stub_agents(), plan=planner.plan, repair=planner.repair, scan=scanner.scan)
