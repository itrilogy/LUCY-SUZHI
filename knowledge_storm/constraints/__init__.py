"""
约束规则系统 — 约束即代码 (Constraint as Code)

对标 Paper-Arts V4.2 的 rule_GB_Layout.md / rule_Tobacco_Norms.md / rule_TRIZ_Innovation.md。

设计：
  - ConstraintRule: 抽象基类，每个规则一个 check() 方法
  - ConstraintRegistry: 规则注册表，从 YAML/TOML 或代码加载规则
  - ConstraintViolation: 约束违规结果
  - 内置规则: 引用格式、事实锚定、风格一致、长度限制
  - 自定义规则: 用户可通过 YAML 或 Python 子类扩展
"""

import json
import logging
import os
import re
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Dict, List, Literal, Optional, Type

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# 核心类型
# ---------------------------------------------------------------------------

Severity = Literal["error", "warning", "info"]


@dataclass
class ConstraintViolation:
    """单次约束违规记录。"""
    rule_name: str
    severity: Severity
    location: str
    message: str
    fix_suggestion: str = ""
    evidence: str = ""


# ---------------------------------------------------------------------------
# 抽象基类
# ---------------------------------------------------------------------------

class ConstraintRule(ABC):
    """约束规则的抽象基类。所有约束必须继承此类并实现 check()。"""

    name: str = "unnamed_rule"
    description: str = ""
    severity: Severity = "error"

    @abstractmethod
    def check(self, article, fact_pool=None, **kwargs) -> List[ConstraintViolation]:
        """执行约束检查。

        Args:
            article: StormArticle 实例
            fact_pool: 可选的 FactPool
            **kwargs: 额外参数

        Returns:
            约束违规列表。空列表 = 通过。
        """
        ...


# ---------------------------------------------------------------------------
# 内置规则 1: CitationFormatRule — 引用格式约束
# ---------------------------------------------------------------------------

class CitationFormatRule(ConstraintRule):
    """检查引用格式是否符合标准。

    对标 Paper-Arts rule_GB_Layout.md 的"参考文献生成约束"。
    """

    name = "citation_format"
    description = "Citation format compliance check"
    severity = "error"

    def __init__(self, max_authors: int = 3):
        self.max_authors = max_authors
        self._ref_pattern = re.compile(r'\[(\d+(?:,\s*\d+)*)\]')

    def check(self, article, fact_pool=None, **kwargs) -> List[ConstraintViolation]:
        violations = []
        refs = getattr(article, "reference", None)
        if not refs:
            return violations

        # 检查引用编号是否连续
        used_indices = set()
        for child in article.root.children:
            if child.content:
                for match in self._ref_pattern.finditer(child.content):
                    for num_str in match.group(1).split(","):
                        try:
                            used_indices.add(int(num_str.strip()))
                        except ValueError:
                            pass

        if not used_indices:
            return violations

        max_used = max(used_indices)
        if max_used > len(refs.get("url_to_unified_index", {})):
            violations.append(ConstraintViolation(
                rule_name=self.name,
                severity="error",
                location="article (global)",
                message=f"Citation index [{max_used}] exceeds available references ({len(refs.get('url_to_unified_index', {}))})",
                fix_suggestion="Check for orphaned citations or missing reference entries",
            ))

        # 检查引用编号是否有间隔
        expected = set(range(1, max_used + 1))
        missing = expected - used_indices
        if missing:
            violations.append(ConstraintViolation(
                rule_name=self.name,
                severity="warning",
                location="article (global)",
                message=f"Non-contiguous citation indices: missing {sorted(missing)}",
                fix_suggestion="Re-number references consecutively",
            ))

        return violations


# ---------------------------------------------------------------------------
# 内置规则 2: FactAnchoringRule — 事实锚定约束
# ---------------------------------------------------------------------------

