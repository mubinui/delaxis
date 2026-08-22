"""Generate documents and hand them back as downloads.

The counterpart to file upload: uploads bring documents in for agents to read,
this takes what agents produce back out as something a person can open.

Downloads are served from the generated directory only, resolved and then
checked for containment, so a crafted name cannot walk out of it.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Optional

from fastapi import APIRouter, HTTPException, Query, status
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field

from src.audit_logging import get_logger
from src.tools.documents import (
    FORMATS,
    MAX_CONTENT_CHARS,
    delete_generated_document,
    generate_document,
    generated_dir,
    list_generated_documents,
)

logger = get_logger(__name__)
router = APIRouter(prefix="/api/v1/documents", tags=["documents"])

#: Served inline where a browser can display it, downloaded where it cannot.
_INLINE = {".pdf", ".html", ".txt", ".md", ".json", ".csv"}
_MIME = {
    ".pdf": "application/pdf",
    ".html": "text/html; charset=utf-8",
    ".md": "text/markdown; charset=utf-8",
    ".txt": "text/plain; charset=utf-8",
    ".csv": "text/csv; charset=utf-8",
    ".json": "application/json",
    ".docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    ".xlsx": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
}


class GenerateRequest(BaseModel):
    content: str = Field(min_length=1, max_length=MAX_CONTENT_CHARS,
                         description="Document body, written as Markdown")
    filename: str = Field(default="document", max_length=120)
    format: str = Field(default="pdf", description=f"One of: {', '.join(FORMATS)}")
    title: Optional[str] = Field(default="", max_length=300)


@router.get("/formats")
async def formats() -> dict[str, Any]:
    """What can be generated, so a UI can offer the right choices."""
    return {"formats": list(FORMATS), "max_content_chars": MAX_CONTENT_CHARS}


@router.post("", status_code=status.HTTP_201_CREATED)
async def create(request: GenerateRequest) -> dict[str, Any]:
    result = generate_document(
        content=request.content,
        filename=request.filename,
        format=request.format,
        title=request.title or "",
    )
    if not result.get("success"):
        # A bad format or a missing optional package is the caller's to fix.
        raise HTTPException(status.HTTP_400_BAD_REQUEST, result.get("error", "generation failed"))
    # The absolute path is an implementation detail of this server.
    result.pop("path", None)
    return result


@router.get("")
async def index(limit: int = Query(default=100, ge=1, le=500)) -> dict[str, Any]:
    documents = list_generated_documents(limit=limit)
    return {"documents": documents, "total": len(documents)}


def _resolve(name: str) -> Path:
    """The file behind a download name, or a 404.

    Resolved before the containment check, so a symlink or a traversal cannot
    point somewhere else and still pass.
    """
    directory = generated_dir().resolve()
    target = (directory / Path(name).name).resolve()
    if not str(target).startswith(str(directory) + "/") or not target.is_file():
        raise HTTPException(status.HTTP_404_NOT_FOUND, f"no generated document named '{name}'")
    return target


@router.get("/{name}")
async def download(name: str) -> FileResponse:
    target = _resolve(name)
    suffix = target.suffix.lower()
    return FileResponse(
        target,
        media_type=_MIME.get(suffix, "application/octet-stream"),
        filename=target.name,
        content_disposition_type="inline" if suffix in _INLINE else "attachment",
    )


@router.delete("/{name}", status_code=status.HTTP_204_NO_CONTENT)
async def remove(name: str) -> None:
    _resolve(name)
    if not delete_generated_document(name):
        raise HTTPException(status.HTTP_404_NOT_FOUND, f"no generated document named '{name}'")
