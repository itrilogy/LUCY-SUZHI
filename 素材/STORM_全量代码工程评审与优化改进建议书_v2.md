# STORM 全量代码工程评审与优化改进建议书 (v2)

> 审计范围：`knowledge_storm/async_core/` 全部 16 个模块 + `server/app.py` + `frontend/web/` 三件套  
> 审计基准：工程可靠性、并发安全、资源泄漏、Prompt 工程、产品功能完备度

---

## 一、工程可靠性与 Bug 级问题

### 1.1 httpx.AsyncClient 每次调用都新建连接池（严重资源泄漏）

**涉及文件**：[llm.py](file:///Users/ic/Project/storm/knowledge_storm/async_core/llm.py#L90-L91)

```python
# 当前：每次 chat() / generate() 调用都 new 一个 AsyncClient
async with httpx.AsyncClient(timeout=self.timeout) as client:
    for attempt in range(1, self.max_retries + 1):
        resp = await client.post(...)
```

**物理后果**：一个 6 章节文章 + 4 视角探索 = 约 30~50 次 LLM 调用，每次都经历 TCP 握手 → TLS 协商 → HTTP 请求 → 连接关闭。对 DeepSeek API 产生约 150+ 次无效握手，额外延迟 5~15 秒。

**修复方案**：将 `AsyncClient` 提升为实例级长连接池，在 `__init__` 中创建，在 Pipeline 结束时 `await llm.close()` 释放。

```python
class AsyncLLM:
    def __init__(self, ...):
        ...
        self._client = httpx.AsyncClient(
            timeout=self.timeout,
            limits=httpx.Limits(max_keepalive_connections=10, max_connections=20),
        )
    
    async def close(self):
        if self._client and not self._client.is_closed:
            await self._client.aclose()
```

**优先级**：P0（性能与资源泄漏）

---

### 1.2 stream() 方法同样存在连接池问题，且缺少重试与错误处理

**涉及文件**：[llm.py](file:///Users/ic/Project/storm/knowledge_storm/async_core/llm.py#L117-L149)

```python
async def stream(self, messages, ...):
    async with httpx.AsyncClient(timeout=self.timeout) as client:  # 又创建一个
        async with client.stream("POST", ...) as response:
            # 无 status_code 检查
            # 无重试机制
            async for line in response.aiter_lines():
                ...
```

**问题**：
1. 未检查 `response.status_code`，若返回 429/500 会直接抛异常
2. 零重试逻辑
3. 独立创建 AsyncClient

**优先级**：P1

---

### 1.3 FactPool.add_fact() 无事实去重，导致重复事实膨胀

**涉及文件**：[models.py](file:///Users/ic/Project/storm/knowledge_storm/async_core/models.py#L52-L66)

从真实测试结果可以看到：

```
Fact count: 9
 - Fact: 尼古丁袋是一种无烟气口含尼古丁递送产品。    ← 出现 3 次
 - Fact: 近年来，尼古丁袋在欧美市场的年复合增长率超过30%。  ← 出现 3 次
```

**根因**：`add_fact()` 无任何去重检查，3 个探索节点提取相同事实时全部追加。

**修复方案**：增加基于 `claim` 文本相似度（或精确匹配 + Jaccard 阈值）的去重守卫。

```python
def add_fact(self, claim: str, ...) -> Optional[FactEntry]:
    # 精确去重
    normalized = claim.strip()
    if any(f.claim.strip() == normalized for f in self.facts):
        return None
    ...
```

**优先级**：P0（直接影响引用质量与 Token 浪费）

---

### 1.4 SQLite 连接在每次操作中反复 `sqlite3.connect()`

**涉及文件**：
* [state_manager.py](file:///Users/ic/Project/storm/knowledge_storm/async_core/state_manager.py) — 每个 save/load/list/delete 方法
* [retriever.py](file:///Users/ic/Project/storm/knowledge_storm/async_core/retriever.py) — SearchCacheManager 每次 get/set
* [local_knowledge_hub.py](file:///Users/ic/Project/storm/knowledge_storm/async_core/local_knowledge_hub.py) — 每个方法

**物理后果**：一次完整 Pipeline 执行约 20~30 次 SQLite 连接/关闭开销。在 WAL 模式下虽然读并发无问题，但每次连接仍需解析 SQLite header、初始化 page cache。

**修复方案**：使用连接池或持有单一长连接，配合 `threading.local()` 在同步方法中安全复用。

**优先级**：P2（性能优化）

---

### 1.5 ConfigHub TOML 解析器手工实现，脆弱且不完整

**涉及文件**：[config_hub.py](file:///Users/ic/Project/storm/knowledge_storm/async_core/config_hub.py#L139-L162)

```python
# 手工逐行解析 TOML
lines = self.config_path.read_text(encoding="utf-8").split("\n")
current_section = ""
for line in lines:
    ...
```

**问题**：
1. 不支持 TOML 数组表、内联表、多行字符串
2. 不支持嵌套 section（如 `[llm.deepseek]`）
3. 数值类型（`max_concurrent = 15`）被当作字符串 `setattr`，Pydantic 校验可能偶发失败
4. Python 3.11+ 内置 `tomllib`，完全不需要手写

**修复方案**：

```python
import tomllib  # Python 3.11+ built-in
with open(self.config_path, "rb") as f:
    raw = tomllib.load(f)
```

**优先级**：P1（配置可靠性）

---

### 1.6 `_stage_polish_article` 仅做了 `$` 转义，未执行真正的内容润色

**涉及文件**：[pipeline.py](file:///Users/ic/Project/storm/knowledge_storm/async_core/pipeline.py#L438-L441)

```python
async def _stage_polish_article(self, draft: ArticleDraft) -> ArticleDraft:
    cleaned = draft.content.replace("$", "\\$")
    draft.polished_content = cleaned
    return draft
```

**问题**：这个"润色"阶段本应执行结构一致性检查、段落衔接优化、引用编号连续性验证等操作，目前只做了一个字符串替换，对产出质量无任何贡献。

**修复方案**：要么移除该伪阶段避免误导用户（Timeline 显示"结构一致性润色"），要么接入真实 LLM 调用做引用编号校验与段落衔接。

**优先级**：P1（产品诚信度）

---

## 二、并发安全与状态一致性

### 2.1 全局 Dict `RUNNING_TASKS` / `TASK_EVENT_QUEUES` 无锁保护

**涉及文件**：[server/app.py](file:///Users/ic/Project/storm/server/app.py#L71-L73)

```python
TASK_EVENT_QUEUES: Dict[str, asyncio.Queue] = {}
RUNNING_TASKS: Dict[str, asyncio.Task] = {}
```

**问题**：虽然 asyncio 是单线程事件循环模型，对 Dict 的竞态条件风险低于多线程场景，但以下边界场景仍可能出现不一致：
1. 同一用户快速连续点击"启动研究"，可能产生两个 task_id 指向同一 topic
2. `delete_task` 与 `_run_research_job` 的 `finally` 块同时操作 `RUNNING_TASKS.pop()`

**修复方案**：增加 task 去重守卫（按 topic 查重 + 节流）。

**优先级**：P2

---

### 2.2 SSE 事件流 `asyncio.Queue` 无界且不清理

**涉及文件**：[server/app.py](file:///Users/ic/Project/storm/server/app.py#L135)

```python
queue = TASK_EVENT_QUEUES.setdefault(task_id, asyncio.Queue())
```

**问题**：
1. `asyncio.Queue()` 默认无上界（`maxsize=0`），若前端长时间不消费 SSE，队列会无限膨胀
2. 任务完成后 `TASK_EVENT_QUEUES` 中的 Queue 对象不会被清理（仅在 `delete_task` 时清理），造成内存泄漏

**修复方案**：
1. 设置 `asyncio.Queue(maxsize=500)`
2. 在 `_run_research_job` 的 `finally` 中调用 `TASK_EVENT_QUEUES.pop(task_id, None)`

**优先级**：P1

---

## 三、Prompt 工程与 LLM 交互质量

### 3.1 视角发现 Prompt 的 fallback 人设不匹配中文课题

**涉及文件**：[pipeline.py](file:///Users/ic/Project/storm/knowledge_storm/async_core/pipeline.py#L213-L217)

```python
if not personas:
    personas = [
        Persona(name="Core Technologist", description="Focuses on underlying architecture and mechanisms"),
        ...
    ]
```

**问题**：中文课题（如"尼古丁袋"）的 fallback 角色名为全英文，与后续中文 Prompt 交互产生语言不一致。

**修复方案**：根据 `is_chinese` 判断使用中文 fallback 角色。

**优先级**：P2

---

### 3.2 大纲生成 Prompt 未区分语言，中文课题生成英文大纲

**涉及文件**：[pipeline.py](file:///Users/ic/Project/storm/knowledge_storm/async_core/pipeline.py#L311-L340)

```python
async def _stage_generate_outline(self, topic: str, fact_pool: FactPool) -> Outline:
    prompt = f"""Topic: {topic}
Key Facts & Insights Collected:
...
Generate a comprehensive, academic-grade article outline.
Format as Markdown headings ..."""
```

**问题**：对中文课题，该 Prompt 全英文要求 `"Generate a comprehensive, academic-grade article outline"`，大模型可能输出全英文章节标题（如 `## Market Overview` 而非 `## 市场概述`），与后续中文正文写作阶段产生割裂。

**修复方案**：同 `_stage_write_article` 一样引入 `is_chinese` 判断，使用中文指令。

**优先级**：P1

---

### 3.3 reviewer.py 的反思修正 Prompt 只送入 `content[:3000]`，长文尾部被截断

**涉及文件**：[reviewer.py](file:///Users/ic/Project/storm/knowledge_storm/async_core/reviewer.py#L114)

```python
Original Article Excerpt:
{draft.content[:3000]}
```

**问题**：6 章节 × 800 字 ≈ 4800 字，只送前 3000 字意味着后半篇完全未被反思覆盖。

**修复方案**：按评审报告指出的 `flawed_sections` 精准定位并提取对应章节文本，而非粗暴截断。

**优先级**：P1

---

## 四、产品功能缺失与设计建议

### 4.1 无任务进度百分比与预估剩余时间

**现状**：前端 Timeline 仅显示 5 个阶段的离散状态（active/completed），用户无法量化感知当前进度。

**设计建议**：
1. 后端在每个 SSE 事件中附加 `progress_pct`（0~100），基于当前阶段权重（DISCOVERY 5% / CURATION 40% / OUTLINE 10% / WRITING 35% / REVIEW 10%）计算
2. 前端增加一个连续进度条 + 预估剩余时间（基于已消耗时间与阶段权重推算）

**优先级**：P1

---

### 4.2 无并发任务隔离与排队机制

**现状**：`start_research` 直接 `asyncio.create_task()`，理论上可同时启动任意多个研究任务，且共享同一个 `AsyncLLM` 实例的 Token 计数器。

**设计建议**：
1. 引入全局任务并发上限（默认 2），超出时返回 `429 Too Many Requests` 或进入排队
2. 每个任务持有独立的 `AsyncLLM` 实例副本（或至少独立的 `total_tokens_used` 计数器）

**优先级**：P2

---

### 4.3 无 Token 用量估算与成本预警

**现状**：`llm.total_tokens_used` 仅在 Pipeline 结束时通过 `COMPLETED` 事件输出一次。

**设计建议**：
1. 每次 LLM 调用后实时推送 `TOKEN_USAGE` 事件，前端累计展示
2. 在启动任务前基于课题复杂度与 `max_depth` 估算 Token 用量范围，让用户决策
3. 支持设定 Token 硬上限（safety cap），超出自动终止任务

**优先级**：P1

---

### 4.4 研究报告无结构化摘要（Abstract）

**现状**：生成的文章直接以 `# Topic` 开头进入正文，缺少学术论文标配的摘要段落。

**设计建议**：在 `_stage_write_article` 完成后、`_stage_polish_article` 之前，增加一个 `_stage_generate_abstract` 阶段：让 LLM 基于全文内容生成 200-300 字中/英文摘要，并插入 `# Topic` 之后、首个 `## Section` 之前。

**优先级**：P1

---

### 4.5 导出功能仅返回 alert 提示，无文件下载

**现状**：Typst / Slides / HTML 导出后仅 `alert(文件路径)`，用户需要手动去服务器磁盘路径找文件。

**设计建议**：
1. 导出 API 返回文件下载 URL（或直接返回 `FileResponse`）
2. 前端自动触发浏览器下载

**优先级**：P1

---

### 4.6 无研究报告版本对比与历史快照

**现状**：每次 Reflexion 补丁直接覆盖 `draft.content`，原始初稿丢失。

**设计建议**：
1. `ArticleDraft` 增加 `versions: List[str]` 字段，每次修改前保存当前版本
2. 前端增加"版本对比"面板，支持 diff 展示反思前后的变化

**优先级**：P3

---

### 4.7 事实池无可信度权重与来源质量评级

**现状**：所有事实的 `confidence` 默认为 1.0，从权威学术论文与普通博客文章提取的事实被视为等价。

**设计建议**：
1. 在 `SearchSnippet` 中增加 `source_quality` 字段，基于引擎分类（scholarly vs general）赋予权重
2. 在章节写作时优先引用高可信度事实

**优先级**：P2

---

## 五、前端工程质量

### 5.1 app.js 单文件 989 行，零模块化

**现状**：所有逻辑（Tab 切换、SSE 流处理、导出、设置、任务管理）全部在一个文件中。

**设计建议**：至少拆分为：
* `core.js` — Tab、状态管理、工具函数
* `stream.js` — SSE 连接与事件分发
* `settings.js` — ConfigHub 设置面板
* `tasks.js` — 任务管理中心
* `export.js` — 导出功能

**优先级**：P2

---

### 5.2 全局函数挂载 + innerHTML 拼接，存在 XSS 风险

**涉及文件**：[app.js](file:///Users/ic/Project/storm/frontend/web/app.js#L656)

```javascript
html += `<div class="task-card" onclick="selectTask('${t.task_id}')">
    <span class="task-title">${escapeHtml(t.topic)}</span>
```

**问题**：
1. `selectTask`、`deleteTask` 等通过 `onclick="..."` 字符串注入，绕过了 CSP
2. `t.task_id` 未 escape，若后端返回恶意 task_id 可注入 JS
3. `escapeHtml` 仅处理了 4 种字符，不够完整

**修复方案**：使用 `addEventListener` 绑定事件，或使用模板渲染库。

**优先级**：P2

---

### 5.3 SSE 断线无自动重连

**涉及文件**：[app.js](file:///Users/ic/Project/storm/frontend/web/app.js#L215-L218)

```javascript
currentEventSource.onerror = (err) => {
    console.warn("SSE stream closed or interrupted.");
};
```

**问题**：网络抖动或 Nginx 超时断开 SSE 后，用户完全失去任务进度更新，需要手动刷新页面。

**修复方案**：增加指数退避自动重连机制（最多 5 次）。

**优先级**：P1

---

## 六、测试覆盖度缺口

### 6.1 无对 LLM 返回异常内容的防御性测试

**现状**：所有测试用的 Mock LLM 返回格式规范的内容。但真实场景中 DeepSeek 可能返回：
* 空字符串
* `<think>` 标签包裹的推理链
* 纯 Markdown 代码围栏包裹的 JSON
* 截断的不完整 JSON

**建议**：增加一组"恶意/异常 LLM 返回"的 Fuzzing 测试用例。

---

### 6.2 无对并发多任务的集成测试

**建议**：增加同时启动 2~3 个研究任务的集成测试，验证 Queue 隔离与状态机互不污染。

---

## 七、问题优先级汇总矩阵

| 优先级 | 问题 | 文件 |
| :--- | :--- | :--- |
| **P0** | httpx.AsyncClient 每次调用新建连接池 | `llm.py` |
| **P0** | FactPool 事实无去重，重复膨胀 | `models.py` |
| **P1** | SSE Queue 无界且不清理，内存泄漏 | `server/app.py` |
| **P1** | TOML 解析器手工实现，不支持标准语法 | `config_hub.py` |
| **P1** | `_stage_polish_article` 伪润色 | `pipeline.py` |
| **P1** | 大纲生成 Prompt 未区分中英文 | `pipeline.py` |
| **P1** | Reflexion 修正只送 3000 字，长文尾部漏评 | `reviewer.py` |
| **P1** | SSE 断线无自动重连 | `app.js` |
| **P1** | 无 Token 用量实时追踪与成本预警 | 全链路 |
| **P1** | 无结构化摘要（Abstract）生成 | `pipeline.py` |
| **P1** | 导出功能无文件下载，只 alert 路径 | `app.js` |
| **P1** | stream() 方法无重试与状态码检查 | `llm.py` |
| **P1** | 无任务进度百分比 | 全链路 |
| **P2** | SQLite 连接反复创建 | 多文件 |
| **P2** | 全局 Dict 无并发保护 | `server/app.py` |
| **P2** | Fallback 角色名中英不匹配 | `pipeline.py` |
| **P2** | app.js 989 行零模块化 | `app.js` |
| **P2** | innerHTML + onclick 存在 XSS 风险 | `app.js` |
| **P2** | 无并发任务数上限 | `server/app.py` |
| **P2** | 事实池无可信度权重 | `models.py` |
| **P3** | 无版本对比与历史快照 | `pipeline.py` |

---

## 八、推荐优先执行的 5 项改进

1. **将 `AsyncLLM` 的 `httpx.AsyncClient` 提升为实例级长连接池**——消除 30~50 次无效 TCP/TLS 握手，预计整体 Pipeline 加速 10~20%
2. **`FactPool.add_fact()` 引入精确去重守卫**——消除重复事实膨胀，降低 Token 浪费约 30%
3. **大纲生成 `_stage_generate_outline` 引入中英文 Prompt 分叉**——与下游写作阶段语言对齐
4. **SSE 事件流增加 `maxsize` 与自动清理 + 前端断线重连**——消除内存泄漏与前端信息丢失
5. **增加 `_stage_generate_abstract` 生成结构化摘要**——提升学术报告完整度
