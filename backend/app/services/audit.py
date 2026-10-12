from sqlalchemy.orm import Session

from app.models import AuditLog
from app.utils.serialization import to_jsonable


def audit(db: Session, event_type: str, message: str, *, user_id: int | None = None,
          workflow_id: int | None = None, meta: dict | None = None, commit: bool = True) -> None:
    db.add(AuditLog(user_id=user_id, workflow_id=workflow_id, event_type=event_type,
                    message=message[:2000], meta=to_jsonable(meta) if meta else None))
    if commit:
        db.commit()
