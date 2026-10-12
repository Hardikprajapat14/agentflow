"""pgvector-backed chunk store."""
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import Document, DocumentChunk
from app.rag.chunking import split_text
from app.rag.embeddings import embed_query, embed_texts


def index_text(db: Session, document: Document, text: str) -> int:
    chunks = split_text(text)
    if not chunks:
        return 0
    db.query(DocumentChunk).filter(DocumentChunk.document_id == document.id).delete()
    for i in range(0, len(chunks), 64):
        batch = chunks[i : i + 64]
        for j, (content, vec) in enumerate(zip(batch, embed_texts(batch))):
            db.add(DocumentChunk(document_id=document.id, chunk_index=i + j, content=content, embedding=vec,
                                 meta={"filename": document.filename}))
    db.flush()
    return len(chunks)


def search(db: Session, user_id: int, query: str, top_k: int = 5, document_ids: list[int] | None = None) -> list[dict]:
    qvec = embed_query(query)
    dist = DocumentChunk.embedding.cosine_distance(qvec).label("distance")
    stmt = (
        select(DocumentChunk, Document.filename, dist)
        .join(Document, Document.id == DocumentChunk.document_id)
        .where(Document.user_id == user_id, Document.status == "ready")
        .order_by(dist)
        .limit(max(1, min(top_k, 10)))
    )
    if document_ids:
        stmt = stmt.where(Document.id.in_(document_ids))
    return [
        {"document_id": c.document_id, "filename": fn, "chunk_index": c.chunk_index, "content": c.content,
         "score": round(1 - float(d), 4)}
        for c, fn, d in db.execute(stmt).all()
    ]
