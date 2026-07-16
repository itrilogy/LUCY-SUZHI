"""
Callback 系统增强 — 可组合的观察者链 + 审计日志 + Token 追踪

对标 Paper-Arts V4.2 的质检回调 + 质量审计机制。

设计决策：
  1. CompositeCallbackHandler: 责任链模式，允许多个 handler 同时注册
  2. 新增 5 个 hook 点（facts / contradictions / sections / hallucinations），所有 hook 默认空实现
  3. AuditCallbackHandler: 将 hook 事件写入结构化 JSONL 审计日志
  4. UsageTrackerCallbackHandler: 细粒度 LM token + RM query 成本追踪

向后兼容：
  - BaseCallbackHandler 保留全部原有 hook 签名
  - 新增 hook 使用 **kwargs 确保子类无需强制实现
"""

import json
import logging
import os
import time
from collections import defaultdict
from dataclasses import dataclass, field, asdict
from datetime import datetime
from typing import Any, Callable, Dict, List, Optional

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# 基类增强 — 新增 5 个 hook 点
# ---------------------------------------------------------------------------

class BaseCallbackHandler:
    """Base callback handler that can be used to handle callbacks from the STORM pipeline."""

    def on_identify_perspective_start(self, **kwargs):
        """Run when the perspective identification starts."""
        pass

    def on_identify_perspective_end(self, perspectives: list[str], **kwargs):
        """Run when the perspective identification finishes."""
        pass

    def on_information_gathering_start(self, **kwargs):
        """Run when the information gathering starts."""
        pass

    def on_dialogue_turn_end(self, dlg_turn, **kwargs):
        """Run when a question asking and answering turn finishes."""
        pass

    def on_information_gathering_end(self, **kwargs):
        """Run when the information gathering finishes."""
        pass

    def on_information_organization_start(self, **kwargs):
        """Run when the information organization starts."""
        pass

    def on_direct_outline_generation_end(self, outline: str, **kwargs):
        """Run when the direct outline generation finishes."""
        pass

    def on_outline_refinement_end(self, outline: str, **kwargs):
        """Run when the outline refinement finishes."""
        pass

    # -----------------------------------------------------------------------
    # Phase 1.2: 新增 hook 点（保持向后兼容）
    # -----------------------------------------------------------------------

    def on_fact_extracted(self, fact, **kwargs):
        """Run when a fact is extracted from search results into FactPool."""
        pass

    def on_fact_contradiction_detected(self, fact_a, fact_b, **kwargs):
        """Run when a contradiction is detected between two facts."""
        pass

    def on_section_generation_start(self, section_name: str, **kwargs):
        """Run when a section generation starts."""
        pass

    def on_section_generation_end(self, section_name: str, content: str,
                                   cited_facts: Optional[List[int]] = None, **kwargs):
        """Run when a section generation finishes."""
        pass

    def on_hallucination_detected(self, claim: str, evidence_gap: str, **kwargs):
        """Run when a potential hallucination is detected."""
        pass


# ---------------------------------------------------------------------------
# CompositeCallbackHandler — 责任链模式
# ---------------------------------------------------------------------------

