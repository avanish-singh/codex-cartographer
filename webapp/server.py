"""
Codex Cartographer web app — upload a project and open the interactive atlas.

Run locally:
  uvicorn webapp.server:app --host 0.0.0.0 --port 7860
"""

from __future__ import annotations

import os
import shutil
import tempfile
import uuid
import zipfile
from pathlib import Path

from fastapi import FastAPI, File, Form, HTTPException, UploadFile
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles

from codex_cartographer.pipeline import MappingError, map_project

ROOT = Path(__file__).resolve().parents[1]
STATIC = Path(__file__).resolve().parent / "static"
SAMPLES = ROOT / "samples" / "todo_cli"
WORK = Path(os.environ.get("CODEX_WORK_DIR", tempfile.gettempdir())) / "codex_cartographer_jobs"
WORK.mkdir(parents=True, exist_ok=True)

MAX_ZIP_BYTES = int(os.environ.get("CODEX_MAX_ZIP_MB", "25")) * 1024 * 1024
MAX_FILES = int(os.environ.get("CODEX_MAX_FILES", "400"))
MAX_STEPS = int(os.environ.get("CODEX_MAX_STEPS", "800"))

app = FastAPI(
    title="Codex Cartographer",
    description="Interactive atlas of how a codebase works — upload code and explore.",
    version="0.1.0",
)
app.mount("/static", StaticFiles(directory=str(STATIC)), name="static")


def _safe_extract(zip_path: Path, dest: Path) -> int:
    """Extract a zip, blocking path traversal. Returns number of files written."""
    count = 0
    with zipfile.ZipFile(zip_path, "r") as zf:
        names = zf.namelist()
        if len(names) > MAX_FILES * 3:
            raise MappingError(f"Zip has too many entries (limit ~{MAX_FILES} source files).")
        for info in zf.infolist():
            if info.is_dir():
                continue
            name = info.filename.replace("\\", "/")
            if name.startswith("/") or ".." in Path(name).parts:
                raise MappingError(f"Refusing unsafe zip path: {info.filename}")
            if info.file_size > 2_000_000:
                continue  # skip huge blobs inside the archive
            target = (dest / name).resolve()
            if not str(target).startswith(str(dest.resolve())):
                raise MappingError(f"Refusing unsafe zip path: {info.filename}")
            target.parent.mkdir(parents=True, exist_ok=True)
            with zf.open(info) as src, open(target, "wb") as out:
                shutil.copyfileobj(src, out)
            count += 1
            if count > MAX_FILES * 5:
                raise MappingError("Zip too large after extraction.")
    return count


def _job_dir(job_id: str) -> Path:
    d = WORK / job_id
    d.mkdir(parents=True, exist_ok=True)
    return d


@app.get("/", response_class=HTMLResponse)
def landing() -> HTMLResponse:
    return HTMLResponse((STATIC / "index.html").read_text(encoding="utf-8"))


@app.get("/health")
def health() -> dict:
    return {"ok": True, "service": "codex-cartographer"}


def _run_demo_job() -> str:
    """Map the built-in sample; return job id."""
    job_id = uuid.uuid4().hex[:12]
    job = _job_dir(job_id)
    try:
        map_project(
            SAMPLES,
            output_html=job / "atlas.html",
            max_steps=MAX_STEPS,
            paper_note="Demo run on the bundled samples/todo_cli project.",
        )
    except MappingError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=500, detail=f"Mapping failed: {exc}") from exc
    return job_id


@app.api_route("/api/demo", methods=["GET", "POST"])
def run_demo() -> RedirectResponse:
    """Map the built-in sample without requiring an upload."""
    return RedirectResponse(url=f"/jobs/{_run_demo_job()}/atlas", status_code=303)


