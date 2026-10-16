"""가이드 텍스트(.txt, Markdown 형식) 로딩 + 섹션/청킹."""
import re
from pathlib import Path

from langchain_core.documents import Document
from langchain_text_splitters import RecursiveCharacterTextSplitter

from src.config import Settings

_HEADER = re.compile(r"\A---\n(.*?)\n---\n", re.S)


def parse_guide(path: Path) -> tuple[dict, list[tuple[str, str]]]:
    text = path.read_text(encoding="utf-8").replace("\r\n", "\n")
    meta: dict = {}
    m = _HEADER.match(text)
    if m:
        for line in m.group(1).splitlines():
            if ":" in line:
                k, v = line.split(":", 1)
                meta[k.strip()] = v.strip()
        text = text[m.end():]
    parts = re.split(r"^## (.+)$", text, flags=re.M)   # [pre, title1, body1, title2, body2 ...]
    sections = [(parts[i].strip(), parts[i + 1].strip()) for i in range(1, len(parts) - 1, 2)]
    if not sections:
        sections = [("전체", text.strip())]
    return meta, sections


def load_and_split(s: Settings) -> list[Document]:
    splitter = RecursiveCharacterTextSplitter(
        chunk_size=s.chunk_size, chunk_overlap=s.chunk_overlap,
        separators=["\n\n", "\n", "。", ". ", " ", ""])
    chunks: list[Document] = []
    for path in sorted(Path(s.guides_dir).glob("*.txt")):
        meta, sections = parse_guide(path)
        city = meta.get("city", path.stem)
        ko = meta.get("city_ko", city)
        for title, body in sections:
            for piece in splitter.split_text(body):
                chunks.append(Document(
                    page_content=f"[{ko} · {title}] {piece}",
                    metadata={"city": city, "city_ko": ko, "country": meta.get("country", ""),
                              "currency": meta.get("currency", ""), "section": title,
                              "source": path.name}))
    return chunks
