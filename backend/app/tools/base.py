from dataclasses import dataclass, field
from typing import Any, Callable

from sqlalchemy.orm import Session


class ToolError(Exception):
    """A tool failed in an expected, user-explainable way."""


@dataclass
class ToolContext:
    db: Session
    user_id: int
    workflow_id: int
    objective: str
    prior: dict[int, dict] = field(default_factory=dict)  # step_number -> output_data


@dataclass
class ToolResult:
    summary: str
    data: dict[str, Any] = field(default_factory=dict)
    charts: list[dict] = field(default_factory=list)


@dataclass
class Tool:
    name: str
    description: str
    parameters: dict
    fn: Callable[[dict, ToolContext], ToolResult]
    sensitive: bool = False  # sensitive tools always require human approval
    planner_visible: bool = True

    def clean_args(self, args: dict) -> dict:
        allowed = set(self.parameters.get("properties", {}))
        return {k: v for k, v in (args or {}).items() if k in allowed and v not in (None, "")}

    def run(self, args: dict, ctx: ToolContext) -> ToolResult:
        return self.fn(self.clean_args(args), ctx)


REGISTRY: dict[str, Tool] = {}


def register(tool: Tool) -> Tool:
    REGISTRY[tool.name] = tool
    return tool
