"""
STORM Server — FastAPI + Server-Sent Events (SSE) 现代异步服务 (集成 ConfigHub 配置中心)
提供：
1. GET / — 托管现代响应式 Web 控制台
2. POST /api/v1/research/start — 启动深度研究任务
3. GET /api/v1/research/stream/{task_id} — SSE 实时流式事件总线
4. GET /api/v1/research/article/{task_id} — 获取任务生成成果
5. POST /api/v1/export/typst/{task_id} — 导出 Typst 论文格式
6. GET /api/v1/config/providers — 获取脱敏配置与 Provider 矩阵
7. POST /api/v1/config/probe — 异步探测端点健康度与拉取可用模型
8. POST /api/v1/config/save — 保存并热重载系统配置
"""

import asyncio
import json
import logging
import os
import sys
import uuid
from pathlib import Path
from typing import Dict, Any, Optional, List

from fastapi import FastAPI, BackgroundTasks, HTTPException, Query
from fastapi.responses import HTMLResponse, StreamingResponse, JSONResponse, FileResponse
from fastapi.staticfiles import StaticFiles
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field

# 注入项目根路径
ROOT_DIR = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT_DIR))

from knowledge_storm.async_core import (
    AsyncLLM,
    AsyncSearXNG,
    HybridRetriever,
    AsyncSTORMPipeline,
    WorkflowStateManager,
    TaskCheckpoint,
    ConfigHub,
    StormSystemConfig,
    probe_llm_endpoint,
    probe_search_endpoint,
)
from knowledge_storm.async_core.typst_compiler import TypstCompiler

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(name)s: %(message)s")
logger = logging.getLogger(__name__)

app = FastAPI(
    title="STORM Modern Deep Research API",
    version="2.1.0",
    description="Production-grade asynchronous knowledge curation and paper generation engine with ConfigHub.",
)

# 允许跨域
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# 静态资源与前端目录
STATIC_DIR = ROOT_DIR / "frontend" / "web"
STATIC_DIR.mkdir(parents=True, exist_ok=True)
app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")

# 全局状态
TASK_EVENT_QUEUES: Dict[str, asyncio.Queue] = {}
RUNNING_TASKS: Dict[str, asyncio.Task] = {}
state_manager = WorkflowStateManager()
config_hub = ConfigHub()


class ResearchStartRequest(BaseModel):
    topic: str = Field(..., min_length=2, description="研究主题")
    resume_task_id: Optional[str] = Field(None, description="需要断点恢复的 task_id")
    deep_research: bool = Field(True, description="是否启用动态递归探索树")
    max_depth: int = Field(2, ge=1, le=4, description="探索最大深度")
    turns: int = Field(3, ge=1, le=8, description="问答轮次")
    perspectives: int = Field(3, ge=1, le=6, description="专家视角数")
    local_docs_dir: Optional[str] = Field(None, description="挂载本地知识库目录路径")


class ProbeRequest(BaseModel):
    type: str = Field("llm", description="llm | search")
    base_url: str
    api_key: Optional[str] = ""


class SaveConfigRequest(BaseModel):
    active_llm_provider: str
    active_search_provider: str
    deep_research_default: bool = True
    max_depth: int = 2
    llm_providers: Dict[str, Any]
    search_providers: Dict[str, Any]


def get_runtime_components(local_docs_dir: Optional[str] = None):
    """从 ConfigHub 动态装配活跃的 LLM 与检索引擎。"""
    active_llm_info = config_hub.get_active_llm()
    active_search_info = config_hub.get_active_search()

    llm = AsyncLLM(
        model=active_llm_info.model,
        api_key=active_llm_info.api_key,
        api_base=active_llm_info.base_url,
        temperature=active_llm_info.temperature,
    )

    searx = AsyncSearXNG(
        api_url=active_search_info.api_url,
        api_key=active_search_info.api_key,
        engines_academic=active_search_info.engines_academic,
        engines_chinese=active_search_info.engines_chinese,
        engines_general=active_search_info.engines_general,
        max_concurrent=active_search_info.max_concurrent,
        timeout=active_search_info.timeout,
        enable_cache=active_search_info.enable_cache,
    )

    if local_docs_dir and Path(local_docs_dir).exists():
        retriever = HybridRetriever(web_retriever=searx, local_docs_dir=local_docs_dir)
    else:
        retriever = searx

    return llm, retriever


MAX_CONCURRENT_RESEARCH = 3

