"""
STORM Async Core — SQLite WAL 状态机与断点续跑管理器
负责在全流程（DISCOVERY -> CURATION -> OUTLINE -> WRITING -> POLISH）持久化 Checkpoint，
确保长耗时研究任务在发生异常、超时或中断后可 100% 恢复。
"""

import json
import logging
import sqlite3
from datetime import datetime
from pathlib import Path
from typing import Optional, Dict, Any
from pydantic import BaseModel, Field

from .models import Persona, FactPool, Outline, DialogueTurn, ArticleDraft

logger = logging.getLogger(__name__)


class TaskCheckpoint(BaseModel):
    """任务全局状态快照"""
    task_id: str
    topic: str
    stage: str = Field(description="当前完成的阶段: INIT | DISCOVERY | CURATION | OUTLINE | WRITING | COMPLETED")
    personas: list[Persona] = Field(default_factory=list)
    dialogues: list[DialogueTurn] = Field(default_factory=list)
    fact_pool: FactPool = Field(default_factory=FactPool)
    outline: Optional[Outline] = None
    article_draft: Optional[ArticleDraft] = None
    tokens_used: int = 0
    updated_at: str = Field(default_factory=lambda: datetime.now().isoformat())


class WorkflowStateManager:
    """基于 SQLite WAL 模式的任务状态与断点续跑管理器。"""

    def __init__(self, db_path: Optional[str] = None):
        if db_path is None:
            db_dir = Path.home() / ".storm"
            db_dir.mkdir(parents=True, exist_ok=True)
            self.db_path = str(db_dir / "storm_workflow.db")
        else:
            self.db_path = db_path
            Path(self.db_path).parent.mkdir(parents=True, exist_ok=True)

        self._init_db()

    def _init_db(self):
        """初始化 SQLite WAL 数据库结构。"""
        with sqlite3.connect(self.db_path) as conn:
            conn.execute("PRAGMA journal_mode=WAL;")
            conn.execute("PRAGMA synchronous=NORMAL;")
            conn.execute("""
                CREATE TABLE IF NOT EXISTS storm_checkpoints (
                    task_id TEXT PRIMARY KEY,
                    topic TEXT,
                    stage TEXT,
                    data_json TEXT,
                    updated_at TEXT
                );
            """)
            conn.commit()

    def save_checkpoint(self, checkpoint: TaskCheckpoint):
        """保存或更新任务 Checkpoint。"""
        checkpoint.updated_at = datetime.now().isoformat()
        with sqlite3.connect(self.db_path) as conn:
            conn.execute(
                """
                INSERT OR REPLACE INTO storm_checkpoints (task_id, topic, stage, data_json, updated_at)
                VALUES (?, ?, ?, ?, ?);
                """,
                (
                    checkpoint.task_id,
                    checkpoint.topic,
                    checkpoint.stage,
                    checkpoint.model_dump_json(),
                    checkpoint.updated_at,
                ),
            )
            conn.commit()
        logger.debug(f"Checkpoint saved: task={checkpoint.task_id}, stage={checkpoint.stage}")

    def load_checkpoint(self, task_id: str) -> Optional[TaskCheckpoint]:
        """根据 task_id 加载 Checkpoint。"""
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.execute(
                "SELECT data_json FROM storm_checkpoints WHERE task_id = ?;", (task_id,)
            )
            row = cursor.fetchone()
            if row:
                return TaskCheckpoint.model_validate_json(row[0])
        return None

    def find_latest_checkpoint_for_topic(self, topic: str) -> Optional[TaskCheckpoint]:
        """查找指定主题最新的未完成或已完成 Checkpoint。"""
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.execute(
                "SELECT data_json FROM storm_checkpoints WHERE topic = ? ORDER BY updated_at DESC LIMIT 1;",
                (topic,),
            )
            row = cursor.fetchone()
            if row:
                return TaskCheckpoint.model_validate_json(row[0])
        return None

    def list_checkpoints(self, limit: int = 50) -> list[dict]:
        """列出所有持久化的任务简要元信息（按更新时间倒序）。"""
        results = []
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.execute(
                "SELECT task_id, topic, stage, data_json, updated_at FROM storm_checkpoints ORDER BY updated_at DESC LIMIT ?;",
                (limit,),
            )
            for row in cursor.fetchall():
                t_id, topic, stage, data_raw, updated_at = row
                try:
                    data = json.loads(data_raw) if data_raw else {}
                except Exception:
                    data = {}
                fact_count = len(data.get("fact_pool", {}).get("facts", []))
                personas_count = len(data.get("personas", []))
                has_outline = bool(data.get("outline"))
                has_draft = bool(data.get("article_draft"))
                article_len = len(data.get("article_draft", {}).get("content", "")) if has_draft else 0

                results.append({
                    "task_id": t_id,
                    "topic": topic,
                    "stage": stage,
                    "personas_count": personas_count,
                    "fact_count": fact_count,
                    "has_outline": has_outline,
                    "has_draft": has_draft,
                    "article_len": article_len,
                    "updated_at": updated_at,
                })
        return results

    def delete_checkpoint(self, task_id: str) -> bool:
        """从 SQLite 中物理删除指定任务 Checkpoint。"""
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.execute("DELETE FROM storm_checkpoints WHERE task_id = ?;", (task_id,))
            conn.commit()
            return cursor.rowcount > 0
