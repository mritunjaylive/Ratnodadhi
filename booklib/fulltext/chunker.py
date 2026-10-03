"""
fulltext/chunker.py – Sliding window chunking of document text into indexable units.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any


@dataclass
class Chunk:
    book_id: int
    chapter_index: int
    page_number: int
    chunk_index: int
    token_start: int
    token_end: int
    char_count: int
    text: str


def chunk_sections(
    book_id: int,
    sections: list[dict[str, Any]],
    target_tokens: int = 500,
    overlap_tokens: int = 50,
) -> list[Chunk]:
    """
    Split document sections into overlapping chunks respecting paragraph boundaries.
    """
    chunks: list[Chunk] = []
    chunk_idx = 0
    total_token_offset = 0

    for sec in sections:
        page_num = sec.get("page", 0)
        chap_num = sec.get("chapter", 0)
        sec_text = sec.get("text", "").strip()
        if not sec_text:
            continue

        # Split into paragraphs
        paras = [p.strip() for p in sec_text.split("\n\n") if p.strip()]
        if not paras:
            paras = [sec_text]

        curr_words: list[str] = []
        curr_start = total_token_offset

        for para in paras:
            words = para.split()
            if not words:
                continue

            if len(curr_words) + len(words) > target_tokens and curr_words:
                # Emit current chunk
                c_text = " ".join(curr_words)
                c_end = curr_start + len(curr_words) - 1
                chunks.append(
                    Chunk(
                        book_id=book_id,
                        chapter_index=chap_num,
                        page_number=page_num,
                        chunk_index=chunk_idx,
                        token_start=curr_start,
                        token_end=c_end,
                        char_count=len(c_text),
                        text=c_text,
                    )
                )
                chunk_idx += 1

                # Keep overlap for next window
                keep_count = min(overlap_tokens, len(curr_words))
                curr_words = curr_words[-keep_count:]
                curr_start = c_end - keep_count + 1

            curr_words.extend(words)

        if curr_words:
            c_text = " ".join(curr_words)
            c_end = curr_start + len(curr_words) - 1
            chunks.append(
                Chunk(
                    book_id=book_id,
                    chapter_index=chap_num,
                    page_number=page_num,
                    chunk_index=chunk_idx,
                    token_start=curr_start,
                    token_end=c_end,
                    char_count=len(c_text),
                    text=c_text,
                )
            )
            chunk_idx += 1
            total_token_offset = c_end + 1

    return chunks
