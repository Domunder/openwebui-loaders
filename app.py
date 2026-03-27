"""
PyPDF External Document Extraction Service for OpenWebUI
=========================================================
Implements the OpenWebUI External Content Extraction Engine API.
OpenWebUI sends:  PUT /process  (multipart form-data, field name: "file")
This service responds with: {"documents": [{"page_content": "...", "metadata": {...}}]}
Mode: "single" — the entire PDF is returned as one Document object.
"""

import logging
import os
import tempfile
from pathlib import Path

from fastapi import FastAPI, File, Header, HTTPException, UploadFile
from fastapi.responses import JSONResponse
from langchain_community.document_loaders import PyPDFLoader

# ---------------------------------------------------------------------------
# Logging
# ---------------------------------------------------------------------------
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s - %(message)s",
)
log = logging.getLogger("pypdf-extractor")

# ---------------------------------------------------------------------------
# Config (all overridable via environment variables)
# ---------------------------------------------------------------------------
API_KEY: str = os.getenv("API_KEY", "")          # empty = no auth required
PYPDF_MODE: str = os.getenv("PYPDF_MODE", "single")  # "single" | "page"
PAGES_DELIMITER: str = os.getenv("PAGES_DELIMITER", "\n")
EXTRACT_IMAGES: bool = os.getenv("EXTRACT_IMAGES", "false").lower() == "true"

# ---------------------------------------------------------------------------
# FastAPI app
# ---------------------------------------------------------------------------
app = FastAPI(
    title="PyPDF External Document Extractor",
    description="OpenWebUI-compatible external content extraction engine using LangChain PyPDFLoader.",
    version="1.0.0",
)


@app.get("/health")
async def health() -> dict:
    """Liveness / readiness probe."""
    return {"status": "ok"}


@app.put("/process")
async def process_document(
    file: UploadFile = File(...),
    authorization: str | None = Header(default=None),
    # Optional user-context headers forwarded by OpenWebUI when
    # ENABLE_FORWARD_USER_INFO_HEADERS=true
    x_user_id: str | None = Header(default=None),
    x_user_email: str | None = Header(default=None),
    x_user_name: str | None = Header(default=None),
    x_user_role: str | None = Header(default=None),
) -> JSONResponse:
    """
    Main extraction endpoint.

    OpenWebUI sends the raw file bytes as multipart/form-data.
    We write it to a temp file, run PyPDFLoader, and return the
    extracted documents in the format OpenWebUI expects.
    """
    # --- Optional bearer-token auth ---
    if API_KEY:
        token = ""
        if authorization and authorization.lower().startswith("bearer "):
            token = authorization[7:].strip()
        if token != API_KEY:
            raise HTTPException(status_code=401, detail="Unauthorized")

    filename: str = file.filename or "upload.pdf"
    log.info(
        "Processing file=%s user=%s role=%s",
        filename,
        x_user_name or x_user_id or "anonymous",
        x_user_role or "-",
    )

    # --- Write upload to a temporary file so PyPDFLoader can read it ---
    suffix = Path(filename).suffix or ".pdf"
    with tempfile.NamedTemporaryFile(delete=False, suffix=suffix) as tmp:
        tmp_path = tmp.name
        content = await file.read()
        tmp.write(content)

    try:
        documents = _extract(tmp_path, filename)
    except Exception as exc:
        log.exception("Extraction failed for %s", filename)
        raise HTTPException(status_code=500, detail=f"Extraction error: {exc}") from exc
    finally:
        try:
            os.unlink(tmp_path)
        except OSError:
            pass

    log.info("Extracted %d document(s) from %s", len(documents), filename)

    # Serialise to the format OpenWebUI's ExternalDocumentLoader expects:
    # {"documents": [{"page_content": str, "metadata": dict}, ...]}
    payload = {
        "documents": [
            {
                "page_content": doc.page_content,
                "metadata": doc.metadata,
            }
            for doc in documents
        ]
    }
    return JSONResponse(content=payload)


# ---------------------------------------------------------------------------
# Extraction logic
# ---------------------------------------------------------------------------
def _extract(file_path: str, original_filename: str):
    """
    Run PyPDFLoader in the configured mode and return a list of
    langchain Document objects.
    """
    loader_kwargs: dict = {
        "extract_images": EXTRACT_IMAGES,
    }

    if PYPDF_MODE == "single":
        loader_kwargs["mode"] = "single"
        if PAGES_DELIMITER:
            loader_kwargs["pages_delimiter"] = PAGES_DELIMITER
    else:
        loader_kwargs["mode"] = "page"

    loader = PyPDFLoader(file_path, **loader_kwargs)
    docs = loader.load()

    # Patch the "source" metadata field to use the original filename
    # instead of the temp-file path, which would be meaningless to the caller.
    for doc in docs:
        doc.metadata["source"] = original_filename

    return docs