class FactAnchoringRule(ConstraintRule):
    """
    检查所有数值断言是否锚定到 FactPool。

    对标 Paper-Arts 的"反幻觉红线"。
    """

    name = "fact_anchoring"
    description = "All numeric claims must be anchored to FactPool"
    severity = "error"

    def __init__(self, anchor_threshold: float = 0.45):
        self.anchor_threshold = anchor_threshold

    def check(self, article, fact_pool=None, **kwargs) -> List[ConstraintViolation]:
        violations = []
        if fact_pool is None:
            violations.append(ConstraintViolation(
                rule_name=self.name,
                severity="warning",
                location="article (global)",
                message="FactPool not provided; skipping fact-anchoring check",
                fix_suggestion="Provide a FactPool to enable fact-anchoring checks",
            ))
            return violations

        # 使用审计模块的 FactAnchorChecker
        try:
            from ..storm_wiki.modules.audit import FactAnchorChecker
            checker = FactAnchorChecker(similarity_threshold=self.anchor_threshold)
            for child in article.root.children:
                if child.content:
                    issues, _, _ = checker.check_section(
                        child.section_name, child.content, fact_pool
                    )
                    for iss in issues:
                        violations.append(ConstraintViolation(
                            rule_name=self.name,
                            severity="error" if iss.severity == "major" else "warning",
                            location=iss.location,
                            message=iss.description,
                            fix_suggestion=iss.fix_suggestion,
                        ))
        except ImportError:
            violations.append(ConstraintViolation(
                rule_name=self.name,
                severity="warning",
                location="article (global)",
                message="FactAnchorChecker not available; skipping check",
            ))

        return violations


# ---------------------------------------------------------------------------
# 内置规则 3: StyleConsistencyRule — 风格一致性
# ---------------------------------------------------------------------------

class StyleConsistencyRule(ConstraintRule):
    """
    检查文章的风格一致性。

    对标 Paper-Arts rule_GB_Layout.md 的"行文基调与张力"部分。
    """

    name = "style_consistency"
    description = "Style consistency across sections"
    severity = "warning"

    def __init__(self):
        self._first_person_pattern = re.compile(
            r'\b(I|we|my|our|me|us)\b', re.IGNORECASE
        )

    def check(self, article, fact_pool=None, **kwargs) -> List[ConstraintViolation]:
        violations = []

        # 检查第一人称使用
        for child in article.root.children:
            if child.content:
                matches = self._first_person_pattern.findall(child.content)
                if matches and child.section_name.lower() not in ("summary", "abstract"):
                    violations.append(ConstraintViolation(
                        rule_name=self.name,
                        severity="warning",
                        location=child.section_name,
                        message=f"First-person pronouns found ({len(matches)} instances): {', '.join(set(matches))}",
                        fix_suggestion="Use third-person or passive voice for encyclopedia tone",
                    ))

        return violations


# ---------------------------------------------------------------------------
# 内置规则 4: LengthBoundsRule — 长度约束
# ---------------------------------------------------------------------------

class LengthBoundsRule(ConstraintRule):
    """
    检查各 section 的长度是否在合理范围内。

    对标 Paper-Arts rule_GB_Layout.md 的"字数限制"（300 字摘要等）。
    """

    name = "length_bounds"
    description = "Section length bounds"
    severity = "warning"

    def __init__(self, max_section_words: int = 1500, min_section_words: int = 50):
        self.max_section_words = max_section_words
        self.min_section_words = min_section_words

    def check(self, article, fact_pool=None, **kwargs) -> List[ConstraintViolation]:
        violations = []

        for child in article.root.children:
            if child.content:
                word_count = len(child.content.split())
                if word_count > self.max_section_words:
                    violations.append(ConstraintViolation(
                        rule_name=self.name,
                        severity="warning",
                        location=child.section_name,
                        message=f"Section too long ({word_count} words, max={self.max_section_words})",
                        fix_suggestion=f"Consider splitting into subsections or condensing",
                    ))
                elif word_count < self.min_section_words:
                    violations.append(ConstraintViolation(
                        rule_name=self.name,
                        severity="warning",
                        location=child.section_name,
                        message=f"Section too short ({word_count} words, min={self.min_section_words})",
                        fix_suggestion=f"Expand with more details",
                    ))

        return violations


# ---------------------------------------------------------------------------
# ConstraintRegistry — 约束注册表
# ---------------------------------------------------------------------------

