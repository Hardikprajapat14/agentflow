import os
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import FileResponse
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.database import get_db
from app.models import TERMINAL_STATUSES, Approval, AuditLog, User, Workflow
from app.schemas import ApprovalOut, ApprovalResolve, AuditOut, WorkflowCreate, WorkflowOut, WorkflowSummary
from app.security.auth import get_current_user
from app.services.audit import audit
from app.services.report import ensure_report_files, report_paths
from app.workers.dispatch import dispatch_workflow

router = APIRouter(tags=["workflows"])


def _owned(db: Session, workflow_id: int, user: User) -> Workflow:
    wf = db.get(Workflow, workflow_id)
    if not wf or wf.user_id != user.id:
        raise HTTPException(404, "Workflow not found")
    return wf


def _summary(wf: Workflow) -> dict:
    d = WorkflowSummary.model_validate(wf).model_dump()
    d["total_steps"] = len(wf.steps)
    d["completed_steps"] = sum(1 for s in wf.steps if s.status == "completed")
    return d


def _detail(wf: Workflow) -> WorkflowOut:
    base = _summary(wf)
    return WorkflowOut(**base, plan=wf.plan, result=wf.result, steps=wf.steps,
                       approvals=[ApprovalOut.model_validate(a) for a in wf.approvals])


@router.post("/workflows", response_model=WorkflowOut, status_code=201)
def create_workflow(body: WorkflowCreate, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    title = (body.title or body.description.strip()[:60]).strip()
    wf = Workflow(user_id=user.id, title=title, description=body.description.strip(),
                  require_approval=body.require_approval, status="pending")
    db.add(wf)
    db.commit()
    audit(db, "workflow_created", f"Workflow '{title}' created", user_id=user.id, workflow_id=wf.id)
    try:
        dispatch_workflow(wf.id)
    except Exception as exc:  # noqa: BLE001
        wf.status, wf.error, wf.completed_at = "failed", f"Task queue unavailable: {exc}"[:500], datetime.now(timezone.utc)
        db.commit()
        raise HTTPException(503, "Background worker queue is unavailable. Is Redis running?") from exc
    return _detail(wf)


@router.get("/workflows", response_model=list[WorkflowSummary])
def list_workflows(user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    rows = db.scalars(select(Workflow).where(Workflow.user_id == user.id).order_by(Workflow.created_at.desc()).limit(200))
    return [_summary(w) for w in rows]


@router.get("/workflows/{workflow_id}", response_model=WorkflowOut)
def get_workflow(workflow_id: int, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    wf = _owned(db, workflow_id, user)
    db.refresh(wf)
    return _detail(wf)


@router.delete("/workflows/{workflow_id}", status_code=204)
def delete_workflow(workflow_id: int, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    wf = _owned(db, workflow_id, user)
    if wf.status not in TERMINAL_STATUSES and wf.status != "awaiting_approval":
        raise HTTPException(409, "Workflow is still running")
    for p in report_paths(wf.id).values():
        if os.path.exists(p):
            os.remove(p)
    db.delete(wf)
    db.commit()


@router.get("/workflows/{workflow_id}/audit", response_model=list[AuditOut])
def workflow_audit(workflow_id: int, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    _owned(db, workflow_id, user)
    return list(db.scalars(select(AuditLog).where(AuditLog.workflow_id == workflow_id).order_by(AuditLog.id)))


@router.get("/workflows/{workflow_id}/report.{fmt}")
def download_report(workflow_id: int, fmt: str, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    wf = _owned(db, workflow_id, user)
    if fmt not in ("pdf", "md"):
        raise HTTPException(404, "Unknown format")
    path = ensure_report_files(wf)[fmt]
    if not os.path.exists(path):
        raise HTTPException(404, "Report is not available yet")
    media = "application/pdf" if fmt == "pdf" else "text/markdown"
    return FileResponse(path, media_type=media, filename=f"agentflow_report_{wf.id}.{fmt}")


# ------------------------------------------------------------------ approvals
@router.get("/approvals", response_model=list[ApprovalOut])
def list_approvals(status: str = "pending", user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    q = (select(Approval, Workflow.title).join(Workflow, Workflow.id == Approval.workflow_id)
         .where(Workflow.user_id == user.id).order_by(Approval.id.desc()).limit(100))
    if status != "all":
        q = q.where(Approval.status == status)
    out = []
    for appr, title in db.execute(q).all():
        item = ApprovalOut.model_validate(appr)
        item.workflow_title = title
        out.append(item)
    return out


@router.post("/approvals/{approval_id}/resolve", response_model=ApprovalOut)
def resolve_approval(approval_id: int, body: ApprovalResolve, user: User = Depends(get_current_user),
                     db: Session = Depends(get_db)):
    appr = db.get(Approval, approval_id)
    wf = db.get(Workflow, appr.workflow_id) if appr else None
    if not appr or not wf or wf.user_id != user.id:
        raise HTTPException(404, "Approval not found")
    if appr.status != "pending":
        raise HTTPException(409, f"Approval already {appr.status}")
    step = next(s for s in wf.steps if s.id == appr.step_id)
    appr.status = "approved" if body.approve else "rejected"
    appr.note, appr.resolved_at = body.note, datetime.now(timezone.utc)
    if body.approve:
        step.status, wf.status = "pending", "running"
    else:
        step.status, wf.status, wf.completed_at = "rejected", "rejected", datetime.now(timezone.utc)
        wf.error = f"Rejected by user at step {step.step_number} ({step.name})" + (f": {body.note}" if body.note else "")
        for s in wf.steps:
            if s.status == "pending":
                s.status = "skipped"
    db.commit()
    audit(db, f"approval_{appr.status}", f"Step {step.step_number} '{step.name}' {appr.status} by user",
          user_id=user.id, workflow_id=wf.id, meta={"note": body.note})
    if body.approve:
        try:
            dispatch_workflow(wf.id)
        except Exception as exc:  # noqa: BLE001
            raise HTTPException(503, f"Approved, but the worker queue is unavailable: {exc}") from exc
    item = ApprovalOut.model_validate(appr)
    item.workflow_title = wf.title
    return item
