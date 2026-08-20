"""File upload endpoints.

Uploads land in the uploads directory, which is also a context root, so a file
posted here is immediately visible to ``analyze_file``, ``analyze_image``, and
the whole context-tree family without any further wiring.

Validation happens in :mod:`src.tools.file_analysis` (extension allowlist, size
cap, filename sanitising), so the same rules apply whether a file arrives
through this router or any other caller.
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, File, HTTPException, Query, UploadFile, status
from fastapi.responses import FileResponse

from src.audit_logging import get_logger
from src.tools.audit_trail import append_audit_entry
from src.tools.file_analysis import (
    ALLOWED_SUFFIXES,
    MAX_UPLOAD_BYTES,
    analyze_file,
    analyze_image,
    delete_uploaded_file,
    save_uploaded_bytes,
    uploads_dir,
)

logger = get_logger(__name__)
router = APIRouter(prefix="/api/v1/files", tags=["files"])


@router.get("/limits")
async def upload_limits() -> dict[str, Any]:
    """What this server accepts, so the UI can validate before sending bytes."""
    return {
        "max_bytes": MAX_UPLOAD_BYTES,
        "allowed_extensions": sorted(ALLOWED_SUFFIXES),
    }


@router.post("", status_code=status.HTTP_201_CREATED)
async def upload_files(files: list[UploadFile] = File(...)) -> dict[str, Any]:
    """Upload one or more files for agents to analyse.

    Every file is attempted; the response reports per-file success so one bad
    file in a batch does not discard the rest.
    """
    if not files:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="No files supplied")

    saved: list[dict[str, Any]] = []
    rejected: list[dict[str, str]] = []

    for upload in files:
        name = upload.filename or "upload"
        try:
            payload = await upload.read()
            record = save_uploaded_bytes(name, payload)
        except ValueError as exc:
            rejected.append({"name": name, "reason": str(exc)})
            continue
        except Exception as exc:
            logger.error("file_upload_failed", filename=name, error=str(exc))
            rejected.append({"name": name, "reason": f"Could not store the file: {exc}"})
            continue
        finally:
            await upload.close()

        saved.append(record)
        try:
            append_audit_entry(
                action="file_uploaded",
                category="data_access",
                resource=f"file:{record['name']}",
                detail={"size_bytes": record["size_bytes"], "kind": record["kind"]},
            )
        except Exception:
            # An audit-store hiccup must not fail an otherwise good upload; the
            # structured log below still records it.
            logger.warning("file_upload_audit_failed", filename=record["name"])

    logger.info("files_uploaded", saved=len(saved), rejected=len(rejected))

    if not saved and rejected:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={"message": "No files were accepted", "rejected": rejected},
        )

    return {"uploaded": saved, "rejected": rejected, "count": len(saved)}


@router.get("")
async def list_files(
    pattern: str = Query("", description="Case-insensitive filename filter"),
    limit: int = Query(100, ge=1, le=500),
) -> dict[str, Any]:
    """List uploaded files, newest first."""
    directory = uploads_dir()
    from datetime import datetime, timezone

    from src.tools.context_tree import _human_size
    from src.tools.file_analysis import IMAGE_SUFFIXES

    try:
        candidates = sorted(
            (item for item in directory.iterdir() if item.is_file()),
            key=lambda item: item.stat().st_mtime,
            reverse=True,
        )
    except OSError as exc:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Uploads directory could not be read: {exc}",
        ) from exc

    entries = []
    for item in candidates:
        if pattern and pattern.lower() not in item.name.lower():
            continue
        if len(entries) >= limit:
            break
        stat = item.stat()
        entries.append(
            {
                "name": item.name,
                "size": _human_size(stat.st_size),
                "size_bytes": stat.st_size,
                "kind": "image" if item.suffix.lower() in IMAGE_SUFFIXES else "document",
                "uploaded": datetime.fromtimestamp(stat.st_mtime, timezone.utc).isoformat(),
            }
        )

    return {"count": len(entries), "files": entries}


def _resolve_upload(name: str):
    """Locate an upload by name, refusing anything that is not a direct child."""
    from pathlib import Path

    directory = uploads_dir()
    # Path(name).name discards every directory component, so "../../etc/passwd"
    # can only ever resolve to "passwd" inside the uploads directory.
    target = directory / Path(name).name
    if not target.exists() or not target.is_file():
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail=f"No uploaded file named '{name}'"
        )
    return target


@router.get("/{name}/content")
async def download_file(name: str) -> FileResponse:
    """Return the raw file — used by the Studio's preview pane."""
    target = _resolve_upload(name)
    return FileResponse(str(target), filename=target.name)


@router.get("/{name}/analysis")
async def analyse_file(
    name: str,
    question: str = Query("Describe this image in detail.", description="Vision prompt for images"),
    max_chars: int = Query(8000, ge=500, le=40000),
) -> dict[str, Any]:
    """Run the same analysis an agent would, and return it as JSON."""
    import json

    from src.tools.file_analysis import IMAGE_SUFFIXES

    target = _resolve_upload(name)
    if target.suffix.lower() in IMAGE_SUFFIXES:
        return json.loads(analyze_image(target.name, question))
    return json.loads(analyze_file(target.name, max_chars))


@router.delete("/{name}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_file(name: str) -> None:
    """Delete an uploaded file."""
    if not delete_uploaded_file(name):
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail=f"No uploaded file named '{name}'"
        )
    try:
        append_audit_entry(
            action="file_deleted",
            category="data_access",
            resource=f"file:{name}",
            severity="notice",
        )
    except Exception:
        logger.warning("file_delete_audit_failed", filename=name)
