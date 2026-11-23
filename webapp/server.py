"""
Codex Cartographer web app — upload code and/or a research paper.

Run locally:
  uvicorn webapp.server:app --host 0.0.0.0 --port 7860
"""

from __future__ import annotations

import json
import os
import shutil
import tempfile
import uuid
import zipfile
from pathlib import Path
from urllib.parse import quote

from fastapi import FastAPI, File, Form, HTTPException, UploadFile
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles

from codex_cartographer.ingestion.walker import SUPPORTED_EXTENSIONS
from codex_cartographer.pipeline import MappingError, map_project

ROOT = Path(__file__).resolve().parents[1]
STATIC = Path(__file__).resolve().parent / "static"
SAMPLES = ROOT / "samples" / "todo_cli"
WORK = Path(os.environ.get("CODEX_WORK_DIR", tempfile.gettempdir())) / "codex_cartographer_jobs"
WORK.mkdir(parents=True, exist_ok=True)

MAX_ZIP_BYTES = int(os.environ.get("CODEX_MAX_ZIP_MB", "25")) * 1024 * 1024
MAX_FILE_BYTES = int(os.environ.get("CODEX_MAX_FILE_MB", "5")) * 1024 * 1024
MAX_PAPER_BYTES = 20 * 1024 * 1024
MAX_FILES = int(os.environ.get("CODEX_MAX_FILES", "400"))
MAX_STEPS = int(os.environ.get("CODEX_MAX_STEPS", "800"))

CODE_EXTS = set(SUPPORTED_EXTENSIONS.keys()) | {".zip"}

app = FastAPI(
    title="Codex Cartographer",
    description="Interactive atlas of how a codebase works — upload code and/or a paper.",
    version="0.1.0",
)
app.mount("/static", StaticFiles(directory=str(STATIC)), name="static")


def _has_upload(upload: UploadFile | None) -> bool:
    return bool(upload is not None and upload.filename and upload.filename.strip())


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
                continue
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


def _write_summary(job: Path, payload: dict) -> None:
    (job / "summary.json").write_text(json.dumps(payload, indent=2), encoding="utf-8")


def _paper_session_url(job_id: str, *, title: str, filename: str) -> str:
    return (
        f"/paper-session?job={quote(job_id)}"
        f"&name={quote(title)}"
        f"&file={quote(filename)}"
    )


@app.get("/", response_class=HTMLResponse)
def landing() -> HTMLResponse:
    return HTMLResponse((STATIC / "index.html").read_text(encoding="utf-8"))


