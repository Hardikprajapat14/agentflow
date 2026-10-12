import re


def split_text(text: str, chunk_size: int = 900, overlap: int = 150) -> list[str]:
    """Paragraph-aware splitter with character overlap."""
    text = re.sub(r"[ \t]+", " ", text.replace("\r", "")).strip()
    if not text:
        return []
    paragraphs = [p.strip() for p in re.split(r"\n\s*\n", text) if p.strip()]
    chunks: list[str] = []
    buf = ""
    for p in paragraphs:
        while len(p) > chunk_size:  # hard-split very long paragraphs
            cut = p.rfind(" ", 0, chunk_size)
            cut = cut if cut > chunk_size // 2 else chunk_size
            if buf:
                chunks.append(buf)
                buf = ""
            chunks.append(p[:cut].strip())
            p = p[max(cut - overlap, 1):].strip()
        if len(buf) + len(p) + 2 <= chunk_size:
            buf = f"{buf}\n\n{p}".strip()
        else:
            if buf:
                chunks.append(buf)
            tail = buf[-overlap:] if buf and overlap else ""
            buf = f"{tail} {p}".strip() if tail and len(tail) + len(p) < chunk_size else p
    if buf:
        chunks.append(buf)
    return [c for c in chunks if len(c) > 20]
