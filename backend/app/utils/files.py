import os

from app.models import Document


def ensure_local_file(doc: Document) -> str:
    """Return a readable path for the document, restoring it from the database if the disk was wiped."""
    if not os.path.exists(doc.storage_path):
        if not doc.content:
            raise FileNotFoundError(f"The stored file for '{doc.filename}' is missing. Please upload it again.")
        os.makedirs(os.path.dirname(doc.storage_path), exist_ok=True)
        with open(doc.storage_path, "wb") as fh:
            fh.write(doc.content)
    return doc.storage_path
