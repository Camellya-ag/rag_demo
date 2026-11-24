from __future__ import annotations

import re
from dataclasses import dataclass

from backend.app.config import SOURCE_FILE
from backend.app.utils.text import CHAPTER_RE, chunk_region_spans, cn_to_int, estimate_tokens


@dataclass
class SourceChunk:
    id: str
    chapter: int
    chapter_title: str
    text: str
    tokens: int
    source: str = "西游记.txt"
    start_char: int = 0
    end_char: int = 0


@dataclass
class SourceMeta:
    file_name: str
    author: str
    size_bytes: int
    lines: int
    chapters: int
    text: str


class SourceLoader:
    def __init__(self, path=SOURCE_FILE) -> None:
        self.path = path
        self._span_cache: list[tuple[str, int, int]] | None = None

    def read_text(self) -> str:
        return self.path.read_text(encoding="utf-8")

    def meta(self) -> SourceMeta:
        text = self.read_text()
        lines = text.count("\n") + 1
        chapters = len(CHAPTER_RE.findall(text))
        author = "吴承恩（明）"
        first_line = text.splitlines()[0] if text else ""
        if "吴承恩" in first_line:
            author = first_line.replace("《西游记》", "").strip() or author
        return SourceMeta(
            file_name=self.path.name,
            author=author,
            size_bytes=self.path.stat().st_size,
            lines=lines,
            chapters=chapters,
            text=text,
        )

    def split_chapters(self, text: str) -> list[tuple[int, str, str]]:
        matches = list(CHAPTER_RE.finditer(text))
        if not matches:
            return [(0, "前言", text)]
        out = []
        for idx, match in enumerate(matches):
            chapter = cn_to_int(match.group(1))
            start = match.start()
            end = matches[idx + 1].start() if idx + 1 < len(matches) else len(text)
            title_line = text[match.start(): text.find("\n", match.start())].strip()
            out.append((chapter, title_line, text[start:end]))
        return out

    def chapter_spans(self, text: str) -> list[tuple[int, int, int, str]]:
        matches = list(CHAPTER_RE.finditer(text))
        if not matches:
            return [(0, 0, len(text), "前言")]
        out: list[tuple[int, int, int, str]] = []
        for idx, match in enumerate(matches):
            chapter = cn_to_int(match.group(1))
            start = match.start()
            end = matches[idx + 1].start() if idx + 1 < len(matches) else len(text)
            title_line = text[match.start() : text.find("\n", match.start())].strip()
            out.append((chapter, start, end, title_line))
        return out

    def chunk(self, *, chapter_limit: int | None = None, chunk_limit: int | None = None,
              chunk_size=512, overlap=64) -> list[SourceChunk]:
        meta = self.meta()
        chunks: list[SourceChunk] = []
        counter = 1
        full = meta.text
        for chapter, chapter_start, chapter_end, title in self.chapter_spans(full):
            if chapter_limit and chapter > chapter_limit:
                break
            for start_char, end_char in chunk_region_spans(
                full,
                chapter_start,
                chapter_end,
                chunk_size=chunk_size,
                overlap=overlap,
            ):
                chunk_id = f"c-{counter:06d}"
                piece = full[start_char:end_char]
                chunks.append(
                    SourceChunk(
                        id=chunk_id,
                        chapter=chapter,
                        chapter_title=title,
                        text=piece,
                        tokens=estimate_tokens(piece),
                        start_char=start_char,
                        end_char=end_char,
                    )
                )
                counter += 1
                if chunk_limit and len(chunks) >= chunk_limit:
                    return chunks
        return chunks

    def chunk_spans(self, **kwargs) -> list[tuple[str, int, int]]:
        if self._span_cache is not None and not kwargs:
            return self._span_cache
        spans = [(c.id, c.start_char, c.end_char) for c in self.chunk(**kwargs)]
        if not kwargs:
            self._span_cache = spans
        return spans

    def find_chunk_ids_for_range(self, start_char: int, end_char: int, **kwargs) -> list[str]:
        hits: list[str] = []
        for chunk_id, c0, c1 in self.chunk_spans(**kwargs):
            if c1 < start_char or c0 > end_char:
                continue
            hits.append(chunk_id)
        return hits

    def distribution(self, chunks: list[SourceChunk]) -> list[dict]:
        buckets: dict[str, int] = {}
        for chunk in chunks:
            start = ((max(chunk.chapter, 1) - 1) // 10) * 10 + 1
            end = start + 9
            label = f"第 {start}-{end} 回"
            buckets[label] = buckets.get(label, 0) + 1
        return [{"label": label, "value": value} for label, value in sorted(buckets.items(), key=lambda x: x[0])]


source_loader = SourceLoader()
