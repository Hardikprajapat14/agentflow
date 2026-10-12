"""Workflow executor: plan -> run tools (LLM function-calling for arguments) -> validate -> approval -> report.

Execution is resumable: every step is persisted, so after a human approval (or a worker restart) the executor
simply continues from the first pending step.
"""
import logging
import time
from datetime import datetime, timezone

from sqlalchemy.orm import Session

from app.agents.planner import PlanError, create_plan
from app.agents.validator import validate_workflow
from app.database import SessionLocal
from app.models import TERMINAL_STATUSES, Approval, Workflow, WorkflowStep
from app.services.audit import audit
from app.services.catalog import format_documents, list_documents
from app.services.llm import LLMClient, LLMError
from app.services.report import generate_report
from app.tools import REGISTRY, ToolContext, ToolError
from app.utils.serialization import compact_json, to_jsonable

logger = logging.getLogger(__name__)
FATAL_STEP_TYPES = {"planning", "validation", "report"}


def now() -> datetime:
    return datetime.now(timezone.utc)


class ExecutionAbort(Exception):
    pass


def execute_workflow(workflow_id: int) -> None:
    """Entry point used by Celery tasks (and the dev-mode thread dispatcher)."""
    db = SessionLocal()
    try:
        _execute(db, workflow_id)
    except Exception as exc:  # noqa: BLE001
        logger.exception("Workflow %s crashed", workflow_id)
        db.rollback()
        wf = db.get(Workflow, workflow_id)
        if wf and wf.status not in TERMINAL_STATUSES:
            _fail(db, wf, f"Unexpected error: {type(exc).__name__}: {exc}")
    finally:
        db.close()


def _fail(db: Session, wf: Workflow, message: str) -> None:
    wf.status, wf.error, wf.completed_at = "failed", message[:2000], now()
    for s in wf.steps:
        if s.status in ("pending", "awaiting_approval"):
            s.status = "skipped"
    db.commit()
    audit(db, "workflow_failed", message, user_id=wf.user_id, workflow_id=wf.id)


def _approval_state(db: Session, step: WorkflowStep) -> str:
    appr = db.query(Approval).filter(Approval.step_id == step.id).order_by(Approval.id.desc()).first()
    return appr.status if appr else "none"


def _needs_approval(wf: Workflow, step: WorkflowStep) -> bool:
    if step.step_type == "report":
        return bool(wf.require_approval)
    if step.step_type == "tool":
        tool = REGISTRY.get(step.tool_name or "")
        return bool((step.input_data or {}).get("requires_approval") or (tool and tool.sensitive))
    return False


def _execute(db: Session, workflow_id: int) -> None:
    wf = db.get(Workflow, workflow_id)
    if not wf or wf.status in TERMINAL_STATUSES:
        return
    llm = LLMClient()
    for s in wf.steps:  # recover from interrupted worker
        if s.status == "running":
            s.status = "pending"
    wf.started_at = wf.started_at or now()
    db.commit()

    if not wf.steps:
        wf.status = "planning"
        db.commit()
        audit(db, "workflow_started", "Workflow execution started", user_id=wf.user_id, workflow_id=wf.id)
        step = _add_step(db, wf, 1, "AI Planning", "planning", "planner", {"task": wf.description})
        _run_step(db, wf, step, lambda: _plan(db, wf, step, llm))
        if step.status == "failed":
            return _fail(db, wf, f"Planning failed: {step.error}")

    wf.status, wf.error = "running", None
    db.commit()
    while True:
        db.refresh(wf)
        steps = list(wf.steps)
        nxt = next((s for s in steps if s.status == "pending"), None)
        if nxt is None:
            break
        if _needs_approval(wf, nxt):
            state = _approval_state(db, nxt)
            if state == "none":
                tool = nxt.tool_name if nxt.step_type == "tool" else "final report"
                db.add(Approval(workflow_id=wf.id, step_id=nxt.id, action=f"Run: {nxt.name}",
                                reason=f"Sensitive action ({tool}) requires human approval before it executes. "
                                       f"Objective: {(nxt.input_data or {}).get('objective', wf.description)[:300]}"))
                nxt.status, wf.status = "awaiting_approval", "awaiting_approval"
                db.commit()
                audit(db, "approval_requested", f"Approval requested for step {nxt.step_number}: {nxt.name}",
                      user_id=wf.user_id, workflow_id=wf.id)
                return
            if state == "rejected":
                return
        handler = {"tool": lambda: _tool(db, wf, nxt, llm), "validation": lambda: _validate(wf, nxt),
                   "report": lambda: _report(db, wf, nxt, llm)}[nxt.step_type]
        _run_step(db, wf, nxt, handler)
        if nxt.status == "failed" and nxt.step_type in FATAL_STEP_TYPES:
            return _fail(db, wf, f"{nxt.name} failed: {nxt.error}")

    wf.status, wf.completed_at = "completed", now()
    db.commit()
    audit(db, "workflow_completed", "Workflow completed", user_id=wf.user_id, workflow_id=wf.id)


def _add_step(db, wf, number, name, step_type, tool, input_data) -> WorkflowStep:
    s = WorkflowStep(workflow_id=wf.id, step_number=number, name=name, step_type=step_type, tool_name=tool,
                     input_data=to_jsonable(input_data), status="pending")
    db.add(s)
    db.commit()
    wf.steps.append(s) if s not in wf.steps else None
    return s


