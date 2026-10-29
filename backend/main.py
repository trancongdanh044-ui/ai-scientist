import json
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import BackgroundTasks, FastAPI, HTTPException
from fastapi.responses import Response
from fastapi.staticfiles import StaticFiles
from sse_starlette.sse import EventSourceResponse

from backend.db import db
from backend.run_manager import RunManager
from backend.schemas import RunRequest, RunResponse, RunStatus
from src.config import load_config

manager = RunManager()
cfg = load_config("config.yaml")
FRONTEND_DIR = Path("frontend")
#
# @asynccontextmanager
# async def lifespan(app: FastAPI):
#     # startup
#     await db.init_indexes()
#     yield
#     # shutdown
#     await db.close()

app = FastAPI(title="AI Scientist Web")

# Loại nội dung nên hiển thị TRỰC TIẾP trên trình duyệt (preview) thay vì luôn tải xuống
_INLINE_TYPES = {"application/pdf", "image/png", "image/jpeg", "text/plain", "application/x-tex"}

@app.on_event("startup")
async def startup_event():
  # Gọi hàm kiểm tra kết nối khi ứng dụng vừa khởi chạy
  connected = await db.test_connection()
  if not connected:
    print(
        "Cảnh báo: Không thể kết nối tới cơ sở dữ liệu khi khởi động ứng dụng!"
    )

  # Khởi tạo index nếu cần
  await db.init_indexes()


@app.on_event("shutdown")
async def shutdown_event():
  await db.close()

# ---------- Health ----------
@app.get("/api/health")
async def health():
    return {
        "status": "ok",
        "llm_model": cfg.llm.model,
        "llm_base_url": cfg.base_url,
    }


# ---------- Tạo run ----------
@app.post("/api/runs", response_model=RunResponse)
async def create_run(req: RunRequest, bg: BackgroundTasks):
    run = await manager.create_run(req.topic, req)
    bg.add_task(manager.execute, run, req, cfg)
    return RunResponse(run_id=run.run_id)


# ---------- Danh sách run ----------
@app.get("/api/runs")
async def list_runs(limit: int = 30):
    cursor = (
        db.runs.find({}, {"topic": 1, "status": 1, "progress": 1, "created_at": 1, "stage": 1, "compile_ok": 1})
        .sort("created_at", -1)
        .limit(limit)
    )
    items = []
    async for d in cursor:
        items.append({
            "run_id": d["_id"], "topic": d.get("topic"), "status": d.get("status"),
            "stage": d.get("stage"), "progress": d.get("progress", 0),
            "compile_ok": d.get("compile_ok"),
            "created_at": d["created_at"].isoformat() if d.get("created_at") else None,
        })
    return {"runs": items}


# ---------- Chi tiết run ----------
@app.get("/api/runs/{run_id}")
async def get_run_detail(run_id: str):
    run_doc = await db.runs.find_one({"_id": run_id})
    if not run_doc:
        raise HTTPException(404, "run not found")

    paper = await db.papers.find_one({"run_id": run_id})
    hyp = await db.hypotheses.find_one({"run_id": run_id})
    review = await db.reviews.find_one({"run_id": run_id})

    sections = []
    async for s in db.sections.find({"run_id": run_id}).sort("order", 1):
        sections.append({"name": s["name"], "order": s["order"], "content": s["content"]})

    return {
        "run_id": run_id,
        "topic": run_doc.get("topic"),
        "status": run_doc.get("status"),
        "stage": run_doc.get("stage"),
        "progress": run_doc.get("progress"),
        "error": run_doc.get("error"),
        "model": run_doc.get("model"),
        "num_papers": run_doc.get("num_papers"),
        "compile_ok": run_doc.get("compile_ok"),
        "compile_engine": run_doc.get("compile_engine"),
        "created_at": run_doc["created_at"].isoformat() if run_doc.get("created_at") else None,
        "literature": (
            {
                "papers": paper.get("papers", []),
                "summaries": paper.get("summaries"),
                "research_gap": paper.get("research_gap"),
                "comparison_rows": paper.get("comparison_rows", []),
            }
            if paper else None
        ),
        "hypotheses": hyp.get("content") if hyp else None,
        "eval_rows": hyp.get("eval_rows", []) if hyp else [],
        "sections": sections,
        "review": review.get("content") if review else None,
    }


# ---------- Trạng thái ----------
@app.get("/api/runs/{run_id}/status", response_model=RunStatus)
async def get_run_status(run_id: str):
    d = await db.runs.find_one({"_id": run_id})
    if not d:
        raise HTTPException(404, "run not found")
    return RunStatus(
        run_id=run_id, status=d.get("status", "unknown"), stage=d.get("stage", ""),
        progress=d.get("progress", 0), error=d.get("error"), output_dir=None,
        compile_ok=d.get("compile_ok"),
    )


# ---------- SSE ----------
@app.get("/api/runs/{run_id}/stream")
async def stream(run_id: str):
    run = manager.get(run_id)

    if not run:
        d = await db.runs.find_one({"_id": run_id})
        if not d:
            raise HTTPException(404, "run not found")

        async def replay():
            yield {"data": json.dumps({"type": "done", "run_id": run_id, "status": d.get("status")}, ensure_ascii=False)}

        return EventSourceResponse(replay())

    async def event_gen():
        async for ev in manager.stream(run_id):
            yield {"data": json.dumps(ev, ensure_ascii=False)}

    return EventSourceResponse(event_gen())


# ---------- Files ----------
@app.get("/api/runs/{run_id}/files")
async def list_files(run_id: str):
    cursor = db.files.find({"run_id": run_id}, {"name": 1, "size": 1, "content_type": 1, "_id": 0})
    files = []
    async for f in cursor:
        files.append({
            "name": f["name"], "size": f.get("size", 0), "type": f.get("content_type", "text/plain"),
            "url": f"/api/runs/{run_id}/files/{f['name']}",
        })
    return {"files": files}


@app.get("/api/runs/{run_id}/files/{name}")
async def download_file(run_id: str, name: str):
    doc = await db.files.find_one({"run_id": run_id, "name": name})
    if not doc:
        raise HTTPException(404, "file not found")

    content_type = doc.get("content_type", "application/octet-stream")
    disposition = "inline" if content_type in _INLINE_TYPES else "attachment"
    return Response(
        content=doc["content"],
        media_type=content_type,
        headers={"Content-Disposition": f'{disposition}; filename="{name}"'},
    )


app.mount("/", StaticFiles(directory=str(FRONTEND_DIR), html=True), name="static")
