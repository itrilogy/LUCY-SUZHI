#!/usr/bin/env python3
"""
STORM 交互式向导 — 配置管理 + 流水线编排

提供渐进式菜单，引导用户完成：
  - 密钥管理
  - 搜索引擎服务配置
  - 项目创建与流水线运行
  - 系统诊断与排错

用法:
  python3 -m cli.interactive_wizard
"""

import os
import sys
import subprocess
from pathlib import Path

# 确保能找到 config_manager
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from cli.config_manager import StormConfig, SERVICE_REGISTRY


def clear_screen():
    os.system("cls" if os.name == "nt" else "clear")


def print_header(title: str):
    print(f"\n{'='*55}")
    print(f"  {title}")
    print(f"{'='*55}")


def print_menu(options: list, title: str = None):
    """打印选项菜单。"""
    if title:
        print(f"\n┌─ {title} ─────────────────────┐")
    for key, desc in options:
        print(f"  [{key}] {desc}")
    print(f"  {'─'*40}")


def wait_for_enter():
    input("\n  按 Enter 键继续...")


# ═══════════════════════════════════════════════════════════════════════════
# 配置管理子菜单
# ═══════════════════════════════════════════════════════════════════════════

def config_llm_menu(config: StormConfig):
    """管理 LLM 密钥。"""
    while True:
        clear_screen()
        print_header("LLM 密钥管理")

        items = [s for s in SERVICE_REGISTRY if s[0] == "LLM"]
        for i, (cat, svc, key, env, url, extra, free) in enumerate(items, 1):
            val = config.get(key)
            if free:
                # Ollama 类——检查 URL
                url_val = config.get(key)
                if url_val:
                    status = f"✅ {url_val}"
                else:
                    status = "❌ 未配置"
                print(f"  {i}. {svc}  {status}")
            elif val:
                masked = val[:8] + "..." if len(val) > 10 else "****"
                print(f"  {i}. {svc}  ✅ 已配置 ({masked})")
            else:
                print(f"  {i}. {svc}  ❌ 未配置  [{env}]")

        print()
        print("  [a] 新增/修改  [d] 删除  [t] 测试连接  [q] 返回主菜单")
        choice = input("\n  请选择 > ").strip().lower()

        if choice == "q":
            break
        elif choice == "a":
            print()
            idx = input("  输入服务编号: ").strip()
            if idx.isdigit() and 1 <= int(idx) <= len(items):
                _, svc, key, env, _, extra, free = items[int(idx) - 1]
                if free:
                    val = input(f"  服务地址 (默认 http://localhost:11434): ").strip()
                    config.set(key, val or "http://localhost:11434")
                    model = input(f"  模型名 (默认 llama3): ").strip()
                    if model:
                        config.set("llm.ollama_model", model)
                else:
                    current = config.get(key)
                    hint = f" (当前已配置)" if current else ""
                    val = input(f"  输入 {svc} API Key{hint}: ").strip()
                    if val:
                        config.set(key, val)
                print("  ✅ 已保存")
        elif choice == "d":
            idx = input("  输入要删除的服务编号: ").strip()
            if idx.isdigit() and 1 <= int(idx) <= len(items):
                _, svc, key, *_ = items[int(idx) - 1]
                config.delete(key)
                print(f"  ✅ 已删除 {svc}")
        elif choice == "t":
            print("\n  ⏳ 正在测试...")
            from cli.config_manager import cmd_diagnose
            # 只测试 LLM 部分
            results = config.diagnose()
            for r in results:
                if r["category"] == "LLM":
                    print(f"  {r['status']} {r['service']}")
        wait_for_enter()