@app.get("/paper-session", response_class=HTMLResponse)
def paper_session_page() -> HTMLResponse:
    return HTMLResponse((STATIC / "paper_session.html").read_text(encoding="utf-8"))


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
    code_zip: UploadFile | None = File(None),
    code_file: UploadFile | None = File(None),
    paper_pdf: UploadFile | None = File(None),
    project_name: str = Form(""),
) -> RedirectResponse:
    """
    Accept any non-empty combination of:
    - code zip
    - single source file
    - research paper PDF
    """
    has_zip = _has_upload(code_zip)
    has_file = _has_upload(code_file)
    has_paper = _has_upload(paper_pdf)

    if not (has_zip or has_file or has_paper):
        raise HTTPException(
            status_code=400,
            detail="Upload a code zip, a source file, a research paper PDF, or any combination of these.",
        )

    job_id = uuid.uuid4().hex[:12]
    job = _job_dir(job_id)
    label = project_name.strip()

    paper_note = None
    paper_name = None
    if has_paper:
        assert paper_pdf is not None and paper_pdf.filename
        if not paper_pdf.filename.lower().endswith(".pdf"):
            raise HTTPException(status_code=400, detail="Paper must be a PDF.")
        pdf_bytes = await paper_pdf.read()
        if len(pdf_bytes) > MAX_PAPER_BYTES:
            raise HTTPException(status_code=400, detail="Paper PDF exceeds 20 MB.")
        (job / "paper.pdf").write_bytes(pdf_bytes)
        paper_name = Path(paper_pdf.filename).name
        paper_title = label or Path(paper_name).stem
        paper_note = (
            f"Uploaded paper `{paper_name}`"
            + (f" for “{paper_title}”." if paper_title else ".")
            + f" Available at /jobs/{job_id}/paper."
        )

    has_code = has_zip or has_file
    if not has_code:
        # Paper-only session
        _write_summary(
            job,
            {
                "job_id": job_id,
                "project_name": label,
                "mode": "paper_only",
                "has_paper": True,
                "paper_name": paper_name,
            },
        )
        return RedirectResponse(
            url=_paper_session_url(
                job_id,
                title=label or Path(paper_name or "paper").stem,
                filename=paper_name or "paper.pdf",
            ),
            status_code=303,
        )

    src_root = job / "src"
    src_root.mkdir(parents=True, exist_ok=True)

    if has_zip:
        assert code_zip is not None and code_zip.filename
        name = code_zip.filename.lower()
        raw = await code_zip.read()
        if name.endswith(".zip"):
            if len(raw) > MAX_ZIP_BYTES:
                raise HTTPException(
                    status_code=400,
                    detail=f"Zip exceeds {MAX_ZIP_BYTES // (1024 * 1024)} MB limit.",
                )
            zip_path = job / "upload.zip"
            zip_path.write_bytes(raw)
            try:
                _safe_extract(zip_path, src_root)
            except MappingError as exc:
                raise HTTPException(status_code=400, detail=str(exc)) from exc
            except zipfile.BadZipFile as exc:
                raise HTTPException(status_code=400, detail="Invalid zip file.") from exc
        else:
            # Some browsers send a source file through the zip field.
            ext = Path(code_zip.filename).suffix.lower()
            if ext not in SUPPORTED_EXTENSIONS:
                raise HTTPException(
                    status_code=400,
                    detail="Code upload must be a .zip or a supported source file.",
                )
            if len(raw) > MAX_FILE_BYTES:
                raise HTTPException(status_code=400, detail="Source file exceeds 5 MB limit.")
            (src_root / Path(code_zip.filename).name).write_bytes(raw)

    if has_file:
        assert code_file is not None and code_file.filename
        ext = Path(code_file.filename).suffix.lower()
        fname = Path(code_file.filename).name
        raw = await code_file.read()
        if ext == ".zip":
            if len(raw) > MAX_ZIP_BYTES:
                raise HTTPException(
                    status_code=400,
                    detail=f"Zip exceeds {MAX_ZIP_BYTES // (1024 * 1024)} MB limit.",
                )
            zip_path = job / "upload_file.zip"
            zip_path.write_bytes(raw)
            try:
                _safe_extract(zip_path, src_root)
            except MappingError as exc:
                raise HTTPException(status_code=400, detail=str(exc)) from exc
            except zipfile.BadZipFile as exc:
                raise HTTPException(status_code=400, detail="Invalid zip file.") from exc
        else:
            if ext not in SUPPORTED_EXTENSIONS:
                raise HTTPException(
                    status_code=400,
                    detail=(
                        f"Unsupported source type `{ext or '(none)'}`. "
                        "Use a supported language file or a .zip."
                    ),
                )
            if len(raw) > MAX_FILE_BYTES:
                raise HTTPException(status_code=400, detail="Source file exceeds 5 MB limit.")
            (src_root / fname).write_bytes(raw)

    children = [p for p in src_root.iterdir() if not p.name.startswith(".")]
    if not children:
        raise HTTPException(status_code=400, detail="No usable source files found in the upload.")
    map_root = children[0] if len(children) == 1 and children[0].is_dir() else src_root

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

    _write_summary(
        job,
        {
            "job_id": job_id,
            "project_name": label,
            "mode": "code_and_paper" if has_paper else "code_only",
            "files": summary["files"],
            "languages": summary["languages"],
            "nodes": summary["nodes"],
            "edges": summary["edges"],
            "steps": summary["steps"],
            "roles": summary["roles"],
            "has_paper": has_paper,
            "paper_name": paper_name,
        },
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
    accept = _request.headers.get("accept", "")
    if "text/html" in accept:
        body = f"""<!DOCTYPE html><html><head><meta charset="utf-8"><title>Error</title>
        <link rel="stylesheet" href="/static/landing.css"></head><body class="err-page">
        <main><h1>Could not process that upload</h1><p>{exc.detail}</p>
        <p><a href="/">← Back to Codex Cartographer</a></p></main></body></html>"""
        return HTMLResponse(body, status_code=exc.status_code)
    return JSONResponse({"detail": exc.detail}, status_code=exc.status_code)
