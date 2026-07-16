"""
STORM WebUI 配置管理页面

提供可视化的密钥管理和服务配置界面。
全量中文化。
"""

import os
import sys
import urllib3
import streamlit as st

urllib3.disable_warnings()

# 确保能找到 cli/config_manager
sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "..", ".."))
from cli.config_manager import StormConfig, SERVICE_REGISTRY


def _mask_key(value: str) -> str:
    """遮蔽密钥中间部分。"""
    if len(value) > 12:
        return value[:6] + "••••" + value[-4:]
    elif value:
        return value[:4] + "••••"
    return ""


def _test_connection(config: StormConfig, service_key: str) -> str:
    """测试单个服务连接。"""
    results = config.diagnose()
    for r in results:
        if r["key"] == service_key:
            return r["status"]
    return "未知"


def config_page():
    """配置管理页面主入口。"""
    st.title("🔧 系统配置")
    st.markdown("管理 API 密钥与搜索引擎服务连接参数。配置存储在 `~/.storm/config.toml`。")

    config = StormConfig()

    # ── 分 Tab 展示 ──
    tab_model, tab_search, tab_export, tab_diag = st.tabs([
        "🧠 模型配置", "🔍 搜索引擎", "📤 导出配置", "🔬 系统诊断"
    ])

    # ═══════════════════════════════════════════
    # Tab 1: 统一模型管理
    # ═══════════════════════════════════════════
    with tab_model:
        st.subheader("模型配置管理")
        st.caption("集中管理 LLM / 嵌入 / 重排序模型。知名厂商自动填入 API 地址（只读），OpenAI 兼容接口可自定地址。")

        # ── 活跃模型选择器 ──
        col_a, col_b, col_c = st.columns(3)
        with col_a:
            current_llm = config.get_active_llm()
            llm_opts = {"deepseek": "DeepSeek", "openai": "OpenAI", "custom": "OpenAI 兼容"}
            idx = list(llm_opts.keys()).index(current_llm) if current_llm in llm_opts else 0
            sel = st.selectbox("🤖 活跃 LLM", list(llm_opts.values()), index=idx, key="m_llm")
            new_v = {v: k for k, v in llm_opts.items()}[sel]
            if new_v != current_llm:
                config.set("llm.active", new_v)
        with col_b:
            current_emb = config.get("embed.active") or "openai"
            emb_opts = {"openai": "OpenAI", "custom": "OpenAI 兼容"}
            idx = list(emb_opts.keys()).index(current_emb) if current_emb in emb_opts else 0
            sel = st.selectbox("🧬 活跃嵌入", list(emb_opts.values()), index=idx, key="m_emb")
            new_v = {v: k for k, v in emb_opts.items()}[sel]
            if new_v != current_emb:
                config.set("embed.active", new_v)
        with col_c:
            current_rr = config.get("rerank.active") or "none"
            rr_opts = {"cohere": "Cohere", "jina": "Jina", "custom": "OpenAI 兼容", "none": "无"}
            idx = list(rr_opts.keys()).index(current_rr) if current_rr in rr_opts else 3
            sel = st.selectbox("📊 活跃重排序", list(rr_opts.values()), index=idx, key="m_rr")
            new_v = {v: k for k, v in rr_opts.items()}[sel]
            if new_v != current_rr:
                config.set("rerank.active", new_v)

        st.divider()

        # ── 已配置模型列表 ──
        model_items = [s for s in SERVICE_REGISTRY if s[0] in ("LLM", "嵌入", "重排序")]

        def _parse_extra(extra: str) -> dict:
            """解析 extra 字段，提取 provider/base_url/model。"""
            result = {"provider": "", "base_url": "", "model": ""}
            for param in extra.split(","):
                for key in result:
                    if param.startswith(f"{key}:"):
                        val = param.split("=", 1)[1] if "=" in param else ""
                        result[key] = val
            return result

        has_any = False
        for cat, svc, prefix, env_var, needs_url, extra, free in model_items:
            if svc == "无":
                continue
            api_key_val = config.get(f"{prefix}.api_key")
            if not api_key_val and not free:
                continue
            has_any = True

            ei = {"base_url": "", "model": ""}
            for param in extra.split(","):
                for k in ei:
                    if param.startswith(f"{k}:"):
                        val = param.split("=", 1)[1] if "=" in param else ""
                        ei[k] = val

            icon = {"LLM": "🤖", "嵌入": "🧬", "重排序": "📊"}.get(cat, "🔌")
            rid = prefix.replace(".", "_")

            edit_key = f"_edit_{rid}"
            if edit_key not in st.session_state:
                st.session_state[edit_key] = False

            with st.container(border=True):
                st.markdown(f"**{icon} {svc}** {'✅ 已配置' if api_key_val else '🆓 免费'}")
                is_custom = (needs_url is True)

                if st.session_state[edit_key]:
                    bu_val = config.get(f"{prefix}.base_url") or ei["base_url"]
                    ak_val = api_key_val or ""
                    md_val = config.get(f"{prefix}.model") or ei["model"]

                    bu = st.text_input("API 接入地址", value=bu_val,
                        disabled=not is_custom, key=f"bu_{rid}",
                        placeholder="http://your-server:7997" if is_custom else "")
                    ak = st.text_input("API 密钥", type="password", value=ak_val, key=f"ak_{rid}")

                    # ── 模型 ID 输入 + 获取模型列表按钮 ──
                    models_key = f"mdl_list_{rid}"
                    if models_key not in st.session_state:
                        st.session_state[models_key] = None

                    col_m1, col_m2 = st.columns([4, 1])
                    with col_m2:
                        if st.button("📋 获取模型列表", key=f"fetch_{rid}"):
                            base = (bu if is_custom else bu_val).rstrip("/")
                            # DeepSeek: /models, OpenAI 兼容: /v1/models
                            models_url = base + ("/v1/models" if is_custom else "/models")
                            fetch_key = ak or ak_val
                            try:
                                import requests
                                resp = requests.get(models_url,
                                    headers={"Authorization": f"Bearer {fetch_key}"} if fetch_key else {},
                                    timeout=10)
                                if resp.status_code == 200:
                                    data = resp.json().get("data", [])
                                    st.session_state[models_key] = [m["id"] for m in data if "id" in m]
                                    st.success(f"已获取 {len(st.session_state[models_key])} 个模型")
                                else:
                                    st.error(f"HTTP {resp.status_code}")
                            except Exception as e:
                                st.error(f"请求失败: {str(e)[:60]}")
                            st.rerun()

                    with col_m1:
                        cached = st.session_state[models_key]
                        if cached:
                            md = st.selectbox("模型 ID", cached,
                                index=cached.index(md_val) if md_val in cached else 0,
                                key=f"md_{rid}")
                        else:
                            md = st.text_input("模型 ID", value=md_val, key=f"md_{rid}",
                                placeholder=ei["model"] or "model-name",
                                help="点击右侧按钮拉取最新模型列表")

                    c1, c2 = st.columns([1, 1])
                    with c1:
                        if st.button("✅ 保存", key=f"sv_{rid}"):
                            if ak:
                                config.set(f"{prefix}.api_key", ak)
                            if md:
                                config.set(f"{prefix}.model", md)
                            if bu and is_custom:
                                config.set(f"{prefix}.base_url", bu)
                            st.session_state[edit_key] = False
                            st.rerun()
                    with c2:
                        if st.button("取消", key=f"cn_{rid}"):
                            st.session_state[edit_key] = False
                            st.rerun()
                else:
                    c1, c2, c3, c4 = st.columns([3, 2, 2, 2])
                    with c1:
                        bd = config.get(f"{prefix}.base_url") or ei["base_url"] or "—"
                        st.caption(f"📍 {bd}")
                    with c2:
                        m = config.get(f"{prefix}.model") or ei["model"] or "—"
                        st.caption(f"🧩 {m}")
                    with c3:
                        if api_key_val:
                            st.caption(f"🔑 {_mask_key(api_key_val)}")
                    with c4:
                        cols = st.columns(3)
                        with cols[0]:
                            if st.button("✏️", key=f"ed_{rid}", help="编辑"):
                                st.session_state[edit_key] = True
                                st.rerun()
                        with cols[1]:
                            if api_key_val and st.button("🔗", key=f"ts_{rid}", help="测试"):
                                status = _test_connection(config, f"{prefix}.api_key")
                                if status.startswith("✅"):
                                    st.success(status)
                                elif status.startswith("⚠️"):
                                    st.warning(status)
                                else:
                                    st.error(status)
                        with cols[2]:
                            if api_key_val and st.button("🗑️", key=f"dl_{rid}", help="清除"):
                                config.delete(f"{prefix}.api_key")
                                config.delete(f"{prefix}.base_url")
                                config.delete(f"{prefix}.model")
                                st.rerun()

        if not has_any:
            st.info("尚未配置任何模型。使用下方表单添加。")

        st.divider()

        # ── 新增模型 ──
        with st.expander("➕ 新增模型配置", expanded=False):
            add_type = st.selectbox("接口类型", ["LLM", "嵌入", "重排序"])
            candidates = [s for s in SERVICE_REGISTRY if s[0] == add_type and s[6] is False]
            add_provider = st.selectbox("提供商", [s[1] for s in candidates])
            selected = [s for s in candidates if s[1] == add_provider][0]
            _, _, add_prefix, add_env, add_needs_url, add_extra, _ = selected

            ei = {"base_url": "", "model": ""}
            for param in add_extra.split(","):
                for k in ei:
                    if param.startswith(f"{k}:"):
                        val = param.split("=", 1)[1] if "=" in param else ""
                        ei[k] = val

            is_custom = add_needs_url

            add_url = st.text_input("API 接入地址",
                value="" if is_custom else ei["base_url"],
                disabled=not is_custom,
                placeholder="http://your-server:7997" if is_custom else "")
            add_api = st.text_input("API 密钥", type="password", placeholder=f"输入 {add_provider} Key...")

            # 获取模型列表
            if "fetch_add_models" not in st.session_state:
                st.session_state["fetch_add_models"] = None

            col_m1, col_m2 = st.columns([4, 1])
            with col_m2:
                if st.button("📋 获取模型列表", key="fetch_add"):
                    base = (add_url if is_custom else ei["base_url"]).rstrip("/")
                    url = base + ("/v1/models" if is_custom else "/models")
                    try:
                        import requests
                        resp = requests.get(url,
                            headers={"Authorization": f"Bearer {add_api}"} if add_api else {},
                            timeout=10)
                        if resp.status_code == 200:
                            data = resp.json().get("data", [])
                            st.session_state["fetch_add_models"] = [m["id"] for m in data if "id" in m]
                            st.success(f"已获取 {len(st.session_state['fetch_add_models'])} 个模型")
                        else:
                            st.error(f"HTTP {resp.status_code}")
                    except Exception as e:
                        st.error(f"请求失败: {str(e)[:60]}")
                    st.rerun()
            with col_m1:
                cached = st.session_state["fetch_add_models"]
                if cached:
                    add_model = st.selectbox("模型 ID", cached,
                        index=0 if not ei["model"] or ei["model"] not in cached else cached.index(ei["model"]),
                        key="md_add")
                else:
                    add_model = st.text_input("模型 ID", value=ei["model"], key="md_add_txt",
                        placeholder=ei["model"] or "model-name")

            if st.button("💾 添加", key="submit_add"):
                if add_api:
                    config.set(f"{add_prefix}.api_key", add_api)
                if add_url and is_custom:
                    config.set(f"{add_prefix}.base_url", add_url)
                model_saved = ""
                if add_model:
                    config.set(f"{add_prefix}.model", add_model)
                    model_saved = f" ({add_model})"
                st.success(f"已添加 {add_provider}{model_saved}")
                st.rerun()
    # ═══════════════════════════════════════════
    # Tab 2: 搜索引擎
    # ═══════════════════════════════════════════
    with tab_search:
        st.subheader("搜索引擎配置")
        st.caption("DuckDuckGo 免费可用；searXNG 自部署需填入服务地址。")

        # 活跃检索引擎
        current_search = config.get("search.active_retriever") or "duckduckgo"
        srch_opts = {"searxng": "searXNG", "duckduckgo": "DuckDuckGo", "serper": "Serper"}
        idx = list(srch_opts.keys()).index(current_search) if current_search in srch_opts else 1
        sel = st.selectbox("🔍 活跃检索引擎", list(srch_opts.values()), index=idx, key="m_srch")
        new_v = {v: k for k, v in srch_opts.items()}[sel]
        if new_v != current_search:
            config.set("search.active_retriever", new_v)
        st.divider()

        # searXNG
        with st.container(border=True):
            st.markdown("**searXNG**（自部署元搜索引擎）")
            url_val = config.get("search.searxng.base_url") or ""
            api_val = config.get("search.searxng.api_key") or ""

            searx_url = st.text_input("服务地址", value=url_val,
                placeholder="https://search.nunch.uk/search", key="searx_url")
            searx_key = st.text_input("API 密钥（可选）", type="password",
                value=api_val, key="searx_key")

            with st.expander("引擎分组（可选）"):
                ae = st.text_input("学术组引擎",
                    value=config.get("search.searxng.engines_academic") or "semantic+scholar,arxiv,pubmed,google+scholar",
                    key="se_ae")
                ce = st.text_input("中文组引擎",
                    value=config.get("search.searxng.engines_chinese") or "baidu,zhihu,bilibili",
                    key="se_ce")
                ge = st.text_input("通用组引擎",
                    value=config.get("search.searxng.engines_general") or "google,bing,duckduckgo",
                    key="se_ge")

            c1, c2 = st.columns([1, 1])
            with c1:
                if st.button("💾 保存 searXNG", key="save_searx"):
                    if searx_url:
                        config.set("search.searxng.base_url", searx_url)
                    if searx_key:
                        config.set("search.searxng.api_key", searx_key)
                    config.set("search.searxng.engines_academic", ae)
                    config.set("search.searxng.engines_chinese", ce)
                    config.set("search.searxng.engines_general", ge)
                    st.success("已保存")
            with c2:
                if searx_url and st.button("🔗 测试", key="test_searx"):
                    try:
                        import requests
                        r = requests.get(searx_url, timeout=5)
                        if r.status_code < 400:
                            st.success(f"✅ 连接正常 (HTTP {r.status_code})")
                        else:
                            st.warning(f"HTTP {r.status_code}")
                    except Exception as e:
                        st.error(str(e)[:60])

        # DuckDuckGo
        with st.container(border=True):
            st.markdown("**DuckDuckGo**")
            ddg_on = config.get("search.ddg.enabled") or "true"
            enabled = st.checkbox("启用 DuckDuckGo 搜索", value=(ddg_on != "false"), key="ddg_on")
            if st.button("💾 保存", key="save_ddg"):
                config.set("search.ddg.enabled", "true" if enabled else "false")
                st.success("已保存")

        # Serper
        with st.container(border=True):
            st.markdown("**Serper**（Google 搜索 API）")
            serper_key = config.get("search.serper.api_key") or ""
            new_serper = st.text_input("API 密钥", type="password",
                value=serper_key, placeholder="输入 Serper API Key...", key="serper_api")
            c1, c2 = st.columns([1, 1])
            with c1:
                if st.button("💾 保存", key="save_serper"):
                    if new_serper:
                        config.set("search.serper.api_key", new_serper)
                        st.success("已保存")
            with c2:
                if serper_key and st.button("🗑️ 清除", key="del_serper"):
                    config.delete("search.serper.api_key")
                    st.success("已清除")

    # ═══════════════════════════════════════════
    # Tab 3: 导出配置
    # ═══════════════════════════════════════════
    with tab_export:
        st.subheader("导出配置为 secrets.toml")
        st.markdown("""
        将当前配置导出为项目级 `secrets.toml` 文件。该文件将被 STORM 流水线的
        `load_api_key()` 函数自动读取并设为环境变量。
        """)

        # 显示将要导出的配置项
        items = config.list_all()
        configured = [i for i in items if i["configured"]]
        if configured:
            st.success(f"共有 {len(configured)} 项已配置待导出")
            for item in configured:
                st.code(f'{item["env_var"]} = "{_mask_key(item["value"])}"', language="toml")
        else:
            st.warning("当前没有已配置的密钥项")

        output_path = st.text_input("导出路径", value="./secrets.toml", key="export_path")
        if st.button("📤 导出 secrets.toml", type="primary"):
            config.export_secrets_toml(output_path)
            st.success(f"✅ 已导出到 {output_path}")
            if os.path.exists(output_path):
                with open(output_path, "r") as f:
                    st.code(f.read(), language="toml")

    # ═══════════════════════════════════════════
    # Tab 3: 系统诊断
    # ═══════════════════════════════════════════
    with tab_diag:
        st.subheader("系统连接诊断")
        st.markdown("测试所有已配置服务的连接状态。")

        if st.button("🔬 运行全量诊断", type="primary"):
            with st.spinner("正在测试连接..."):
                results = config.diagnose()
                ok = sum(1 for r in results if r["status"].startswith("✅"))
                warn = sum(1 for r in results if r["status"].startswith("⚠️"))
                err = sum(1 for r in results if r["status"].startswith("❌"))

                # 统计指标
                col1, col2, col3, col4 = st.columns(4)
                col1.metric("总计", len(results))
                col2.metric("✅ 正常", ok)
                col3.metric("⚠️ 警告", warn)
                col4.metric("❌ 异常", err)

                # 详细列表
                current_cat = None
                for r in results:
                    if r["category"] != current_cat:
                        current_cat = r["category"]
                        st.markdown(f"---\n**{current_cat}**")
                    status = r["status"]
                    if status.startswith("✅"):
                        st.success(f"  {r['service']}: {status}")
                    elif status.startswith("⚠️"):
                        st.warning(f"  {r['service']}: {status}")
                    else:
                        st.error(f"  {r['service']}: {status}")
        else:
            st.info("点击上方按钮运行诊断")
