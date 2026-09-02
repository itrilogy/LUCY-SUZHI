"""研讨现场对白：阶段事件 → 角色台词，并按场次落盘 JSONL。"""

from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional

from .models import SeminarUtterance

HOST_COLOR = "#F1C40F"
REVIEWER_COLOR = "#E8A33D"
SCRIBE_COLOR = "#7CDBA5"
EXPERT_COLORS = ("#00D2FF", "#7CDBA5", "#82A0C4", "#4FC3C7", "#E8A33D", "#9ad8c4")

_SEQ = 0


def _next_ts() -> str:
    global _SEQ
    _SEQ += 1
    return f"{time.time():.6f}-{_SEQ:06d}"


def expert_color(name: str) -> str:
    if not name:
        return EXPERT_COLORS[0]
    return EXPERT_COLORS[sum(ord(c) for c in name) % len(EXPERT_COLORS)]


def _u(kind: str, name: str, role: str, text: str, color: str) -> SeminarUtterance:
    return SeminarUtterance(
        kind=kind, name=name, role_label=role, text=text, color=color, ts=_next_ts()
    )


def host(text: str) -> SeminarUtterance:
    return _u("host", "主持人", "调度", text, HOST_COLOR)


def expert(name: str, text: str) -> SeminarUtterance:
    who = name or "视角"
    return _u("expert", who, "视角", text, expert_color(who))


def reviewer(text: str) -> SeminarUtterance:
    return _u("reviewer", "审稿人", "红蓝对抗", text, REVIEWER_COLOR)


def scribe(text: str) -> SeminarUtterance:
    return _u("scribe", "书记员", "成章", text, SCRIBE_COLOR)


