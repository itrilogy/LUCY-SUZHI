# STORM 工程进化实录

## 一、项目定位

基于 Stanford STORM v1.1.1，将其从「OpenAI + You.com 写死的 Demo」演进为**全配置驱动的生产级知识策展引擎**。核心理念：LLM / 嵌入 / 重排序 / 检索引擎全部可替换，配置持久化于 `~/.storm/config.toml`，WebUI 可视管理。

## 二、架构决策

| 决策 | 选择 | 理由 |
|:---|:---|:---|
| LLM 后端 | DeepSeek v4-pro（直连 API） | 用户提供密钥，国产大模型 |
| LLM 备选 | 自定义 LiteLLM / OpenAI 兼容 | 通过 WebUI 切换 |
| 检索引擎 | searXNG（自部署 nunch.uk） | 免费、支持引擎分组 |
| 嵌入模型 | Infinity `bge-m3`（7997 端口） | 自部署 GPU 推理，1024 维 |
| 重排序 | Infinity `bge-reranker-v2-m3`（7998 端口） | 同上 |
| 配置中心 | `~/.storm/config.toml` | 用户级持久化，不污染项目 |
| 配置 UI | Streamlit Tab 页 | 可视管理，零手动改文件 |

## 三、关键文件改造清单

### 新增
- `cli/providers.toml` — 厂商端点注册表
- `knowledge_storm/reranker.py` — 多后端重排序（Cohere/Jina/本地/自定义）
- `cli/config_manager.py` — `StormConfig` 类 + `SERVICE_REGISTRY` + `save()` 递归序列化 + `get_llm/embed/rerank_config()`

### 重写
- `frontend/demo_light/pages_util/Configuration.py` — 统一模型管理 Tab（LLM + 嵌入 + 重排序），含拉取模型列表、诊断
- `frontend/demo_light/demo_util.py` — `set_storm_runner()` 全配置驱动 + 文章渲染改为 Python-Markdown
- `frontend/demo_light/pages_util/MyArticles.py` — `streamlit-card` → 原生按钮 + 删除功能

### 修改
- `knowledge_storm/encoder.py` — 新增 `custom` 后端（直连 Infinity `/embeddings`）
- `knowledge_storm/reranker.py` — 新增 `custom` 后端（直连 Infinity `/rerank`）
- `knowledge_storm/storm_wiki/modules/persona_generator.py` — Wikipedia 抓取并发化 + 超时 + 反代替换
- `knowledge_storm/storm_wiki/modules/storm_dataclass.py` — `SentenceTransformer` → 内置 numpy 余弦相似度 + `Persona` dataclass
- `knowledge_storm/storm_wiki/engine.py` — `_fact_pool` 初始化前移 + `encoder/reranker` 透传
- `knowledge_storm/rm.py` — `SearXNG` 类增加 `engines_academic/chinese/general` 三轨路由
- `knowledge_storm/lm.py` — `AutoTokenizer` 懒加载
- `knowledge_storm/storm_wiki/modules/knowledge_curation.py` — Wikipedia 并发 + Persona 对象传递
- `cli/config_manager.py` — `save()` 递归序列化 + `SERVICE_REGISTRY` 简化为 core 提供商

## 四、排查时间线

| 时间 | 现象 | 根因 | 修复 |
|:---|:---|:---|:---|
| 17:25 | `ModuleNotFoundError: bs4` | venv 未装依赖 | `pip install beautifulsoup4` |
| 17:30 | `ModuleNotFoundError: sentence_transformers` | `storm_dataclass.py` 硬导入 | 改为懒加载 + numpy 内置余弦 |
| 17:35 | `ModuleNotFoundError: transformers` | `lm.py` 硬导入 `AutoTokenizer` | 懒加载 try/except |
| 17:40 | `ModuleNotFoundError: scipy` | sklearn 未完全安装 | `pip install scipy` |
| 18:06 | `ModuleNotFoundError: sklearn` → `scipy` | 连锁缺包 | 补装全部依赖 |
| 启动成功 | WebUI 可打开 | - | - |
| 配置嵌入 | 诊断显示 `HTTP 404/405 正常` | `_test_service` 用 GET 探测 API | 改为 POST `/v1/embeddings` |
| 配置 searXNG | `SearXNG.init() unexpected keyword 'engines_academic'` | `rm_params` 残留未 pop 的参数 | 显式传参 |
| 开始研究 | `AttributeError: _fact_pool` | 初始化顺序：`apply_decorators()` 在 `_fact_pool = None` 之前 | 交换两行 |
| 开始研究 | `ProxyError` | 系统代理拦截 `api.deepseek.com` | 切到自定义 LiteLLM 内网地址 |
| 角色生成 | `TypeError: expected str, Persona found` | `persona_generator` 返回 `Persona` 对象但回调期望字符串 | `on_identify_perspective_end` 兼容 `Persona.to_perspective()` |
| 嵌入报错 | `litellm.ServiceUnavailableError 503` | litellm 无限重试 + 空 snippet 嵌入 | 切到 custom 后端直连 Infinity |
| 嵌入不可达 | `Empty reply from server` | 7997 端口未放通 iptables | 开代理/VPN |
| 点击文章 | **完全无反应** | `streamlit-card` 组件 JS 与 Streamlit 版本不兼容，阻塞事件总线 | 卸载 `streamlit-card`，改用原生 `st.button` |
| 文章显示 | 渲染两次 + 目录点击无效 | `st.markdown()` 不生成锚点 ID | 改用 `markdown.markdown()` 预渲染 HTML |
| 文章导航 | 遗留问题 | TOC 锚点与 Streamlit 页面滚动机制不兼容 | 待解决 |

## 五、已知遗留问题

1. **侧边栏目录点击不跳转**：`st.markdown(html)` 不执行内联 JS，`<a href="#anchor">` 在 Streamlit 中不会滚动页面
2. **角色生成：Wikipedia 抓取全崩**：中文主题无对等英文 Wiki 页面，LLM 凭空造角色
3. **searXNG 中文组全返回 B 站**：`engines_chinese=baidu,zhihu,bilibili` 质量太低，应改为 `google,bing`
4. **`providers.toml` 厂商注册表未完成**：端点地址仍硬编码在各处
5. **Ctrl+C 无法停止研究**：`requests` 无超时 + `ThreadPoolExecutor` 非 daemon

## 六、下次修订入口

- 配置模型拉取列表 → `Configuration.py` fetch 按钮
- 搜索质量 → 修改 searXNG 中文引擎组为 `google,bing`
- 角色生成 → 关闭 Wikipedia 抓取分支，直接让 LLM 自由发挥（反正抓了也是全崩）
- 目录跳转 → 改用 Streamlit 原生 `st.markdown` 的 header anchor 机制（需升级到 1.35+）
