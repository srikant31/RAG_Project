"""
QueryDesk — Document Parser
Handles PDF and Markdown file parsing with robust error handling.
"""
from __future__ import annotations

import re
from pathlib import Path
from typing import Optional

import fitz  # PyMuPDF
import markdown

from QueryDesk.utils.logger import logger


class DocumentParser:
    """
    Parses PDF and Markdown documents into clean plain text.
    Supports: .pdf, .md, .markdown
    """

    SUPPORTED_EXTENSIONS = {".pdf", ".md", ".markdown"}

    def parse(self, file_path: str | Path) -> list[dict]:
        """
        Parse a document file into a list of page/section dicts.

        Returns:
            List of {"text": str, "page": int | None, "metadata": dict}
        """
        path = Path(file_path)

        if not path.exists():
            raise FileNotFoundError(f"Document not found: {file_path}")

        ext = path.suffix.lower()
        if ext not in self.SUPPORTED_EXTENSIONS:
            raise ValueError(
                f"Unsupported file type: {ext}. "
                f"Supported: {self.SUPPORTED_EXTENSIONS}"
            )

        logger.info(f"Parsing document: {path.name} ({ext})")

        if ext == ".pdf":
            return self._parse_pdf(path)
        else:
            return self._parse_markdown(path)

    def _parse_pdf(self, path: Path) -> list[dict]:
        """Extract text from each page of a PDF."""
        pages = []
        try:
            doc = fitz.open(str(path))
            for page_num, page in enumerate(doc, start=1):
                text = page.get_text("text")
                text = self._clean_text(text)
                if text.strip():
                    pages.append({
                        "text": text,
                        "page": page_num,
                        "metadata": {
                            "source": path.name,
                            "page": page_num,
                            "total_pages": len(doc),
                        },
                    })
            doc.close()
            logger.info(f"PDF parsed: {len(pages)} pages extracted from {path.name}")
            return pages
        except Exception as e:
            logger.error(f"Failed to parse PDF {path.name}: {e}")
            raise RuntimeError(f"PDF parsing failed for {path.name}: {e}") from e

    def _parse_markdown(self, path: Path) -> list[dict]:
        """Parse markdown into sections split by headers."""
        try:
            raw = path.read_text(encoding="utf-8")
            # Convert markdown to plain text by stripping HTML tags
            html = markdown.markdown(raw)
            plain = re.sub(r"<[^>]+>", " ", html)
            plain = self._clean_text(plain)

            # Split into sections by top-level headers
            sections = re.split(r"\n(?=#{1,3} )", raw)
            result = []
            for i, section in enumerate(sections, start=1):
                text = re.sub(r"<[^>]+>", " ", markdown.markdown(section))
                text = self._clean_text(text)
                if text.strip():
                    result.append({
                        "text": text,
                        "page": None,
                        "metadata": {
                            "source": path.name,
                            "section": i,
                        },
                    })

            logger.info(
                f"Markdown parsed: {len(result)} sections from {path.name}"
            )
            return result
        except Exception as e:
            logger.error(f"Failed to parse Markdown {path.name}: {e}")
            raise RuntimeError(
                f"Markdown parsing failed for {path.name}: {e}"
            ) from e

    @staticmethod
    def _clean_text(text: str) -> str:
        text = re.sub(r"<[^>]+>", " ", text)
        """Normalize whitespace and remove junk characters."""
        text = re.sub(r"\s+", " ", text)
        text = re.sub(r"[^\x20-\x7E\n]", "", text)
        return text.strip()
