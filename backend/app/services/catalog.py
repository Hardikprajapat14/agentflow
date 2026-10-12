from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import Document


def list_documents(db: Session, user_id: int) -> list[dict]:
    docs = db.scalars(select(Document).where(Document.user_id == user_id, Document.status == "ready")
                      .order_by(Document.created_at.desc()))
    return [{"id": d.id, "filename": d.filename, "type": d.file_type, "meta": d.meta or {}} for d in docs]


def format_documents(docs: list[dict]) -> str:
    if not docs:
        return "(no documents uploaded)"
    lines = []
    for d in docs:
        if d["type"] in ("csv", "xlsx"):
            cols = ", ".join((d["meta"].get("columns") or [])[:20])
            lines.append(f"- id={d['id']} | {d['filename']} | dataset, {d['meta'].get('rows', '?')} rows | columns: {cols}")
        else:
            lines.append(f"- id={d['id']} | {d['filename']} | text document, {d['meta'].get('chunks', '?')} indexed chunks")
    return "\n".join(lines)