def config_search_menu(config: StormConfig):
    """管理搜索引擎服务。"""
    while True:
        clear_screen()
        print_header("搜索引擎管理")

        items = [s for s in SERVICE_REGISTRY if s[0] == "搜索"]
        for i, (cat, svc, key, env, url, extra, free) in enumerate(items, 1):
            val = config.get(key)
            if free and svc == "DuckDuckGo":
                print(f"  {i}. {svc}  ✅ 免费可用 (无需配置)")
            elif free and "searXNG" in svc:
                url_val = config.get(key)
                if url_val:
                    print(f"  {i}. {svc}  ✅ {url_val}")
                else:
                    print(f"  {i}. {svc}  ⚠️ 未配置服务地址 (免费自托管)")
            elif val:
                masked = val[:8] + "..." if len(val) > 10 else "****"
                print(f"  {i}. {svc}  ✅ 已配置 ({masked})")
            else:
                print(f"  {i}. {svc}  ❌ 未配置  [{env}]")

        print()
        print("  [a] 新增/修改  [d] 删除  [t] 测试  [q] 返回主菜单")
        choice = input("\n  请选择 > ").strip().lower()

        if choice == "q":
            break
        elif choice == "a":
            idx = input("  输入服务编号: ").strip()
            if idx.isdigit() and 1 <= int(idx) <= len(items):
                _, svc, key, env, _, extra, free = items[int(idx) - 1]
                if "searxng" in key:
                    current = config.get(key)
                    hint = f" (当前: {current})" if current else ""
                    val = input(f"  searXNG 服务地址{hint}: ").strip()
                    if val:
                        config.set(key, val)
                    api_key = input(f"  API Key (无需则留空): ").strip()
                    if api_key:
                        config.set("search.searxng_api_key", api_key)
                    print("  searXNG 引擎分组配置 (可自定义):")
                    for ek in ["searxng_engines_academic", "searxng_engines_chinese", "searxng_engines_general"]:
                        cur = config.get(f"search.{ek}")
                        default = {"searxng_engines_academic": "semantic+scholar,arxiv,pubmed,google+scholar",
                                    "searxng_engines_chinese": "baidu,zhihu,bilibili",
                                    "searxng_engines_general": "google,bing,duckduckgo"}.get(ek, "")
                        val = input(f"  {ek} (默认: {default}): ").strip()
                        if val:
                            config.set(f"search.{ek}", val)
                else:
                    current = config.get(key)
                    hint = f" (当前已配置)" if current else ""
                    val = input(f"  输入 {svc} API Key{hint}: ").strip()
                    if val:
                        config.set(key, val)
                print("  ✅ 已保存")
        elif choice == "d":
            idx = input("  输入要删除的服务编号: ").strip()
            if idx.isdigit() and 1 <= int(idx) <= len(items):
                _, svc, key, *_ = items[int(idx) - 1]
                config.delete(key)
                print(f"  ✅ 已删除 {svc}")
        elif choice == "t":
            print("\n  ⏳ 正在测试...")
            results = config.diagnose()
            for r in results:
                if r["category"] == "搜索":
                    print(f"  {r['status']} {r['service']}")
        wait_for_enter()


def config_export_menu(config: StormConfig):
    """导出配置为 secrets.toml。"""
    print_header("导出配置为 secrets.toml")
    print("\n  将当前配置导出为项目级 secrets.toml 文件")
    print("  该文件将被 STORM 流水线的 load_api_key() 读取。\n")
    target = input("  输出路径 (默认: ./secrets.toml): ").strip()
    if not target:
        target = "./secrets.toml"
    config.export_secrets_toml(target)


def config_diagnostics_menu(config: StormConfig):
    """运行全量诊断。"""
    print_header("STORM 系统诊断")
    from cli.config_manager import cmd_diagnose
    cmd_diagnose(config)


def config_main_menu(config: StormConfig):
    """配置管理主菜单。"""
    while True:
        clear_screen()
        print_header("配置管理")
        print("  管理 API 密钥、搜索引擎服务连接参数\n")
        print_menu([
            ("1", "管理 LLM 密钥 (OpenAI / DeepSeek / Ollama ...)"),
            ("2", "管理搜索引擎服务 (searXNG / DuckDuckGo / Bing ...)"),
            ("3", "导出配置为 secrets.toml"),
            ("4", "全量系统诊断"),
            ("q", "返回主菜单"),
        ])
        choice = input("  请选择 > ").strip().lower()
        if choice == "1":
            config_llm_menu(config)
        elif choice == "2":
            config_search_menu(config)
        elif choice == "3":
            config_export_menu(config)
        elif choice == "4":
            config_diagnostics_menu(config)
        elif choice == "q":
            break


# ═══════════════════════════════════════════════════════════════════════════
# 流水线运行子菜单
# ═══════════════════════════════════════════════════════════════════════════

