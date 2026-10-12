from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, EmailStr, Field


class ORM(BaseModel):
    model_config = ConfigDict(from_attributes=True)


class UserCreate(BaseModel):
    email: EmailStr
    password: str = Field(min_length=8, max_length=128)
    name: str = Field(min_length=1, max_length=120)


class UserLogin(BaseModel):
    email: EmailStr
    password: str = Field(max_length=128)


class UserOut(ORM):
    id: int
    email: str
    name: str
    created_at: datetime


class TokenOut(BaseModel):
    access_token: str
    token_type: str = "bearer"
    user: UserOut


class WorkflowCreate(BaseModel):
    description: str = Field(min_length=10, max_length=4000)
    title: str | None = Field(default=None, max_length=255)
    require_approval: bool = True


class StepOut(ORM):
    id: int
    step_number: int
    name: str
    step_type: str
    status: str
    tool_name: str | None
    input_data: dict[str, Any] | None
    output_data: dict[str, Any] | None
    error: str | None
    started_at: datetime | None
    completed_at: datetime | None
    duration: float | None


class ApprovalOut(ORM):
    id: int
    workflow_id: int
    step_id: int
    action: str
    reason: str
    status: str
    note: str | None
    created_at: datetime
    resolved_at: datetime | None
    workflow_title: str | None = None


class ApprovalResolve(BaseModel):
    approve: bool
    note: str | None = Field(default=None, max_length=1000)


class WorkflowSummary(ORM):
    id: int
    title: str
    description: str
    status: str
    require_approval: bool
    error: str | None
    created_at: datetime
    started_at: datetime | None
    completed_at: datetime | None
    total_steps: int = 0
    completed_steps: int = 0


class WorkflowOut(WorkflowSummary):
    plan: dict[str, Any] | None
    result: dict[str, Any] | None
    steps: list[StepOut]
    approvals: list[ApprovalOut]


class DocumentOut(ORM):
    id: int
    filename: str
    file_type: str
    file_size: int
    status: str
    error: str | None
    meta: dict[str, Any] | None
    created_at: datetime


class AuditOut(ORM):
    id: int
    event_type: str
    message: str
    meta: dict[str, Any] | None
    created_at: datetime
