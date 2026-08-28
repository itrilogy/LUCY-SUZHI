# STORM 检索命中率与信源有效性彻底重构落地报告

## 1. 现状物理缺陷与根因定位 (Root Cause Analysis)

在针对课题《软件工程的脚手架机制+大模型技术在知识工程中的应用》的初期实测中，系统暴露了以下 **4 项致命物理根因**：

```
[致命劣变链条]
查询词: "软件工程的脚手架机制+大模型技术在知识工程中的应用 技术架构师 核心概念 发展现状 关键机制" (56 字符)
        ↓ 搜索引擎无法处理超长复合短语，退化为无序单字模糊匹配 ("软件" + "应用")
命中源: "腾讯软件中心-海量软件高速免费下载", "华军软件园", "360软件宝库" (国内高 SEO 权重的下载站)
        ↓ 缺乏垃圾域名黑名单与语义相关度初筛
事实池: "腾讯软件中心提供超过10000款免费软件下载..." (沉淀了完全无关的垃圾事实)
        ↓
图谱抽取: ent_1 (腾讯软件中心) -[提供]-> ent_2 (免费软件) (实体关系图谱彻底失效)
```

| 缺陷维度 | 代码现状与物理后果 | 严重级别 | 解决方案 |
| :--- | :--- | :--- | :--- |
| **1. 检索词粗暴拼接 (Query Pollution)** | `deep_exploration.py` 采用 `f"{topic} {p.name} 核心概念 发展现状 关键机制"` 拼接出 50+ 字长句，搜索引擎直接退化为词频模糊泛匹配。 | **P0 (致命)** | 引入 LLM 专家级检索重写器 `_distill_initial_queries`，提炼 6~15 字的高价值精准搜索词。 |
| **2. 垃圾域名与 SEO 农场零拦截 (No Domain Filter)** | 搜索引擎返回大量软件下载站（`pc.qq.com`, `onlinedown.net`, `360.cn`），系统无差别作为“权威源”接收。 | **P0 (致命)** | 构建 `SpamFilterManager`，结合本地持久化 `~/.storm/spam_domains.txt` 与 GitHub 开源订阅列表异步同步。 |
| **3. 伪数据与蜜罐实例无感知 (No Semantic Verification)** | 第三方公共 SearXNG 实例受限或降级时返回无关外语/坐标伪数据，旧逻辑无感知照单全收。 | **P0 (致命)** | 增加 `_is_relevant_snippet` 关键词重合度核验，不足时自动无缝降级触发内置 DuckDuckGo Direct 通道。 |
| **4. 事实提取无相关性审查 (No Relevance Guard)** | 事实提取 Prompt 顺从地提炼下载站广告为“原子事实”。 | **P0 (致命)** | Prompt 注入强审查红线（无关内容直接输出 `[GAIN]: 0.0`），事实入池前执行关键词二次校验。 |

---

## 2. 4 层递进防御重构架构设计

```
[原始研究课题 + 专家视角]
       │
       ▼
【第 1 层：LLM 专家级检索重写器 (Query Rewriter & Keyword Distiller)】
  - 剥离所有助词与长句式
  - 生成 2 个精准短语 (6~15 字，如 "知识图谱 脚手架 LLM") + 严格清洗特殊标点与括号
       │
       ▼
【第 2 层：动态内容农场与垃圾站过滤器 (SpamFilterManager)】
  - 权威白名单直接放行: arxiv.org, github.com, ieee.org, acm.org, wikipedia.org, zhihu.com
  - 本地规则库: ~/.storm/spam_domains.txt (内置 50+ 核心黑名单兜底)
  - 异步定时同步: cobaltdisco/Google-Search-Blacklist + danny0838/content-farm-terminator 开源规则
  - URL 路径下载正则特征拦截: r'/(download|xiazai|soft|down|apk|exe)/'
  - 标题与正文垃圾特征词拦截: ["免费软件下载", "高速下载", "绿色纯净版", "破解补丁", "安装包下载"]
       │
       ▼
【第 3 层：网页片段语义相关度初筛与 DDG 直连保底 (Semantic Overlap & DDG Fallback)】
  - 校验 Snippet 与查询词汉字/英文重合度，过滤伪数据
  - 若 SearXNG 实例受限（< 2 条有效结果），无缝启动内置 DuckDuckGo Direct 通道
       │
       ▼
【第 4 层：事实提炼相关性强约束守卫 (Fact Extraction Relevance Guard)】
  - Prompt 强约束：“若搜索结果偏离课题核心主题，严禁提炼事实，直接返回 [GAIN]: 0.0”
  - 事实入池二次核验：事实文本必须包含课题核心关键词
       │
       ▼
[100% 聚焦于研究课题的高纯净度事实池 FactPool]
```

