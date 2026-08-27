# STORM 完整功能与使用操作指南 (Comprehensive Operational Guide)

## 一、系统架构与运行模式概览

STORM 是一个全配置驱动、纯异步轻量化、支持深度递归探索（Deep Research）的自动化知识策展与学术长文生成引擎。提供三种开箱即用的使用方式：

```mermaid
flowchart TD
    Config[配置中心: ~/.storm/config.toml / 环境变量 / Web 设置] --> Engine[STORM 异步深度研究内核]

    Engine --> Mode1[1. 现代 Web 控制台模式 (FastAPI + SSE)]
    Engine --> Mode2[2. 命令行 CLI 深度研究模式 (CLI Runner)]
    Engine --> Mode3[3. Python SDK 嵌入式调用模式]

    Mode1 & Mode2 & Mode3 --> Artifacts[(生成物: Markdown + 事实图谱 + Typst 双栏论文 + Marp 幻灯片 + 离线 HTML 研报)]
```

---

## 二、环境安装与配置

### 1. 极简依赖安装 (无需 GPU，无 PyTorch 负担)

```bash
# 进入工程根目录
cd /Users/ic/Project/storm

# 安装纯轻量异步依赖 (体积 < 50MB)
pip install -r requirements.txt
```

### 2. 模型与检索引擎配置 (支持三种方式)

#### 方式 A：环境变量 (推荐生产部署)
```bash
export DEEPSEEK_API_KEY="sk-your-deepseek-key"
export DEEPSEEK_API_BASE="https://api.deepseek.com"
export SEARXNG_API_URL="https://search.nunch.uk/search"  # 或您自建的 SearXNG 地址
```

#### 方式 B：全局配置文件 (`~/.storm/config.toml`)
```toml
[llm]
active = "deepseek"
deepseek.api_key = "sk-your-key"
deepseek.base_url = "https://api.deepseek.com"
deepseek.model = "deepseek-chat"

[search]
active_retriever = "searxng"
searxng.api_url = "https://search.nunch.uk/search"
searxng.engines_academic = "semantic_scholar,arxiv,pubmed,google_scholar"
searxng.engines_chinese = "google,bing,baidu,zhihu"
searxng.engines_general = "google,bing,duckduckgo"
```

#### 方式 C：Web 控制台可视化配置（免命令行编辑）
启动 Web 服务后，在界面点击右上角 **“⚙️ 系统与模型配置”**，支持界内切换厂商、点击 **“⚡ 探测并拉取模型”** 测算延迟并一键保存热重载。

---

## 三、四大核心使用模式详解

### 模式 1：现代响应式 Web 控制台 (首选推荐)

启动高性能 FastAPI + SSE 流式服务：

```bash
python3 -m server.app
```
* **控制台访问地址**：`http://localhost:8000`
* **功能亮点**：
  * **实时流式响应**：5 阶段进度指示轴毫秒级更新，实时推送专家角色发现、探索树下钻节点。
  * **实时思考终端 (Thinking Trace)**：实时滚动展示当前模型思考逻辑与事实提取。
  * **正文 Markdown 渲染**：带可点击的 `[i]` 引用标号，参考文献浮动卡片预览。
  * **一键导出**：支持一键导出 Typst 双栏论文、Marp 演讲幻灯片、离线印刷研报与复制 Markdown。

---

### 模式 2：命令行 CLI 深度研究模式 (生产/批量跑批)

#### 1. 基础快速研究 (标准模式)
```bash
python3 -m cli.async_runner --topic "Vibe Coding in Software Engineering"
```

#### 2. 启用深度递归探索树 (Deep Research 模式)
突破固定轮数，依据信息增益率自发下钻深入技术细节：
```bash
python3 -m cli.async_runner \
  --topic "Vibe Coding as a Paradigm for AI-Assisted Software Development" \
  --deep-research \
  --max-depth 2 \
  --perspectives 4
```

#### 3. 挂载本地知识库/语料库 (RRF 混合检索)
将外部 Web 搜索与本地私有文档（Markdown/TXT/代码仓库）融合检索：
```bash
python3 -m cli.async_runner \
  --topic "企业内部微服务治理演进" \
  --local-docs-dir ./raw_sources \
  --deep-research
```