def utterances_for_event(stage: str, data: Optional[Dict[str, Any]] = None) -> List[SeminarUtterance]:
    data = data or {}
    last_expert = data.get("perspective") or ""

    if stage == "SESSION_OPEN":
        topic = data.get("topic") or "本课题"
        if data.get("resumed"):
            return [host(f"从断点继续讨论「{topic}」。场次 {data.get('task_id') or ''}。")]
        return [host(f"我们开始讨论课题「{topic}」。请各位稍后入座。")]

    if stage == "PRIOR_KNOWLEDGE":
        return [host(f"从本地知识库冷启动带入 {data.get('count') or 0} 条旧课题事实。")]

    if stage == "DISCOVERY_START":
        return [host("先请几位视角嘉宾入座。我去对一下各自的专长。")]

    if stage == "DISCOVERY_COMPLETE":
        personas = data.get("personas") or []
        out = []
        if personas:
            out.append(host(f"请来 {len(personas)} 位嘉宾。请各位先自报家门。"))
            for p in personas:
                name = p.get("name") if isinstance(p, dict) else getattr(p, "name", "")
                desc = p.get("description") if isinstance(p, dict) else getattr(p, "description", "")
                if name:
                    out.append(expert(name, desc or "从本视角跟进这一课题。"))
        else:
            out.append(host("视角名单还没拟好，我用默认席位继续。"))
        return out

    if stage == "CURATION_START":
        return [host("进入策展。请各位带着问题去找证据，有分歧就摊在桌上。")]

    if stage == "DEEP_RESEARCH_TREE_ACTIVE":
        return [host("这一场走深度探索树：增益不够就停，够了再往下问。")]

    if stage == "DEEP_EXPLORATION_NODE_START":
        if last_expert:
            return [expert(last_expert, f"我从第 {data.get('depth', '?')} 层追问：{data.get('query') or '继续检索。'}")]
        return [host(f"下钻一层（深度 {data.get('depth')}）：{data.get('query') or ''}")]

    if stage == "SEARCH_ISSUED":
        return [host(f"检索发出：「{data.get('query') or ''}」")]

    if stage == "SEARCH_HITS":
        samples = data.get("samples") or []
        titles = "；".join(s.get("title", "") for s in samples if isinstance(s, dict) and s.get("title"))
        if titles:
            return [host(f"这一轮命中 {data.get('count', len(samples))} 篇。例如：{titles}")]
        return []

    if stage == "FACTS_EXTRACTED":
        facts = "；".join(x for x in (data.get("facts") or []) if x)
        gain = float(data.get("gain_score") or 0)
        line = f"我记下这些事实（增益 {gain:.2f}）：{facts or '这一轮没有新的可靠陈述。'}"
        who = last_expert or data.get("perspective")
        return [expert(who, line) if who else host(line)]

    if stage == "DECISION_BRANCH":
        qs = "；".join(data.get("derived_queries") or []) or "派生问题待拟。"
        return [host(f"增益 {float(data.get('gain') or 0):.2f}，还值得往下问：{qs}")]

    if stage == "DECISION_SATURATE":
        return [host(f"{data.get('reason') or '这一支先到此。'}（增益 {float(data.get('gain') or 0):.2f}）")]

    if stage == "CURATION_COMPLETE":
        return [host(f"策展告一段落，事实池里现有 {data.get('fact_count', 0)} 条。下面请书记员排大纲。")]

    if stage == "OUTLINE_START":
        return [scribe("我来把刚才的证据收成章节骨架。")]

    if stage == "OUTLINE_COMPLETE":
        titles = data.get("section_titles") or []
        if titles:
            return [scribe(f"大纲 {len(titles)} 章：{' → '.join(titles)}")]
        return [scribe("大纲已经立住。")]

    if stage == "WRITING_START":
        return [host("请书记员按章起草。图谱若有口径冲突，一并写进对照。")]

    if stage == "FACT_GRAPH_EXTRACTING":
        return [host("正在核对跨信源关系与分歧。")]

    if stage == "FACT_GRAPH_COMPLETE":
        out = [host(f"图谱抽出 {data.get('triples_count') or 0} 条关系，口径差异 {data.get('conflicts_count') or 0} 处。")]
        samples = data.get("sample_triples") or []
        if samples:
            out.append(host(f"例如：{'；'.join(samples)}"))
        return out

    if stage == "SECTION_WRITING_START":
        return [scribe(f"正在写《{data.get('section') or '未名章节'}》。")]

    if stage == "SECTION_WRITTEN":
        extra = "，附机制图" if data.get("has_diagram") else ""
        return [scribe(f"《{data.get('section') or '未名章节'}》初稿 {data.get('char_count') or 0} 字{extra}。")]

    if stage == "WRITING_COMPLETE":
        return [scribe(f"初稿合成，约 {data.get('article_len') or 0} 字。请审稿人过目。")]

    if stage == "REVIEW_START":
        return [reviewer("我按学术规范做红蓝对抗：引用、断言、结构，一处一处看。")]

    if stage == "REVIEW_COMPLETE":
        passed = data.get("passed")
        out = [reviewer(f"综合 {data.get('score')} / 100。{'这一稿可以过。' if passed else '还不到线，我建议局部修订。'}")]
        tips = data.get("suggestions") or []
        if tips:
            out.append(reviewer(f"意见：{'；'.join(tips)}"))
        return out

    if stage == "REFLEXION_ACTIVE":
        return [reviewer("按刚才的意见打补丁，只动有问题的段落。")]

    if stage == "REFLEXION_PATCH_APPLIED":
        return [scribe(f"补丁已打上，正文现约 {data.get('new_len') or 0} 字。")]

    if stage == "POLISH_START":
        return [host("最后对标题与排版收一遍，准备成章。")]

    if stage == "COMPLETED":
        return [host("本场结束。右侧是成稿，引用仍可回溯到各位刚才举过的证据。")]
    if stage == "DONE":
        return []

    if stage == "STOPPED":
        return [host(data.get("message") or "这一场先停在这里。可在任务列表里续开。")]

    if stage == "ERROR":
        return [host(f"这一场出了差错：{data.get('error') or '未知错误'}")]

    return []


def seminar_path(output_root: Path, task_id: str) -> Path:
    return Path(output_root) / task_id / "seminar.jsonl"


def append_seminar(path: Path, items: Iterable[SeminarUtterance]) -> List[SeminarUtterance]:
    rows = list(items)
    if not rows:
        return []
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as fh:
        for u in rows:
            fh.write(u.model_dump_json(ensure_ascii=False) + "\n")
    return rows


def load_seminar_log(path: Path, limit: int = 4000) -> List[dict]:
    if not path.is_file():
        return []
    lines = path.read_text(encoding="utf-8").splitlines()
    out: List[dict] = []
    for line in lines[-limit:]:
        line = line.strip()
        if not line:
            continue
        try:
            out.append(json.loads(line))
        except json.JSONDecodeError:
            continue
    return out
