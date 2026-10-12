import os

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.database import get_db
from app.models import Document, User
from app.schemas import DocumentOut
from app.security.auth import get_current_user
from app.services.audit import audit
from app.services.documents import save_upload
from app.workers.dispatch import dispatch_document

router = APIRouter(prefix="/documents", tags=["documents"])


@router.post("", response_model=DocumentOut, status_code=201)
def upload(file: UploadFile = File(...), user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    doc = save_upload(db, user, file)
    try:
        dispatch_document(doc.id)
    except Exception as exc:  # noqa: BLE001  (e.g. Redis down)
        doc.status, doc.error = "failed", f"Could not queue processing: {exc}"[:300]
        db.commit()
    return doc


@router.get("", response_model=list[DocumentOut])
def list_documents(user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    return list(db.scalars(select(Document).where(Document.user_id == user.id).order_by(Document.created_at.desc())))


@router.delete("/{document_id}", status_code=204)
def delete_document(document_id: int, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    doc = db.get(Document, document_id)
    if not doc or doc.user_id != user.id:
        raise HTTPException(404, "Document not found")
    path, name = doc.storage_path, doc.filename
    db.delete(doc)
    db.commit()
    if os.path.exists(path):
        os.remove(path)
    audit(db, "document_deleted", f"Deleted {name}", user_id=user.id)