#### 4. 任务中断恢复与断点续跑 (Resumable Workflow)
若任务因网络超时或 `Ctrl+C` 中断，系统已自动在 SQLite WAL 中记录快照，直接输入原 task_id 即可秒级恢复：
```bash
python3 -m cli.async_runner \
  --topic "企业内部微服务治理演进" \
  --resume storm_a1b2c3d4
```

---

### 模式 3：Python SDK 编程式调用 (集成到自有服务)

在自有 Python 项目中直接引入异步流水线：

```python
import asyncio
from knowledge_storm.async_core import (
    AsyncLLM,
    AsyncSearXNG,
    HybridRetriever,
    AsyncSTORMPipeline,
    WorkflowStateManager,
)

async def run_my_research():
    # 1. 实例化异步组件
    llm = AsyncLLM(
        model="deepseek-chat",
        api_key="sk-your-key",
        api_base="https://api.deepseek.com",
    )
    retriever = AsyncSearXNG(
        api_url="https://search.nunch.uk/search",
        engines_academic="semantic_scholar,arxiv",
        engines_general="google,bing",
    )

    # 2. 初始化流水线
    pipeline = AsyncSTORMPipeline(
        llm=llm,
        retriever=retriever,
        output_dir="./my_results",
        deep_research=True,
        max_depth=2,
        enable_review=True,
        enable_diagrams=True,
    )

    # 3. 异步驱动并接收事件
    def on_progress(stage, data):
        print(f">> Stage: {stage}")

    article = await pipeline.run(
        topic="Transformer vs Mamba Architecture Tradeoffs",
        progress_callback=on_progress,
    )

    print(f"生成的文章标题: {article.topic}")
    print(f"正文字数: {len(article.content)}")
    print(f"引用篇数: {len(article.citations)}")

if __name__ == "__main__":
    asyncio.run(run_my_research())
```

---

### 模式 4：Typst 论文排版、Marp 幻灯片与离线报告编译

STORM 内置了自动将 Markdown 正文和引用字典编译为 IEEE / ACM 双栏论文格式、Marp 演说幻灯片与独立离线 HTML 研报的导出引擎。

#### 1. 命令行直接编译 (需安装 Typst: `brew install typst`)
```bash
typst compile results_async/storm_xxxx/paper.typ paper.pdf
```

#### 2. Marp 演说幻灯片编译 (需安装 Marp CLI)
```bash
npx @marp-team/marp-cli results_async/storm_xxxx/slides.marp.md -o presentation.pptx
```

#### 3. 独立离线 HTML 研报
直接双击打开 `results_async/storm_xxxx/report_standalone.html`，可在无网络环境下查看完整排版与引用，并支持在浏览器中按 `Ctrl+P` 完美打印或另存为 PDF/Word。

---

## 四、生成物文件结构说明

每次研究任务执行完毕后，所有产物将结构化保存在 `results_async/<task_id>/` 目录下：

```
results_async/storm_a1b2c3d4/
├── article.md                # 带精确 [i] 引用与 Mermaid 架构图的完整长文
├── outline.md                # 结构化多级学术大纲
├── citations.json            # 参考文献完整元数据（URL、标题、摘录）
├── fact_pool.json            # 全量原子事实池
├── paper.typ                 # IEEE/ACM 双栏学术论文 Typst 源码
├── slides.marp.md            # Marp 演讲幻灯片演示文稿
└── report_standalone.html    # 独立自包含印刷级 HTML 研报
```

---

## 五、常见故障排查与易用性保障 (Troubleshooting)

| 现象 | 根因推导 | 解决方案 |
| :--- | :--- | :--- |
| **启动报错 `Missing API Key`** | 未检测到环境变量或配置中的密钥 | 执行 `export DEEPSEEK_API_KEY="sk-..."` 或在 Web 界面设置中心直接填写保存。 |
| **检索失败 / 结果为空** | SearXNG 节点响应慢或被限流 | 检查网络连接，系统会自动向通用组降级；也可在配置中切换为本地部署的 SearXNG 实例。 |
| **长任务执行中断** | 用户误按 `Ctrl+C` 或网络瞬态断开 | 查看日志中打印的 `task_id`，使用 `--resume <task_id>` 原地恢复，无需从头重跑。 |
| **Typst PDF 编译未生成** | 本地未安装 `typst` CLI 二进制 | 系统已自动落盘 `.typ` 源码文件，可通过 `brew install typst` 安装后编译，或在 Web 界面一键导出。 |