class CompositeCallbackHandler(BaseCallbackHandler):
    """
    允许多个 handler 同时注册的 Composite 模式实现。

    用法:
        handler = CompositeCallbackHandler([
            AuditCallbackHandler(log_dir="/tmp/storm_audit"),
            UsageTrackerCallbackHandler(),
        ])
        runner.run(topic="...", callback_handler=handler)
    """

    def __init__(self, handlers: List[BaseCallbackHandler]):
        self.handlers = handlers

    def _dispatch(self, method_name: str, *args, **kwargs):
        for h in self.handlers:
            method = getattr(h, method_name, None)
            if method is not None:
                try:
                    method(*args, **kwargs)
                except Exception as e:
                    logger.warning(f"Callback handler {type(h).__name__}.{method_name} failed: {e}")

    def on_identify_perspective_start(self, **kwargs):
        self._dispatch("on_identify_perspective_start", **kwargs)

    def on_identify_perspective_end(self, perspectives: list[str], **kwargs):
        self._dispatch("on_identify_perspective_end", perspectives=perspectives, **kwargs)

    def on_information_gathering_start(self, **kwargs):
        self._dispatch("on_information_gathering_start", **kwargs)

    def on_dialogue_turn_end(self, dlg_turn, **kwargs):
        self._dispatch("on_dialogue_turn_end", dlg_turn=dlg_turn, **kwargs)

    def on_information_gathering_end(self, **kwargs):
        self._dispatch("on_information_gathering_end", **kwargs)

    def on_information_organization_start(self, **kwargs):
        self._dispatch("on_information_organization_start", **kwargs)

    def on_direct_outline_generation_end(self, outline: str, **kwargs):
        self._dispatch("on_direct_outline_generation_end", outline=outline, **kwargs)

    def on_outline_refinement_end(self, outline: str, **kwargs):
        self._dispatch("on_outline_refinement_end", outline=outline, **kwargs)

    def on_fact_extracted(self, fact, **kwargs):
        self._dispatch("on_fact_extracted", fact=fact, **kwargs)

    def on_fact_contradiction_detected(self, fact_a, fact_b, **kwargs):
        self._dispatch("on_fact_contradiction_detected", fact_a=fact_a, fact_b=fact_b, **kwargs)

    def on_section_generation_start(self, section_name: str, **kwargs):
        self._dispatch("on_section_generation_start", section_name=section_name, **kwargs)

    def on_section_generation_end(self, section_name: str, content: str,
                                   cited_facts: Optional[List[int]] = None, **kwargs):
        self._dispatch("on_section_generation_end",
                        section_name=section_name, content=content,
                        cited_facts=cited_facts, **kwargs)

    def on_hallucination_detected(self, claim: str, evidence_gap: str, **kwargs):
        self._dispatch("on_hallucination_detected", claim=claim, evidence_gap=evidence_gap, **kwargs)


# ---------------------------------------------------------------------------
# AuditCallbackHandler — 结构化审计日志
# ---------------------------------------------------------------------------

class AuditCallbackHandler(BaseCallbackHandler):
    """
    将所有 callback 事件写入结构化 JSONL 审计日志。

    每个事件写入一行 JSON，包含:
      - event: 事件名称
      - timestamp: ISO 时间戳
      - data: 事件负载（可序列化部分）
    """

    def __init__(self, log_dir: str = "./storm_audit"):
        self.log_dir = log_dir
        os.makedirs(log_dir, exist_ok=True)
        self._log_file = os.path.join(
            log_dir, f"audit_{datetime.now().strftime('%Y%m%d_%H%M%S')}.jsonl"
        )
        self._event_count = 0

    def _log_event(self, event: str, data: Dict):
        self._event_count += 1
        record = {
            "event": event,
            "timestamp": datetime.now().isoformat(),
            "sequence": self._event_count,
            "data": data,
        }
        with open(self._log_file, "a", encoding="utf-8") as f:
            f.write(json.dumps(record, ensure_ascii=False, default=str) + "\n")

    def on_identify_perspective_start(self, **kwargs):
        self._log_event("identify_perspective_start", {})

    def on_identify_perspective_end(self, perspectives: list[str], **kwargs):
        self._log_event("identify_perspective_end", {"perspectives": perspectives})

    def on_information_gathering_start(self, **kwargs):
        self._log_event("information_gathering_start", {})

    def on_dialogue_turn_end(self, dlg_turn, **kwargs):
        # 仅记录对话轮次的元数据，不记录完整内容以避免日志膨胀
        turn_info = {
            "has_agent_utterance": bool(dlg_turn.agent_utterance),
            "has_user_utterance": bool(dlg_turn.user_utterance),
            "search_queries": dlg_turn.search_queries,
            "num_search_results": len(dlg_turn.search_results) if dlg_turn.search_results else 0,
        }
        self._log_event("dialogue_turn_end", turn_info)

    def on_information_gathering_end(self, **kwargs):
        self._log_event("information_gathering_end", {})

    def on_information_organization_start(self, **kwargs):
        self._log_event("information_organization_start", {})

    def on_direct_outline_generation_end(self, outline: str, **kwargs):
        self._log_event("direct_outline_generation_end", {"outline_length": len(outline)})

    def on_outline_refinement_end(self, outline: str, **kwargs):
        self._log_event("outline_refinement_end", {"outline_length": len(outline)})

    def on_fact_extracted(self, fact, **kwargs):
        self._log_event("fact_extracted", {
            "fact_id": fact.fact_id,
            "confidence": fact.confidence,
            "source_url": fact.source_url[:120] if fact.source_url else "",
            "content_preview": fact.content[:100],
        })

    def on_fact_contradiction_detected(self, fact_a, fact_b, **kwargs):
        self._log_event("fact_contradiction_detected", {
            "fact_a_id": fact_a.fact_id,
            "fact_b_id": fact_b.fact_id,
            "fact_a_preview": fact_a.content[:80],
            "fact_b_preview": fact_b.content[:80],
        })

    def on_section_generation_start(self, section_name: str, **kwargs):
        self._log_event("section_generation_start", {"section_name": section_name})

    def on_section_generation_end(self, section_name: str, content: str,
                                   cited_facts: Optional[List[int]] = None, **kwargs):
        self._log_event("section_generation_end", {
            "section_name": section_name,
            "content_length": len(content),
            "cited_facts": cited_facts or [],
        })

    def on_hallucination_detected(self, claim: str, evidence_gap: str, **kwargs):
        self._log_event("hallucination_detected", {
            "claim": claim[:200],
            "evidence_gap": evidence_gap[:200],
        })

    def summary(self) -> Dict:
        """返回审计日志的统计摘要。"""
        event_counts = defaultdict(int)
        total_size = 0
        if os.path.exists(self._log_file):
            total_size = os.path.getsize(self._log_file)
            with open(self._log_file, "r", encoding="utf-8") as f:
                for line in f:
                    try:
                        record = json.loads(line)
                        event_counts[record.get("event", "unknown")] += 1
                    except json.JSONDecodeError:
                        pass
        return {
            "log_file": self._log_file,
            "total_events": self._event_count,
            "log_size_bytes": total_size,
            "event_counts": dict(event_counts),
        }