STAGE_PROGRESS_MAP = {
    "INIT": 0,
    "DISCOVERY_START": 5,
    "DISCOVERY_COMPLETE": 15,
    "CURATION_START": 20,
    "DEEP_RESEARCH_TREE_ACTIVE": 25,
    "DEEP_EXPLORATION_NODE_START": 35,
    "CURATION_COMPLETE": 50,
    "OUTLINE_START": 55,
    "OUTLINE_COMPLETE": 65,
    "WRITING_START": 70,
    "FACT_GRAPH_COMPLETE": 75,
    "SECTION_WRITTEN": 80,
    "WRITING_COMPLETE": 85,
    "REVIEW_START": 88,
    "REVIEW_COMPLETE": 92,
    "POLISH_START": 95,
    "COMPLETED": 100,
    "DONE": 100,
}


async def _run_research_job(task_id: str, req: ResearchStartRequest):
    """后台异步执行研究任务并推入 SSE 队列。"""
    queue = TASK_EVENT_QUEUES.setdefault(task_id, asyncio.Queue(maxsize=2000))
    llm, retriever = get_runtime_components(req.local_docs_dir)

    pipeline = AsyncSTORMPipeline(
        llm=llm,
        retriever=retriever,
        output_dir=str(ROOT_DIR / "results_async"),
        state_manager=state_manager,
        max_conv_turns=req.turns,
        max_perspectives=req.perspectives,
        deep_research=req.deep_research,
        max_depth=req.max_depth,
    )

    def _event_cb(stage: str, data: Any):
        progress = STAGE_PROGRESS_MAP.get(stage, None)
        payload = {
            "task_id": task_id,
            "stage": stage,
            "data": data,
            "tokens_used": llm.total_tokens_used,
            "progress_pct": progress,
        }
        try:
            queue.put_nowait(payload)
        except Exception:
            pass

    try:
        article = await pipeline.run(
            topic=req.topic,
            task_id=task_id,
            progress_callback=_event_cb,
        )
        queue.put_nowait({
            "task_id": task_id,
            "stage": "DONE",
            "progress_pct": 100,
            "tokens_used": llm.total_tokens_used,
            "data": {"article_len": len(article.content)},
        })
    except asyncio.CancelledError:
        logger.info(f"Task {task_id} cancelled by user.")
        queue.put_nowait({"task_id": task_id, "stage": "STOPPED", "data": {"message": "任务已手动终止"}})
    except Exception as e:
        logger.error(f"Task {task_id} failed: {e}", exc_info=True)
        queue.put_nowait({"task_id": task_id, "stage": "ERROR", "data": {"error": str(e)}})
    finally:
        RUNNING_TASKS.pop(task_id, None)
        await llm.close()
        if hasattr(retriever, "close"):
            await retriever.close()


@app.get("/", response_class=HTMLResponse)
async def serve_index():
    index_file = STATIC_DIR / "index.html"
    if index_file.exists():
        return HTMLResponse(
            content=index_file.read_text(encoding="utf-8"),
            headers={"Cache-Control": "no-cache, no-store, must-revalidate", "Pragma": "no-cache", "Expires": "0"}
        )
    return "<h1>STORM Web UI Initializing...</h1>"


# ── 任务管理 REST API ───────────────────────────────────────────────────

@app.get("/api/v1/tasks")
async def list_tasks(limit: int = Query(50, ge=1, le=100)):
    """获取所有历史与进行中的任务列表（按最近更新时间排序）。"""
    checkpoints = state_manager.list_checkpoints(limit=limit)
    running_set = {t_id for t_id, task in RUNNING_TASKS.items() if not task.done()}
    
    tasks_with_status = []
    for cp in checkpoints:
        t_id = cp["task_id"]
        is_running = t_id in running_set
        display_stage = "RUNNING" if is_running else cp["stage"]
        tasks_with_status.append({
            **cp,
            "is_running": is_running,
            "display_stage": display_stage,
        })
    return {"tasks": tasks_with_status, "total": len(tasks_with_status)}


@app.post("/api/v1/research/start")
async def start_research(req: ResearchStartRequest):
    # 限制并发运行任务上限
    active_running = [t for t in RUNNING_TASKS.values() if not t.done()]
    if len(active_running) >= MAX_CONCURRENT_RESEARCH:
        raise HTTPException(
            status_code=429,
            detail=f"当前已有 {len(active_running)} 个深度研究任务正在并发执行，已达到服务器安全上限 ({MAX_CONCURRENT_RESEARCH})。请等待其完成或手动终止后再发起。",
        )

    task_id = req.resume_task_id or f"storm_{uuid.uuid4().hex[:8]}"
    TASK_EVENT_QUEUES[task_id] = asyncio.Queue(maxsize=500)

    t = asyncio.create_task(_run_research_job(task_id, req))
    RUNNING_TASKS[task_id] = t

    return {
        "status": "started",
        "task_id": task_id,
        "topic": req.topic,
        "deep_research": req.deep_research,
    }