def run_pipeline_menu(config: StormConfig):
    """引导式流水线运行。"""
    print_header("运行 STORM 流水线")

    # 步骤 1: 项目名称
    project_name = input("\n  步骤 1/5: 项目名称 > ").strip()
    if not project_name:
        print("  ❌ 项目名称不能为空")
        wait_for_enter()
        return

    # 步骤 2: 素材来源
    print("\n  步骤 2/5: 素材来源")
    print("    [a] 纯互联网搜索 (无需本地素材)")
    print("    [b] 本地素材文件夹 + 互联网搜索")
    src_choice = input("  请选择 (默认 a): ").strip().lower() or "a"
    source_dir = ""
    if src_choice == "b":
        source_dir = input("  素材文件夹路径: ").strip()
        if not os.path.isdir(source_dir):
            print(f"  ⚠️ 路径不存在: {source_dir}，将仅使用互联网搜索")
            source_dir = ""

    # 步骤 3: 检索引擎
    print("\n  步骤 3/5: 选择检索引擎")
    # 检查可用引擎
    duckduckgo = config.get("search.duckduckgo_enabled")
    searxng_url = config.get("search.searxng_base_url")
    print(f"    [1] DuckDuckGo {'✅' if duckduckgo else '❌'} (免费)")
    print(f"    [2] searXNG     {'✅' if searxng_url else '❌'} ({searxng_url or '未配置'})")
    print(f"    [3] 其他 (Bing/Serper 等, 需在配置中设置)")
    engine_choice = input("  请选择 (默认 1): ").strip() or "1"

    # 步骤 4: LLM 后端
    print("\n  步骤 4/5: 选择大语言模型")
    # 自动检测可用后端
    available_llms = []
    for _, svc, key, env, _, _, free in [s for s in SERVICE_REGISTRY if s[0] == "LLM"]:
        val = config.get(key)
        if val or free:
            available_llms.append((svc, key))
    for i, (name, key) in enumerate(available_llms, 1):
        mark = "✅" if config.get(key) or "ollama" in key else "⚠️"
        print(f"    [{i}] {name} {mark}")
    llm_choice = input(f"  请选择 (1-{len(available_llms)}, 默认 1): ").strip() or "1"

    # 步骤 5: 确认
    print("\n  步骤 5/5: 确认配置")
    print(f"  ├─ 项目: {project_name}")
    print(f"  ├─ 素材: {'本地文件夹 + ' if source_dir else ''}互联网搜索")
    print(f"  ├─ 引擎: {['DuckDuckGo', 'searXNG', '其他'][int(engine_choice)-1] if engine_choice.isdigit() and 1<=int(engine_choice)<=3 else 'DuckDuckGo'}")
    print(f"  └─ LLM:  {available_llms[int(llm_choice)-1][0] if llm_choice.isdigit() and 1<=int(llm_choice)<=len(available_llms) else 'Unknown'}")
    confirm = input("\n  确认执行? (Y/n): ").strip().lower() or "y"
    if confirm != "y":
        print("  已取消")
        wait_for_enter()
        return

    # 导出配置
    config.export_secrets_toml()

    # 构造运行命令
    engine_names = {"1": "duckduckgo", "2": "searxng", "3": "bing"}
    engine = engine_names.get(engine_choice, "duckduckgo")
    llm = available_llms[int(llm_choice)-1][0] if llm_choice.isdigit() and 1 <= int(llm_choice) <= len(available_llms) else "DeepSeek"

    print(f"\n  🚀 正在启动流水线...")
    print(f"  引擎: {engine}, LLM: {llm}")

    # 输出目录
    output_dir = f"./results/{project_name.replace(' ', '_')}"
    os.makedirs(output_dir, exist_ok=True)

    # 选择对应脚本
    script_map = {
        "DeepSeek": "run_storm_wiki_deepseek.py",
        "OpenAI": "run_storm_wiki_gpt.py",
        "Ollama": "run_storm_wiki_ollama.py",
    }
    script = script_map.get(llm, "run_storm_wiki_gpt.py")
    script_path = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                                "examples", "storm_examples", script)

    if not os.path.exists(script_path):
        print(f"  ❌ 未找到示例脚本: {script_path}")
        print("  您可以手动运行流水线。")
        wait_for_enter()
        return

    # 运行
    print(f"\n  执行: python3 {script_path} ...")
    print(f"  话题: {project_name}")
    print(f"  输出: {output_dir}")
    print("\n  ⏳ 流水线运行中，请稍候...\n")

    cmd = [
        sys.executable, script_path,
        "--output-dir", output_dir,
        "--retriever", engine,
        "--do-research",
        "--do-generate-outline",
        "--do-generate-article",
        "--do-polish-article",
        "--remove-duplicate",
        "--max-conv-turn", "5",
        "--max-perspective", "3",
        "--max-thread-num", "2",
    ]
    # 对 DeepSeek 添加参数
    if llm == "DeepSeek":
        cmd.extend(["--model", "deepseek-chat"])

    try:
        proc = subprocess.Popen(cmd, text=True)
        # 注入 topic
        proc.communicate(input=f"{project_name}\n")
        print(f"\n  ✅ 流水线执行完毕")
        print(f"  输出目录: {output_dir}")
    except Exception as e:
        print(f"  ❌ 执行失败: {e}")
        print("  您可以直接运行:")
        print(f"  {' '.join(cmd)}")
        print(f"  然后在提示 Topic: 时输入: {project_name}")

    wait_for_enter()


# ═══════════════════════════════════════════════════════════════════════════
# 主菜单
# ═══════════════════════════════════════════════════════════════════════════

def main():
    config = StormConfig()

    while True:
        clear_screen()
        print("\n" + "█" * 55)
        print("  STORM 论文撰写系统 — 交互式向导")
        print("█" * 55)

        # 快速状态栏
        items = config.list_all()
        configured = sum(1 for i in items if i["configured"])
        print(f"\n  配置状态: {configured}/{len(items)} 项已配置")
        print(f"  配置文件: {config.config_path}")

        print_menu([
            ("C", "🔧 配置管理 (密钥 / 搜索引擎)"),
            ("R", "🚀 运行流水线 (引导式)"),
            ("D", "🔍 系统诊断"),
            ("E", "📤 导出 secrets.toml"),
            ("q", "退出"),
        ], "主菜单")

        choice = input("  请选择 > ").strip().lower()

        if choice == "c":
            config_main_menu(config)
        elif choice == "r":
            run_pipeline_menu(config)
        elif choice == "d":
            config_diagnostics_menu(config)
        elif choice == "e":
            config_export_menu(config)
        elif choice == "q":
            print("\n  感谢使用 STORM 交互式向导！\n")
            break


if __name__ == "__main__":
    main()
