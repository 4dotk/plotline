from dataclasses import replace

from plotline.agents import aggregator, anomaly, planner, scanner, validator
from plotline.agents.stubs import stub_agents  # noqa: F401
from plotline.state import AgentSet


def default_agents() -> AgentSet:
    """The real agents A-E; the Diagnostic (G) is still the template stub."""
    return replace(
        stub_agents(), plan=planner.plan, repair=planner.repair, scan=scanner.scan,
        aggregate=aggregator.aggregate, validate=validator.validate, analyse=anomaly.analyse,
    )