class ConstraintRegistry:
    """
    约束规则注册表。

    支持:
      - 通过代码注册内置规则
      - 通过 YAML 配置文件加载规则
      - 从自定义目录加载 Python 规则文件
    """

    def __init__(self):
        self._rules: Dict[str, ConstraintRule] = {}

    # -----------------------------------------------------------------------
    # 注册规则
    # -----------------------------------------------------------------------

    def register(self, rule: ConstraintRule):
        """注册一个规则。"""
        if rule.name in self._rules:
            logger.warning(f"Overwriting existing rule: {rule.name}")
        self._rules[rule.name] = rule
        logger.info(f"Registered constraint rule: {rule.name} ({rule.severity})")

    def register_all(self, rules: List[ConstraintRule]):
        """批量注册。"""
        for rule in rules:
            self.register(rule)

    def unregister(self, name: str):
        """注销一个规则。"""
        self._rules.pop(name, None)

    def get_rule(self, name: str) -> Optional[ConstraintRule]:
        return self._rules.get(name)

    def get_rules_by_severity(self, severity: Severity) -> List[ConstraintRule]:
        return [r for r in self._rules.values() if r.severity == severity]

    def list_rules(self) -> List[Dict]:
        """返回所有规则的摘要。"""
        return [
            {"name": r.name, "description": r.description, "severity": r.severity}
            for r in self._rules.values()
        ]

    # -----------------------------------------------------------------------
    # 执行检查
    # -----------------------------------------------------------------------

    def check_all(self, article, fact_pool=None, **kwargs) -> List[ConstraintViolation]:
        """执行所有注册的规则。"""
        all_violations = []
        for rule in self._rules.values():
            try:
                violations = rule.check(article, fact_pool=fact_pool, **kwargs)
                all_violations.extend(violations)
            except Exception as e:
                logger.error(f"Rule '{rule.name}' failed: {e}")
                all_violations.append(ConstraintViolation(
                    rule_name=rule.name,
                    severity="error",
                    location="system",
                    message=f"Rule execution error: {e}",
                ))
        return all_violations

    def check_by_name(self, name: str, article, fact_pool=None, **kwargs) -> List[ConstraintViolation]:
        """按名称执行单个规则。"""
        rule = self._rules.get(name)
        if rule is None:
            raise KeyError(f"Rule not found: {name}")
        return rule.check(article, fact_pool=fact_pool, **kwargs)

    def check_by_severity(self, severity: Severity, article, fact_pool=None, **kwargs) -> List[ConstraintViolation]:
        """按严重级别执行规则。"""
        violations = []
        for rule in self.get_rules_by_severity(severity):
            try:
                violations.extend(rule.check(article, fact_pool=fact_pool, **kwargs))
            except Exception as e:
                logger.error(f"Rule '{rule.name}' failed: {e}")
        return violations

    # -----------------------------------------------------------------------
    # 从 YAML 加载
    # -----------------------------------------------------------------------

    @classmethod
    def from_yaml(cls, yaml_path: str) -> "ConstraintRegistry":
        """
        从 YAML 配置文件加载约束规则。

        YAML 格式示例:
            rules:
              - name: "no_first_person"
                description: "禁止第一人称表达"
                severity: error
                pattern: "(我(们|认为|发现|提出)|we (believe|propose|think))"
                applies_to: ["body"]

              - name: "citation_density"
                description: "每个正文段落至少包含 1 条引用"
                severity: warning
                check_type: "semantic"
                threshold: 0.8

              - name: "fact_anchoring"
                description: "所有数值断言必须在 FactPool 中有锚定"
                severity: error
                check_type: "fact_pool_lookup"
        """
        import yaml

        registry = cls()

        with open(yaml_path, "r", encoding="utf-8") as f:
            config = yaml.safe_load(f)

        for rule_def in config.get("rules", []):
            name = rule_def.get("name", "unnamed")
            check_type = rule_def.get("check_type", "pattern")

            if check_type == "pattern":
                rule = _PatternRule.from_config(rule_def)
            elif check_type == "semantic":
                rule = _SemanticRule.from_config(rule_def)
            elif check_type == "fact_pool_lookup":
                rule = _FactPoolLookupRule.from_config(rule_def)
            else:
                logger.warning(f"Unknown check_type '{check_type}' for rule '{name}', skipping")
                continue

            registry.register(rule)

        return registry