def _run_step(db: Session, wf: Workflow, step: WorkflowStep, handler) -> None:
    step.status, step.started_at, step.error = "running", now(), None
    db.commit()
    t0 = time.perf_counter()
    try:
        step.output_data = to_jsonable(handler())
        step.status = "completed"
    except (ToolError, LLMError, PlanError, ExecutionAbort, ValueError) as exc:
        db.rollback()
        step.status, step.error = "failed", str(exc)[:2000]
    except Exception as exc:  # noqa: BLE001
        logger.exception("Step %s crashed", step.id)
        db.rollback()
        step.status, step.error = "failed", f"{type(exc).__name__}: {exc}"[:2000]
    step.completed_at, step.duration = now(), round(time.perf_counter() - t0, 3)
    db.commit()
    audit(db, f"step_{step.status}", f"Step {step.step_number} '{step.name}' {step.status}"
          + (f": {step.error}" if step.error else ""), user_id=wf.user_id, workflow_id=wf.id,
          meta={"tool": step.tool_name, "duration": step.duration})


# ------------------------------------------------------------------ step handlers
def _plan(db: Session, wf: Workflow, step: WorkflowStep, llm: LLMClient) -> dict:
    docs = list_documents(db, wf.user_id)
    plan = create_plan(llm, wf.description, format_documents(docs))
    wf.plan = to_jsonable(plan.model_dump())
    if plan.title and (not wf.title or wf.title == wf.description[:60]):
        wf.title = plan.title[:200]
    n = 2
    for ps in plan.steps:
        _add_step(db, wf, n, ps.name, "tool", ps.tool,
                  {"objective": ps.objective, "requires_approval": ps.requires_approval})
        n += 1
    _add_step(db, wf, n, "Result Validation", "validation", "validator", {"checks": "tool outputs"})
    _add_step(db, wf, n + 1, "Report Generation", "report", "report_generator", {"format": "markdown + pdf"})
    return {"summary": f"Created a {len(plan.steps)}-step plan: " + " -> ".join(s.tool for s in plan.steps),
            "data": plan.model_dump()}


def _tool_args(llm: LLMClient, wf: Workflow, step: WorkflowStep, docs_text: str, prior: dict) -> tuple[dict, str]:
    tool = REGISTRY[step.tool_name]
    prior_txt = "\n".join(f"Step {n}: {str(o.get('summary', ''))[:300]}" for n, o in sorted(prior.items())) or "(none)"
    messages = [
        {"role": "system", "content": "You prepare arguments for a tool call. Use exact dataset and column names from the "
                                      "catalog. Omit optional arguments you are unsure about."},
        {"role": "user", "content": f"Overall task: {wf.description}\nThis step: {step.name}\nObjective: "
                                    f"{(step.input_data or {}).get('objective')}\n\nDocuments:\n{docs_text}\n\nPrior results:\n{prior_txt}"}]
    try:
        return tool.clean_args(llm.call_tool(messages, tool.name, tool.description, tool.parameters)), "llm_tool_call"
    except LLMError as exc:
        logger.warning("Tool-call argument generation failed for %s (%s); using defaults", tool.name, str(exc)[:150])
        return {}, "defaults"


def _tool(db: Session, wf: Workflow, step: WorkflowStep, llm: LLMClient) -> dict:
    tool = REGISTRY.get(step.tool_name or "")
    if not tool:
        raise ExecutionAbort(f"Unknown tool '{step.tool_name}'")
    prior = {s.step_number: s.output_data for s in wf.steps if s.status == "completed" and s.output_data}
    args, source = _tool_args(llm, wf, step, format_documents(list_documents(db, wf.user_id)), prior)
    step.input_data = {**(step.input_data or {}), "arguments": to_jsonable(args), "arguments_source": source}
    db.commit()
    res = tool.run(args, ToolContext(db, wf.user_id, wf.id, (step.input_data or {}).get("objective", wf.description), prior))
    return {"summary": res.summary, "data": res.data, "charts": res.charts}


def _validate(wf: Workflow, step: WorkflowStep) -> dict:
    result = validate_workflow(list(wf.steps))
    if result["completed_tool_steps"] == 0:
        raise ExecutionAbort("No tool step completed successfully, so there is nothing to report on.")
    bad = [c for c in result["checks"] if not c["passed"] and c["critical"]]
    summary = (f"Validation {'passed' if result['passed'] else 'passed with issues'}: "
               f"{result['completed_tool_steps']}/{len(result['checks'])} tool outputs valid."
               + (f" Issues: {'; '.join(c['message'] for c in bad)[:300]}" if bad else ""))
    return {"summary": summary, "data": result}


def _report(db: Session, wf: Workflow, step: WorkflowStep, llm: LLMClient) -> dict:
    steps = list(wf.steps)
    validation = next((s.output_data or {}).get("data", {}) for s in steps if s.step_type == "validation")
    out = generate_report(db, wf, steps, validation, llm)
    wf.result = to_jsonable({"report_markdown": out["data"]["report_markdown"], "grounding": out["data"]["grounding"],
                             "used_llm": out["data"]["used_llm"], "validation": validation, "charts": out["charts"],
                             "files": {"pdf": True, "md": True}})
    db.commit()
    return {"summary": out["summary"], "data": {"grounding": out["data"]["grounding"], "used_llm": out["data"]["used_llm"]}}
