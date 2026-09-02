import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from knowledge_storm.async_core.models import ArticleDraft, FactPool, Outline, OutlineSection, claim_jaccard, claim_similarity
from knowledge_storm.async_core.exporter import MultiFormatExporter
from knowledge_storm.async_core.deep_exploration import DynamicExplorationTree
from knowledge_storm.async_core.reviewer import AcademicReviewer
from knowledge_storm.async_core.seminar import (
    append_seminar,
    load_seminar_log,
    utterances_for_event,
)


def test_seminar_roles():
    open_u = utterances_for_event("SESSION_OPEN", {"topic": "测试课题", "task_id": "storm_abcd1234"})
    assert open_u[0].kind == "host"
    assert "测试课题" in open_u[0].text

    disc = utterances_for_event(
        "DISCOVERY_COMPLETE",
        {"personas": [{"name": "工艺专家", "description": "看配方"}]},
    )
    assert disc[0].kind == "host"
    assert disc[1].kind == "expert"
    assert disc[1].name == "工艺专家"

    done = utterances_for_event("COMPLETED", {"article_len": 12})
    assert done[0].kind == "host"
    assert utterances_for_event("DONE", {}) == []


def test_seminar_jsonl_roundtrip():
    root = Path(tempfile.mkdtemp())
    path = root / "storm_ab12cd34" / "seminar.jsonl"
    items = utterances_for_event("CURATION_START", {})
    append_seminar(path, items)
    loaded = load_seminar_log(path)
    assert loaded[0]["name"] == "主持人"
    assert loaded[0]["text"]


def test_no_dummy_facts_or_fake_gain():
    tree = DynamicExplorationTree(llm=None)
    gain, facts = tree._parse_gain_and_facts("completely unusable output", fallback_topic="尼古丁袋")
    assert gain == 0.0
    assert facts == []
    gain, facts = tree._parse_gain_and_facts("[GAIN]: 0.62\n[FACTS]:\n- 这是一条足够长的可核验事实陈述")
    assert abs(gain - 0.62) < 1e-6
    assert facts and "可核验" in facts[0]


def test_review_json_fail_does_not_pass():
    class _LLM:
        async def generate(self, **_kwargs):
            return "not-json-at-all"

    import asyncio
    draft = ArticleDraft(
        topic="测试",
        outline=Outline(topic="测试", sections=[OutlineSection(level=1, title="引言")]),
        content="## 引言\n正文。",
    )
    report = asyncio.run(AcademicReviewer(llm=_LLM()).review_article(draft))
    assert report.is_passed is False
    assert report.overall_score == 0


def test_near_dup_facts():
    assert claim_jaccard("尼古丁袋是口含烟替代品", "尼古丁袋是口含烟替代品。") > 0.9
    assert claim_similarity("尼古丁袋是口含烟替代品", "尼古丁袋是一种口含烟替代品") >= 0.86
    pool = FactPool()
    a = pool.add_fact("尼古丁袋是口含烟替代品", "https://a.example/1", "A")
    b = pool.add_fact("尼古丁袋是一种口含烟替代品", "https://a.example/2", "B")
    c = pool.add_fact("欧洲口含烟市场规模持续扩大且监管趋严", "https://a.example/3", "C")
    assert a is not None and c is not None
    assert b is a
    assert len(pool.facts) == 2


def test_html_export_branded_offline():
    draft = ArticleDraft(
        topic="本地大模型部署",
        outline=Outline(topic="本地大模型部署", sections=[OutlineSection(level=1, title="引言")]),
        content="# 本地大模型部署\n\n引言段落 [1]。\n\n```mermaid\nflowchart TD\n  A-->B\n```\n",
        citations={1: {"title": "示例", "url": "https://example.com"}},
    )
    html_doc = MultiFormatExporter().generate_standalone_html_report(draft)
    assert "溯知" in html_doc
    assert "溯流求源，知汇成章" in html_doc
    assert "鹿溪联合创新实验室" in html_doc
    assert "jsdelivr" not in html_doc
    assert "cdn." not in html_doc
    assert "diagram-source" in html_doc
    slides = MultiFormatExporter().generate_marp_slides_markdown(draft)
    assert "溯知 · SuZhi" in slides
    assert "jsdelivr" not in slides


def main():
    test_seminar_roles()
    test_seminar_jsonl_roundtrip()
    test_no_dummy_facts_or_fake_gain()
    test_review_json_fail_does_not_pass()
    test_near_dup_facts()
    test_html_export_branded_offline()
    print("ALL SEMINAR AND EXPORT TESTS PASSED")


if __name__ == "__main__":
    main()
