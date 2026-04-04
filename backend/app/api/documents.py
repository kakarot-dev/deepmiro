"""
Document upload API — server-side validation and sanitization.
"""

import logging
import traceback

from flask import request, jsonify, g

from . import documents_bp
from ..models.document import DocumentManager

logger = logging.getLogger("mirofish.api.documents")


@documents_bp.route("/upload", methods=["POST"])
def upload_document():
    """
    Upload a document for use in simulations.

    Request: multipart/form-data with a single ``file`` field.
    Accepts PDF, Markdown, and plain-text files up to 10 MB.

    Returns::

        {
            "success": true,
            "data": {
                "document_id": "doc_a1b2c3d4e5f6",
                "filename": "report.pdf",
                "text_length": 20862,
                "mime_type": "application/pdf"
            }
        }
    """
    try:
        if "file" not in request.files:
            return jsonify({"success": False, "error": "No file provided"}), 400

        file = request.files["file"]
        if not file.filename:
            return jsonify({"success": False, "error": "No filename"}), 400

        user_id = getattr(g, "user_id", None)
        doc = DocumentManager.create_document(file, user_id=user_id)

        logger.info(
            "Document uploaded: %s (%s, %d bytes, %d chars text)",
            doc.document_id, doc.original_filename, doc.file_size, doc.text_length,
        )

        return jsonify({
            "success": True,
            "data": {
                "document_id": doc.document_id,
                "filename": doc.original_filename,
                "text_length": doc.text_length,
                "mime_type": doc.mime_type,
            },
        })

    except ValueError as e:
        return jsonify({"success": False, "error": str(e)}), 400
    except Exception as e:
        logger.error("Document upload failed: %s\n%s", e, traceback.format_exc())
        return jsonify({"success": False, "error": str(e)}), 500
