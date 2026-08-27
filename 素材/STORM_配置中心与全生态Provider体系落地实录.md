# STORM 配置中心与全生态 Provider 体系落地实录 (ConfigHub & Search Cache)

## 一、本次实施的重大工程落地

为彻底解决传统多模型配置繁琐、手动盲填易拼写错误、SearXNG 检索延迟高（$3\sim 6\text{s}$）且缺少本地缓存等痛点，本次开发成功落地统一强类型配置中心 **ConfigHub** 与检索三级缓存体系。

```mermaid
flowchart TD
    subgraph ConfigHub 配置四层继承与自动发现
        UserEnv[1. 系统环境变量 .env] --> Hierarchy[四层优先级解析引擎]
        UserToml[2. 用户级 config.toml] --> Hierarchy
        Presets[3. 内置全生态厂商矩阵] --> Hierarchy
        Hierarchy --> ActiveProfile[统一生效 Profile (脱敏)]
        ActiveProfile --> Probe[⚡ 异步探测端点 GET /v1/models]
        Probe --> AutoFill[自动拉取可用模型与测算 RTT 延迟]
    end

    subgraph 检索性能跃迁 (Search Caching & Deep Extract)
        SearchQuery[研究节点检索查询] --> SQLiteCache{SQLite WAL 缓存命中?}
        SQLiteCache -- 命中 (<5ms) --> CachedData[返回缓存结果]
        SQLiteCache -- 未命中 --> PooledSearXNG[HTTP/2 复用连接池 SearXNG (15 并发)]
        PooledSearXNG --> JinaReader[Jina Reader 二级深度提纯 (Markdown 1500字)]
        JinaReader --> SaveCache[存入 SQLite 缓存 (TTL 12h)]
    end
```

---

## 二、关键文件与模块实现细节

### 1. 强类型配置中心与 Provider 管理矩阵 (`knowledge_storm/async_core/config_hub.py`)
* **核心类与函数**：`ConfigHub`、`StormSystemConfig`、`LLMProviderInfo`、`SearchProviderInfo`、`probe_llm_endpoint`、`probe_search_endpoint`
* **底层能力**：
  * **四层优先级继承**：`CLI Flags > Environment Variables > ~/.storm/config.toml > Built-in Presets`。
  * **预置全生态主流厂商**：DeepSeek 官方直连、SiliconFlow (硅基流动)、OpenAI 官方端点、Ollama 本地免 Key 实例、Moonshot (Kimi)、自建/私有 SearXNG 及 DuckDuckGo。
  * **异步探测与自发现**：自动向 `/v1/models` 端点发起轻量级握手，自动拉取账号下可用模型列表，并测算网络往返延迟 RTT（毫秒）。
  * **安全脱敏**：默认执行 `sk-xxxx...xxxx` 掩码脱敏，杜绝日志与 Web 展示泄密。

### 2. 检索端三级缓存与深度提纯 (`knowledge_storm/async_core/retriever.py`)
* **核心类**：`SearchCacheManager`、`AsyncSearXNG`
* **底层能力**：
  * **本地 SQLite WAL 检索缓存**：基于 SHA256 查询哈希建立本地缓存表（默认 TTL 12 小时）。相同或归一化查询直接 **$< 5\text{ms}$** 返回，显著削减重复研究耗时。
  * **Jina Reader 二级正文深度提纯**：提供 `fetch_deep_markdown()` 接口，通过 `https://r.jina.ai/<url>` 快速提纯 Markdown 全文，突破搜索 Snippet 字数限制。

### 3. 服务端 API 与 Web 前端控制台设置抽屉 (`server/app.py` & `frontend/web/`)
* **服务端 API**：
  * `GET /api/v1/config/providers`：获取脱敏全量配置。
  * `POST /api/v1/config/probe`：异步探测端点连通性与模型拉取。
  * `POST /api/v1/config/save`：保存配置并实时热重载。
* **前端 Web 控制台**：
  * 引入现代化设置抽屉/模态框组件，支持下拉切换活跃 LLM 与搜索引擎。
  * 密码框提供一键显隐，集成 **“⚡ 探测并拉取模型”** 与 **“⚡ 探测检索连通性”** 按钮，实时展示绿色在线指示灯与延迟。

---

## 三、测试与验证结果

* **测试脚本**：[`tests/test_config_hub_and_probe.py`](file:///Users/ic/Project/storm/tests/test_config_hub_and_probe.py)
* **执行结果**：
  * ConfigHub 配置加载、脱敏与磁盘保存：**100% 通过**
  * SQLite 检索缓存写入与命中：**100% 通过**
  * 异步端点探测网络异常降级：**100% 通过**
  * 全局代码字节码编译：`python3 -m compileall server knowledge_storm cli tests -q` **100% 通过**