@app.post("/api/map")
async def map_upload(
    code_zip: UploadFile = File(..., description="Zip archive of the project source"),
    paper_pdf: UploadFile | None = File(None, description="Optional research paper PDF"),
    project_name: str = Form(""),
) -> RedirectResponse:
    if not code_zip.filename or not code_zip.filename.lower().endswith(".zip"):
        raise HTTPException(status_code=400, detail="Please upload a .zip of your source code.")

    job_id = uuid.uuid4().hex[:12]
    job = _job_dir(job_id)
    src_root = job / "src"
    src_root.mkdir(parents=True, exist_ok=True)
    zip_path = job / "upload.zip"

    raw = await code_zip.read()
    if len(raw) > MAX_ZIP_BYTES:
        raise HTTPException(
            status_code=400,
            detail=f"Zip exceeds {MAX_ZIP_BYTES // (1024 * 1024)} MB limit. Try a smaller folder.",
        )
    zip_path.write_bytes(raw)

    try:
        _safe_extract(zip_path, src_root)
    except MappingError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except zipfile.BadZipFile as exc:
        raise HTTPException(status_code=400, detail="Invalid zip file.") from exc

    # If the zip contained a single top-level folder, map that folder.
    children = [p for p in src_root.iterdir() if not p.name.startswith(".")]
    map_root = children[0] if len(children) == 1 and children[0].is_dir() else src_root

    paper_note = None
    if paper_pdf and paper_pdf.filename:
        if not paper_pdf.filename.lower().endswith(".pdf"):
            raise HTTPException(status_code=400, detail="Paper must be a PDF.")
        pdf_bytes = await paper_pdf.read()
        if len(pdf_bytes) > 20 * 1024 * 1024:
            raise HTTPException(status_code=400, detail="Paper PDF exceeds 20 MB.")
        paper_path = job / "paper.pdf"
        paper_path.write_bytes(pdf_bytes)
        label = project_name.strip() or Path(paper_pdf.filename).stem
        paper_note = (
            f"Visitor uploaded paper `{paper_pdf.filename}`"
            + (f" for project “{label}”." if label else ".")
            + " Open `/jobs/{}/paper` to download it alongside the atlas.".format(job_id)
        )

    try:
        summary = map_project(
            map_root,
            output_html=job / "atlas.html",
            max_steps=MAX_STEPS,
            paper_note=paper_note,
        )
    except MappingError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=500, detail=f"Mapping failed: {exc}") from exc

    (job / "summary.json").write_text(
        __import__("json").dumps(
            {
                "job_id": job_id,
                "project_name": project_name,
                "files": summary["files"],
                "languages": summary["languages"],
                "nodes": summary["nodes"],
                "edges": summary["edges"],
                "steps": summary["steps"],
                "roles": summary["roles"],
                "has_paper": bool(paper_note),
            },
            indent=2,
        ),
        encoding="utf-8",
    )
    return RedirectResponse(url=f"/jobs/{job_id}/atlas", status_code=303)


@app.get("/jobs/{job_id}/atlas")
def get_atlas(job_id: str):
    path = _job_dir(job_id) / "atlas.html"
    if not path.exists():
        raise HTTPException(status_code=404, detail="Atlas not found or expired.")
    return FileResponse(path, media_type="text/html")


@app.get("/jobs/{job_id}/paper")
def get_paper(job_id: str):
    path = _job_dir(job_id) / "paper.pdf"
    if not path.exists():
        raise HTTPException(status_code=404, detail="No paper was uploaded for this job.")
    return FileResponse(path, media_type="application/pdf", filename="paper.pdf")


@app.get("/jobs/{job_id}/summary")
def get_summary(job_id: str):
    path = _job_dir(job_id) / "summary.json"
    if not path.exists():
        raise HTTPException(status_code=404, detail="Summary not found.")
    return FileResponse(path, media_type="application/json")


@app.exception_handler(HTTPException)
async def http_error_handler(_request, exc: HTTPException):
    # Friendly HTML for browser form posts
    accept = _request.headers.get("accept", "")
    if "text/html" in accept:
        body = f"""<!DOCTYPE html><html><head><meta charset="utf-8"><title>Error</title>
        <link rel="stylesheet" href="/static/landing.css"></head><body class="err-page">
        <main><h1>Could not map that upload</h1><p>{exc.detail}</p>
        <p><a href="/">← Back to Codex Cartographer</a></p></main></body></html>"""
        return HTMLResponse(body, status_code=exc.status_code)
    return JSONResponse({"detail": exc.detail}, status_code=exc.status_code)
