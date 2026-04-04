"""
Document model — server-side file upload with validation and sanitization.
"""

import json
import os
import uuid
from dataclasses import dataclass, asdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from ..config import Config
from ..utils.file_parser import FileParser

DOCUMENT_DIR = os.path.join(Config.UPLOAD_FOLDER, "documents")

# Magic byte signatures for allowed file types
_PDF_MAGIC = b"%PDF"
_MAX_SIZE = 10 * 1024 * 1024  # 10 MB

ALLOWED_EXTENSIONS = {"pdf", "md", "txt", "markdown"}
MIME_MAP = {
    "pdf": "application/pdf",
    "md": "text/markdown",
    "markdown": "text/markdown",
    "txt": "text/plain",
}


@dataclass
class Document:
    document_id: str
    original_filename: str
    mime_type: str
    text_length: int
    file_size: int
    created_at: str
    user_id: Optional[str] = None

    def to_dict(self):
        return asdict(self)


class DocumentManager:
    """Handles upload validation, sanitization, text extraction, and storage."""

    @staticmethod
    def _ensure_dir(doc_id: str) -> str:
        doc_dir = os.path.join(DOCUMENT_DIR, doc_id)
        os.makedirs(doc_dir, exist_ok=True)
        return doc_dir

    @classmethod
    def create_document(cls, file_storage, user_id: Optional[str] = None) -> Document:
        """Validate, sanitize, extract text, and persist a document.

        Args:
            file_storage: werkzeug FileStorage object from request.files
            user_id: optional user ID from auth context

        Returns:
            Document with document_id and extracted text_length

        Raises:
            ValueError: on validation failure
        """
        filename = file_storage.filename or ""
        ext = Path(filename).suffix.lstrip(".").lower()

        # --- Extension check ---
        if ext not in ALLOWED_EXTENSIONS:
            raise ValueError(
                f"Unsupported file type '.{ext}'. Allowed: {', '.join(sorted(ALLOWED_EXTENSIONS))}"
            )

        # --- Read file bytes ---
        data = file_storage.read()
        if len(data) > _MAX_SIZE:
            raise ValueError(f"File too large ({len(data)} bytes). Max: {_MAX_SIZE // (1024*1024)} MB")
        if len(data) == 0:
            raise ValueError("Empty file")

        # --- Magic byte validation ---
        if ext == "pdf":
            if not data[:4].startswith(_PDF_MAGIC):
                raise ValueError("File extension is .pdf but content is not a valid PDF")
        else:
            # Text files: reject if binary (null bytes in first 512 bytes)
            if b"\x00" in data[:512]:
                raise ValueError("File appears to be binary, not text")

        # --- Persist original file ---
        doc_id = f"doc_{uuid.uuid4().hex[:12]}"
        doc_dir = cls._ensure_dir(doc_id)
        original_path = os.path.join(doc_dir, f"original.{ext}")
        with open(original_path, "wb") as f:
            f.write(data)

        # --- Extract text (sanitization happens here) ---
        # PyMuPDF's get_text() strips JS, forms, embedded objects from PDFs
        extracted_text = FileParser.extract_text(original_path)

        # Save extracted text
        text_path = os.path.join(doc_dir, "extracted.txt")
        with open(text_path, "w", encoding="utf-8") as f:
            f.write(extracted_text)

        # --- Build document record ---
        doc = Document(
            document_id=doc_id,
            original_filename=filename,
            mime_type=MIME_MAP.get(ext, "application/octet-stream"),
            text_length=len(extracted_text),
            file_size=len(data),
            created_at=datetime.now(timezone.utc).isoformat(),
            user_id=user_id,
        )

        # Save metadata
        meta_path = os.path.join(doc_dir, "meta.json")
        with open(meta_path, "w", encoding="utf-8") as f:
            json.dump(doc.to_dict(), f, ensure_ascii=False, indent=2)

        return doc

    @classmethod
    def get_document(cls, document_id: str) -> Optional[Document]:
        meta_path = os.path.join(DOCUMENT_DIR, document_id, "meta.json")
        if not os.path.exists(meta_path):
            return None
        with open(meta_path, "r", encoding="utf-8") as f:
            return Document(**json.load(f))

    @classmethod
    def get_document_text(cls, document_id: str) -> Optional[str]:
        text_path = os.path.join(DOCUMENT_DIR, document_id, "extracted.txt")
        if not os.path.exists(text_path):
            return None
        with open(text_path, "r", encoding="utf-8") as f:
            return f.read()