@app.post("/api/v1/research/stop/{task_id}")
async def stop_research(task_id: str):
    """手动中断指定的后台研究任务。"""
    t = RUNNING_TASKS.get(task_id)
    if t and not t.done():
        t.cancel()
        RUNNING_TASKS.pop(task_id, None)
        return {"status": "stopped", "task_id": task_id}
    return {"status": "not_running", "task_id": task_id}


@app.delete("/api/v1/tasks/{task_id}")
async def delete_task(task_id: str):
    """彻底物理清理指定任务的所有持久化快照、知识库索引、内存队列与磁盘成果。"""
    t = RUNNING_TASKS.get(task_id)
    if t and not t.done():
        t.cancel()
        RUNNING_TASKS.pop(task_id, None)

    TASK_EVENT_QUEUES.pop(task_id, None)
    deleted_cp = state_manager.delete_checkpoint(task_id)

    # 清理本地 SQLite 知识库索引
    from knowledge_storm.async_core.local_knowledge_hub import LocalKnowledgeHub
    kb_hub = LocalKnowledgeHub(db_path=ROOT_DIR / "results_async" / "local_knowledge.db")
    kb_hub.delete_task_records(task_id)

    # 物理清理磁盘结果目录
    task_dir = ROOT_DIR / "results_async" / task_id
    if task_dir.exists():
        import shutil
        shutil.rmtree(task_dir, ignore_errors=True)

    return {
        "status": "deleted",
        "task_id": task_id,
        "deleted_checkpoint": deleted_cp,
        "cleared_kb": True,
        "cleared_files": True,
    }


@app.get("/api/v1/research/stream/{task_id}")
async def stream_research_events(task_id: str):
    """建立或重连 SSE 实时事件流（支持已有状态快照重放）。"""
    queue = TASK_EVENT_QUEUES.get(task_id)
    cp = state_manager.load_checkpoint(task_id)

    async def event_generator():
        # 1. 如果存在已持久化的 Checkpoint，先回放状态快照给新连进来的客户端
        if cp:
            snapshot_event = {
                "task_id": task_id,
                "stage": "STAGE_SNAPSHOT",
                "data": {
                    "topic": cp.topic,
                    "stage": cp.stage,
                    "personas": [p.model_dump() for p in cp.personas],
                    "fact_count": len(cp.fact_pool.facts) if cp.fact_pool else 0,
                    "has_outline": bool(cp.outline),
                    "has_draft": bool(cp.article_draft),
                    "updated_at": cp.updated_at,
                }
            }
            yield f"data: {json.dumps(snapshot_event, ensure_ascii=False)}\n\n"

        # 2. 如果任务已在后台执行结束，补发 DONE 事件后退出
        is_running = task_id in RUNNING_TASKS and not RUNNING_TASKS[task_id].done()
        if not is_running and cp and cp.stage in ("COMPLETED", "DONE"):
            done_event = {
                "task_id": task_id,
                "stage": "DONE",
                "data": {
                    "article_len": len(cp.article_draft.content) if cp.article_draft else 0
                }
            }
            yield f"data: {json.dumps(done_event, ensure_ascii=False)}\n\n"
            return

        # 3. 若任务正在执行中，从队列流式消费新事件
        if not queue:
            return

        while True:
            try:
                event = await asyncio.wait_for(queue.get(), timeout=45.0)
                yield f"data: {json.dumps(event, ensure_ascii=False)}\n\n"
                if event.get("stage") in ("DONE", "ERROR", "STOPPED"):
                    break
            except asyncio.TimeoutError:
                yield ": heartbeat\n\n"

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "Connection": "keep-alive", "X-Accel-Buffering": "no"},
    )


@app.get("/api/v1/research/article/{task_id}")
async def get_article(task_id: str):
    cp = state_manager.load_checkpoint(task_id)
    if not cp:
        raise HTTPException(status_code=404, detail="Task not found")

    task_dir = ROOT_DIR / "results_async" / task_id
    article_path = task_dir / "article.md"
    content = article_path.read_text(encoding="utf-8") if article_path.exists() else (cp.article_draft.content if cp.article_draft else "")

    return {
        "task_id": task_id,
        "topic": cp.topic,
        "stage": cp.stage,
        "article": content,
        "citations": cp.fact_pool.get_citations_dict() if cp.fact_pool else {},
        "updated_at": cp.updated_at,
    }


@app.post("/api/v1/export/typst/{task_id}")
async def export_typst(task_id: str):
    cp = state_manager.load_checkpoint(task_id)
    if not cp or not cp.article_draft:
        raise HTTPException(status_code=404, detail="Article draft not available for this task")

    compiler = TypstCompiler()
    typst_code = compiler.generate_typst_source(cp.article_draft)
    out_dir = ROOT_DIR / "results_async" / task_id
    out_file = out_dir / "paper.typ"
    out_file.write_text(typst_code, encoding="utf-8")

    return {
        "status": "success",
        "file_path": str(out_file.absolute()),
        "download_url": f"/api/v1/download/{task_id}/paper.typ",
        "typst_source": typst_code,
    }