# ---------------------------------------------------------------------------
# YAML 驱动的自定义规则（内部实现）
# ---------------------------------------------------------------------------

class _PatternRule(ConstraintRule):
    """由 YAML 中 check_type=pattern 生成的规则，使用正则匹配。"""

    def __init__(self, name: str, description: str, severity: Severity,
                 pattern: str, applies_to: Optional[List[str]] = None):
        self.name = name
        self.description = description
        self.severity = severity
        self._compiled = re.compile(pattern, re.IGNORECASE)
        self._applies_to = applies_to or ["body"]

    @classmethod
    def from_config(cls, config: dict) -> "_PatternRule":
        return cls(
            name=config["name"],
            description=config.get("description", ""),
            severity=config.get("severity", "warning"),
            pattern=config["pattern"],
            applies_to=config.get("applies_to"),
        )

    def check(self, article, fact_pool=None, **kwargs) -> List[ConstraintViolation]:
        violations = []
        for child in article.root.children:
            if child.content:
                matches = self._compiled.findall(child.content)
                if matches:
                    violations.append(ConstraintViolation(
                        rule_name=self.name,
                        severity=self.severity,
                        location=child.section_name,
                        message=f"Found {len(matches)} match(es): {self.description}",
                        evidence=f"Matches: {', '.join(m[:50] for m in matches[:3])}",
                    ))
        return violations


class _SemanticRule(ConstraintRule):
    """由 YAML 中 check_type=semantic 生成的规则（占位，需扩展）。"""

    def __init__(self, name: str, description: str, severity: Severity,
                 threshold: float = 0.8, **kwargs):
        self.name = name
        self.description = description
        self.severity = severity
        self.threshold = threshold

    @classmethod
    def from_config(cls, config: dict) -> "_SemanticRule":
        return cls(
            name=config["name"],
            description=config.get("description", ""),
            severity=config.get("severity", "warning"),
            threshold=config.get("threshold", 0.8),
        )

    def check(self, article, fact_pool=None, **kwargs) -> List[ConstraintViolation]:
        # 占位实现：需要特定语义逻辑
        return []


class _FactPoolLookupRule(ConstraintRule):
    """由 YAML 中 check_type=fact_pool_lookup 生成的规则。"""

    def __init__(self, name: str, description: str, severity: Severity, **kwargs):
        self.name = name
        self.description = description
        self.severity = severity

    @classmethod
    def from_config(cls, config: dict) -> "_FactPoolLookupRule":
        return cls(
            name=config["name"],
            description=config.get("description", ""),
            severity=config.get("severity", "error"),
        )

    def check(self, article, fact_pool=None, **kwargs) -> List[ConstraintViolation]:
        if fact_pool is None:
            return [ConstraintViolation(
                rule_name=self.name,
                severity=self.severity,
                location="article (global)",
                message=self.description,
                fix_suggestion="Provide a FactPool to enable this check",
            )]
        # 使用 FactPool.anchor_rate 做锚定检查
        all_claims = []
        for child in article.root.children:
            if child.content:
                sentences = re.split(r'(?<=[.!?])\s+', child.content)
                for s in sentences:
                    if re.search(r'\d+', s) and len(s) > 20:
                        all_claims.append((child.section_name, s.strip()))

        violations = []
        for section_name, claim in all_claims:
            rate = fact_pool.anchor_rate([claim])
            if rate < 0.5:
                violations.append(ConstraintViolation(
                    rule_name=self.name,
                    severity=self.severity,
                    location=section_name,
                    message=f"Unanchored claim: {claim[:100]}",
                    fix_suggestion="Add a supporting citation for this claim",
                ))
        return violations


# ---------------------------------------------------------------------------
# 便利工厂
# ---------------------------------------------------------------------------

def default_registry() -> ConstraintRegistry:
    """创建包含所有内置规则的默认注册表。"""
    registry = ConstraintRegistry()
    registry.register_all([
        CitationFormatRule(),
        StyleConsistencyRule(),
        LengthBoundsRule(),
    ])
    return registry
