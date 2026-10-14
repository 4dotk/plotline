from dataclasses import replace

from plotline.agents import aggregator, anomaly, diagnostic, planner, scanner, validator
from plotline.agents.stubs import stub_agents  # noqa: F401
from plotline.state import AgentSet


def default_agents() -> AgentSet:
    """The real agents A-E and G (the Diagnostic: model text in live/replay, template when off)."""
    return replace(
        stub_agents(), plan=planner.plan, repair=planner.repair, scan=scanner.scan,
        aggregate=aggregator.aggregate, validate=validator.validate, analyse=anomaly.analyse, diagnose=diagnostic.diagnose,
    )