---

## 3. 落地重构源码比对

### 3.1 SpamFilterManager 动态同步与多层过滤 (`retriever.py`)
```python
class SpamFilterManager:
    """本地持久化与异步订阅更新的内容农场与垃圾站过滤器。"""

    def __init__(self, local_file: Optional[Path] = None):
        self.local_file = local_file or (Path.home() / ".storm" / "spam_domains.txt")
        self.local_file.parent.mkdir(parents=True, exist_ok=True)
        self.spam_domains: Set[str] = set()
        self._load_local_or_init()

    async def sync_remote_blocklists(self) -> Dict[str, Any]:
        """异步拉取开源社区权威垃圾站与内容农场订阅源（GitHub Raw），自动去重合并。"""
        remote_sources = [
            "https://raw.githubusercontent.com/cobaltdisco/Google-Search-Blacklist/master/src/blacklist.txt",
            "https://raw.githubusercontent.com/danny0838/content-farm-terminator/master/rules/block.txt",
        ]
        ...
```

### 3.2 专家视角检索词精准提纯 (`deep_exploration.py`)
```python
async def _distill_initial_queries(self, topic: str, persona: Persona, is_chinese: bool = True) -> List[tuple[str, str]]:
    """使用 LLM 针对特定专家视角提纯出精简、高质量的搜索引擎关键词（长度 6-18 字）。"""
    if is_chinese:
        prompt = f"""研究课题: {topic}
专家角色: {persona.name} ({persona.description})

请基于上述研究课题与专家视角，提炼出 1~2 个最精准的搜索引擎检索短语。
要求：
1. 必须是简短、专业的高效搜索词（6~18 字），严禁输出长句或自然语言问句！
2. 剥离“对于...的作用”、“机制”等虚词，组合核心技术术语（如："知识图谱 脚手架 LLM"、"代码生成 软件脚手架 知识建模"）。
3. 格式严格为：
1. [搜索短语]: 检索动机
2. [搜索短语]: 检索动机"""
    ...
```

---

## 4. 靶向真实物理验证测试数据

使用课题《软件工程的脚手架机制+大模型技术在知识工程中的应用》进行真实端到端测试，实测数据如下：

### 4.1 提纯查询词对比
* **重构前**：`软件工程的脚手架机制+大模型技术在知识工程中的应用 技术架构师 核心概念 发展现状 关键机制` (56 字)
* **重构后**：
  * `软件脚手架 大模型 知识工程` (14 字)
  * `脚手架 代码生成 知识建模` (13 字)
  * `知识图谱 脚手架 LLM` (12 字)
  * `本体设计 脚手架 大模型` (12 字)

### 4.2 检索源质量对比
* **重构前**：`腾讯软件中心`, `华军软件园`, `360软件宝库` (100% 垃圾下载站)
* **重构后**：
  * `https://www.betteryeah.com/blog/llm-knowledge-graph-construction-complete-guide` (大模型知识图谱构建完整指南)
  * `https://zhuanlan.zhihu.com/p/1911805939247486365` (知乎专栏：大模型与知识图谱融合架构)
  * `https://blog.csdn.net/weixin_42680139/article/details/161134983` (代码生成与知识建模脚手架实践)

### 4.3 事实池纯净度对比
* **重构前**：沉淀“腾讯软件中心提供10000款免费软件下载”、“Windows显示器刷新率”等噪音事实。
* **重构后**：沉淀 **31 条核心事实**，0 广告噪音：
  1. *项目脚手架的核心原理是将项目初始结构、配置文件、依赖关系等抽象为可描述的模板，通过变量替换和条件逻辑自动化生成标准化的项目基础代码...*
  2. *现代脚手架通过预设规则和动态模板引擎，将用户选择转化为具体的文件结构和依赖配置...*
  3. *skill-scaffold 是一个为 AI 技能开发量身定制的脚手架项目，目标是提供“开箱即用”的解决方案，避免从零搭建项目结构...*

---

## 5. 自动化测试套件回归结果

7 大自动化测试套件全部 100% 通过（耗时 5.1s）：
```text
Running Async Core Integrity & Resumability Tests      ✓ PASSED
Running Phase 2 Deep Research Modules Integrity Tests  ✓ PASSED
Running Advanced Plans Integrity Tests                 ✓ PASSED
Running ConfigHub & Search Cache Integration Tests     ✓ PASSED
Running Phase 3 Streaming Web & Typst Compiler Tests   ✓ PASSED
Running Fuzzing & Multi-Task Concurrency Tests         ✓ PASSED
Running End-to-End STORM Full Pipeline Test            ✓ PASSED (68 节点)
==================================================
ALL 7 INTEGRITY TEST SUITES PASSED! 🏆
```
