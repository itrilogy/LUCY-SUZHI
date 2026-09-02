# NOTICE — 第三方与上游权利声明

本软件「溯知深度知识策展与学术长文生成系统」在发行与运行时可能包含下列第三方组件。其权利归原权利人，使用须遵守相应许可证。下列内容 **不纳入** 本软件著作权登记客体。

## 1. Stanford STORM（上游方法学与遗留实现）

- 名称：STORM — Synthesis of Topic Outlines through Retrieval and Multi-perspective Question Asking  
- 权利人：Stanford Open Virtual Assistant Lab  
- 许可：MIT License（见仓库根目录 `LICENSE`）  
- 本仓库中对应路径：`knowledge_storm/storm_wiki/`、`knowledge_storm/collaborative_storm/`、部分历史示例与 `setup.py` 元数据  
- 说明：溯知 V1.0 的运行主路径为实验室自研的 `knowledge_storm/async_core/` + `server/` + `frontend/web/` + `cli/`。上游实现保留供对照，不作为本软件功能交付物。

## 2. 运行时与构建依赖（Python）

| 组件 | 典型许可 | 用途 |
| :--- | :--- | :--- |
| FastAPI / Starlette / Uvicorn | MIT / BSD | HTTP 与 SSE 服务 |
| Pydantic v2 | MIT | 强类型数据契约 |
| httpx / h2 | BSD | 异步 HTTP 客户端 |
| NumPy | BSD | 数值辅助 |
| BeautifulSoup4 | MIT | 网页正文解析 |
| Markdown | BSD | Markdown 处理 |

以 `requirements.txt` 安装的精确版本及其传递依赖为准。

## 3. 前端运行时（本机副本 `frontend/web/vendor/`）

| 组件 | 版本 | 用途 |
| :--- | :--- | :--- |
| marked | 15.0.7 MIT | Markdown 渲染 |
| mermaid | 10.9.3 MIT | 机制图 |

离线研报 HTML **不再**嵌入或请求这些脚本；机制图以源码块保存。

## 4. 检索与模型服务（运行时外部系统）

SearXNG、DeepSeek、OpenAI 兼容端点、Jina Reader 等为用户自行配置的外部服务，权属与服务条款归各提供方。本软件不对其内容主张著作权。

## 5. 品牌

- 溯知方标与横版字锁：本软件产品视觉，随本软件文档一并保护。  
- 鹿溪联合实验室主 LOGO：实验室官方标识，工程内仅为单向拷贝，权属仍归实验室/权利人。