@app.post("/api/v1/export/slides/{task_id}")
async def export_slides(task_id: str):
    """导出 Marp 学术演示幻灯片。"""
    cp = state_manager.load_checkpoint(task_id)
    if not cp or not cp.article_draft:
        raise HTTPException(status_code=404, detail="Article draft not available for this task")

    from knowledge_storm.async_core.exporter import MultiFormatExporter
    exporter = MultiFormatExporter()
    slides_md = exporter.generate_marp_slides_markdown(cp.article_draft)
    out_dir = ROOT_DIR / "results_async" / task_id
    out_file = out_dir / "slides.marp.md"
    out_file.write_text(slides_md, encoding="utf-8")

    return {
        "status": "success",
        "file_path": str(out_file.absolute()),
        "download_url": f"/api/v1/download/{task_id}/slides.marp.md",
        "slides_markdown": slides_md,
    }


@app.post("/api/v1/export/html/{task_id}")
async def export_standalone_html(task_id: str):
    """导出独立印刷级 HTML 研报。"""
    cp = state_manager.load_checkpoint(task_id)
    if not cp or not cp.article_draft:
        raise HTTPException(status_code=404, detail="Article draft not available for this task")

    from knowledge_storm.async_core.exporter import MultiFormatExporter
    exporter = MultiFormatExporter()
    html_content = exporter.generate_standalone_html_report(cp.article_draft)
    out_dir = ROOT_DIR / "results_async" / task_id
    out_file = out_dir / "report_standalone.html"
    out_file.write_text(html_content, encoding="utf-8")

    return {
        "status": "success",
        "file_path": str(out_file.absolute()),
        "download_url": f"/api/v1/download/{task_id}/report_standalone.html",
        "html_content": html_content,
    }


@app.get("/api/v1/download/{task_id}/{filename}")
async def download_task_file(task_id: str, filename: str):
    """通用文件直接下载端点。"""
    allowed_files = [
        "paper.typ",
        "slides.marp.md",
        "report_standalone.html",
        "article.md",
        "outline.md",
        "fact_pool.json",
        "citations.json",
    ]
    if filename not in allowed_files:
        raise HTTPException(status_code=400, detail="Invalid filename requested")

    file_path = ROOT_DIR / "results_async" / task_id / filename
    if not file_path.exists():
        raise HTTPException(status_code=404, detail="Requested file not found on disk")

    return FileResponse(
        path=str(file_path),
        filename=f"{task_id}_{filename}",
        media_type="application/octet-stream",
    )


# ── 配置中心 API ───────────────────────────────────────────────────────

@app.get("/api/v1/config/providers")
async def get_config_providers():
    """获取脱敏后的当前全量配置与 Provider 矩阵。"""
    return config_hub.get_masked_config()


@app.post("/api/v1/config/probe")
async def probe_endpoint(req: ProbeRequest):
    """一键探测 LLM/检索端点并拉取可用模型与 RTT 延迟。"""
    if req.type == "llm":
        res = await probe_llm_endpoint(base_url=req.base_url, api_key=req.api_key or "")
    else:
        res = await probe_search_endpoint(api_url=req.base_url, api_key=req.api_key or "")
    return res


@app.post("/api/v1/config/save")
async def save_config(req: SaveConfigRequest):
    """保存并热重载系统配置。"""
    try:
        new_cfg = StormSystemConfig(**req.model_dump())
        config_hub.save_config(new_cfg)
        return {"status": "saved", "active_llm": new_cfg.active_llm_provider, "active_search": new_cfg.active_search_provider}
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))


@app.get("/api/v1/config/spam_stats")
async def get_spam_stats():
    """获取当前内容农场与垃圾站规则库统计。"""
    from knowledge_storm.async_core.retriever import _GLOBAL_SPAM_FILTER
    return {
        "total_rules": len(_GLOBAL_SPAM_FILTER.spam_domains),
        "local_file": str(_GLOBAL_SPAM_FILTER.local_file),
    }


@app.post("/api/v1/config/sync_spam_list")
async def sync_spam_blocklist():
    """一键异步同步云端开源内容农场与垃圾站 Blocklist 规则。"""
    from knowledge_storm.async_core.retriever import _GLOBAL_SPAM_FILTER
    res = await _GLOBAL_SPAM_FILTER.sync_remote_blocklists()
    return {"status": "success", "data": res}


def run_server(host: str = "0.0.0.0", port: int = 8000):
    import uvicorn
    uvicorn.run("server.app:app", host=host, port=port, reload=False, log_level="info")


if __name__ == "__main__":
    run_server()
