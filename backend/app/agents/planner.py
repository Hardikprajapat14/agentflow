"""Planner agent: natural-language task -> validated, structured execution plan (JSON)."""
import logging

from pydantic import BaseModel, Field, ValidationError

from app.services.llm import LLMClient, LLMError
from app.tools import REGISTRY

logger = logging.getLogger(__name__)
MAX_STEPS = 7


class PlanError(Exception):
    pass


class PlanStep(BaseModel):
    name: str = Field(min_length=2, max_length=120)
    tool: str
    objective: str = Field(min_length=3, max_length=600)
    requires_approval: bool = False


class Plan(BaseModel):
    title: str = Field(default="", max_length=200)
    rationale: str = ""
    steps: list[PlanStep]


SYSTEM = """You are the planning agent of an autonomous workflow platform. Convert the user's business task into a
short, ordered execution plan. Respond with ONE JSON object only:
{{"title": "<=8 word title", "rationale": "one or two sentences", "steps": [
  {{"name": "short step name", "tool": "<one tool name>", "objective": "precise goal of this step, mentioning dataset/column names where known", "requires_approval": false}}]}}

Available tools:
{tools}

Rules:
- Use only the tools listed. 2 to {max_steps} steps. Put data reading/analysis before charts and ML.
- Use rag_search whenever the task mentions policies, guidelines, documents or rules. Use web_search only if external/current information is needed.
- Use create_chart when visualizations are requested. Use ml_analysis for anomalies, outliers, forecasts or trends.
- Use send_email only if the user explicitly asks to email something, and set requires_approval true.
- Do NOT add validation or report steps; the platform adds them automatically.
User documents:
{docs}"""


def create_plan(llm: LLMClient, task: str, docs_text: str) -> Plan:
    tools = "\n".join(f"- {t.name}: {t.description}" for t in REGISTRY.values() if t.planner_visible)
    messages = [{"role": "system", "content": SYSTEM.format(tools=tools, docs=docs_text, max_steps=MAX_STEPS)},
                {"role": "user", "content": f"Task: {task}"}]
    last_err = ""
    for attempt in range(2):
        try:
            raw = llm.json(messages, max_tokens=1500)
            plan = Plan.model_validate(raw)
            steps = [s for s in plan.steps if s.tool in REGISTRY][:MAX_STEPS]
            for s in steps:
                if REGISTRY[s.tool].sensitive:
                    s.requires_approval = True
            if not steps:
                raise PlanError("Plan contained no usable steps")
            plan.steps = steps
            return plan
        except (ValidationError, PlanError, LLMError) as exc:
            last_err = str(exc)
            if isinstance(exc, LLMError) and not exc.retryable and exc.status in (400, 401, 403):
                raise PlanError(f"LLM request rejected: {exc}") from exc
            logger.warning("Planner attempt %d failed: %s", attempt + 1, last_err[:200])
            messages = messages + [{"role": "user", "content": f"Your plan was invalid ({last_err[:300]}). "
                                    "Return a corrected JSON object using only the listed tools."}]
    raise PlanError(f"Could not create a valid plan: {last_err[:300]}")