# ---------------------------------------------------------------------------
# UsageTrackerCallbackHandler — Token + Query 成本追踪
# ---------------------------------------------------------------------------

class UsageTrackerCallbackHandler(BaseCallbackHandler):
    """
    细粒度 LM token + RM query 成本追踪。

    在每个 hook 点记录当前的 lm_configs 使用量快照，
    生成时间线式的成本分布数据。
    """

    def __init__(self):
        self.events: List[Dict] = []
        self._start_time = time.time()

    def _snapshot(self, event: str, lm_configs=None, **kwargs):
        entry = {
            "event": event,
            "elapsed_seconds": round(time.time() - self._start_time, 2),
            "timestamp": datetime.now().isoformat(),
        }
        if lm_configs:
            try:
                entry["lm_usage"] = lm_configs.collect_and_reset_lm_usage()
            except Exception:
                pass
        self.events.append(entry)

    def on_identify_perspective_start(self, **kwargs):
        self._snapshot("identify_perspective_start", **kwargs)

    def on_identify_perspective_end(self, **kwargs):
        self._snapshot("identify_perspective_end", **kwargs)

    def on_information_gathering_start(self, **kwargs):
        self._snapshot("information_gathering_start", **kwargs)

    def on_dialogue_turn_end(self, **kwargs):
        self._snapshot("dialogue_turn_end", **kwargs)

    def on_information_gathering_end(self, **kwargs):
        self._snapshot("information_gathering_end", **kwargs)

    def on_section_generation_start(self, **kwargs):
        self._snapshot("section_generation_start", **kwargs)

    def on_section_generation_end(self, **kwargs):
        self._snapshot("section_generation_end", **kwargs)

    def summary(self) -> Dict:
        """返回成本追踪统计。"""
        total_prompt = 0
        total_completion = 0
        lm_models = set()
        for ev in self.events:
            usage = ev.get("lm_usage", {})
            if usage:
                for model, tokens in usage.items():
                    lm_models.add(model)
                    total_prompt += tokens.get("prompt_tokens", 0)
                    total_completion += tokens.get("completion_tokens", 0)

        return {
            "total_events_logged": len(self.events),
            "lm_models_used": list(lm_models),
            "total_prompt_tokens": total_prompt,
            "total_completion_tokens": total_completion,
            "total_tokens": total_prompt + total_completion,
            "elapsed_seconds": round(time.time() - self._start_time, 2),
        }
