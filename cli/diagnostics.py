#!/usr/bin/env python3
"""
STORM 系统诊断工具

独立的诊断脚本，供 CLI 直接调用。
提供环境检查、API 连接测试、依赖完整性检查。

用法:
  python3 -m cli.diagnostics
  python3 -m cli.diagnostics --quick
  python3 -m cli.diagnostics --output report.json
"""

import argparse
import json
import os
import subprocess
import sys
from datetime import datetime


def check_python():
    """检查 Python 环境。"""
    info = {
        "python_version": sys.version,
        "executable": sys.executable,
    }
    print(f"  ✅ Python {sys.version.split()[0]}")
    return info


def check_dependencies():
    """检查核心依赖是否可导入。"""
    deps = ["dspy", "openai", "litellm", "sentence_transformers", "duckduckgo_search"]
    results = {}
    for dep in deps:
        try:
            __import__(dep)
            results[dep] = True
            print(f"  ✅ {dep}")
        except ImportError:
            results[dep] = False
            print(f"  ❌ {dep}")
    return results


def check_env_vars():
    """检查环境变量。"""
    env_vars = [
        "OPENAI_API_KEY", "DEEPSEEK_API_KEY", "ANTHROPIC_API_KEY",
        "GOOGLE_API_KEY", "GROQ_API_KEY",
        "BING_SEARCH_API_KEY", "YDC_API_KEY", "SERPER_API_KEY",
        "BRAVE_API_KEY", "TAVILY_API_KEY",
    ]
    results = {}
    for var in env_vars:
        val = os.getenv(var)
        results[var] = bool(val)
        if val:
            print(f"  ✅ {var} 已设置 ({val[:8]}...)")
        else:
            print(f"  ❌ {var} 未设置")
    return results


def check_storm_package():
    """检查 STORM 包自身。"""
    try:
        from knowledge_storm import STORMWikiRunner, STORMWikiLMConfigs
        print(f"  ✅ STORMWikiRunner 可导入")
        return True
    except ImportError as e:
        print(f"  ❌ STORM 导入失败: {e}")
        return False


def check_example_scripts():
    """检查示例脚本语法。"""
    script_dir = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                              "examples", "storm_examples")
    if not os.path.isdir(script_dir):
        print(f"  ❌ 示例脚本目录不存在: {script_dir}")
        return {}
    
    results = {}
    for fname in sorted(os.listdir(script_dir)):
        if fname.endswith(".py"):
            fpath = os.path.join(script_dir, fname)
            try:
                import py_compile
                py_compile.compile(fpath, doraise=True)
                results[fname] = True
                print(f"  ✅ {fname}")
            except py_compile.PyCompileError:
                results[fname] = False
                print(f"  ❌ {fname} (语法错误)")
    return results


def check_output_dir():
    """检查输出目录。"""
    results_dir = os.path.join(os.getcwd(), "results")
    if os.path.isdir(results_dir):
        subdirs = [d for d in os.listdir(results_dir) if os.path.isdir(os.path.join(results_dir, d))]
        print(f"  ✅ results/ 目录存在，含 {len(subdirs)} 个子项目")
        for d in subdirs:
            print(f"     └─ {d}")
    else:
        print(f"  ℹ️  results/ 目录不存在（首次运行时会自动创建）")


def run_diagnose(quick: bool = False) -> dict:
    """运行全量诊断。"""
    report = {
        "timestamp": datetime.now().isoformat(),
        "cwd": os.getcwd(),
        "checks": {},
    }

    print("\n" + "=" * 50)
    print("  STORM 系统诊断")
    print("=" * 50)

    print("\n┌─ Python 环境 ──────────────────────┐")
    report["python"] = check_python()

    if not quick:
        print("\n┌─ 依赖检查 ─────────────────────────┐")
        report["dependencies"] = check_dependencies()

        print("\n┌─ 环境变量 ─────────────────────────┐")
        report["env_vars"] = check_env_vars()

    print("\n┌─ STORM 包 ─────────────────────────┐")
    report["storm_package"] = check_storm_package()

    if not quick:
        print("\n┌─ 示例脚本 ─────────────────────────┐")
        report["example_scripts"] = check_example_scripts()

        print("\n┌─ 输出目录 ─────────────────────────┐")
        check_output_dir()

    # 尝试从 config_manager 加载配置诊断
    try:
        sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
        from cli.config_manager import StormConfig
        config = StormConfig()
        print("\n┌─ 配置诊断 ─────────────────────────┐")
        results = config.diagnose()
        report["config"] = []
        for r in results:
            report["config"].append(r)
            print(f"  {r['status']} {r['service']}")

        total = len(results)
        ok = sum(1 for r in results if r["status"].startswith("✅"))
        warn = sum(1 for r in results if r["status"].startswith("⚠️"))
        err = sum(1 for r in results if r["status"].startswith("❌"))
        print(f"\n  总计: {total} | ✅ {ok} | ⚠️ {warn} | ❌ {err}")
    except ImportError:
        print("\n┌─ 配置诊断 ─────────────────────────┐")
        print("  ℹ️  config_manager 不可用，跳过")
    except Exception as e:
        print(f"\n  ❌ 配置诊断异常: {e}")

    print("\n" + "=" * 50)
    print("  诊断完成")
    print("=" * 50)

    return report


def main():
    parser = argparse.ArgumentParser(description="STORM 系统诊断工具")
    parser.add_argument("--quick", action="store_true", help="快速诊断（跳过依赖和示例检查）")
    parser.add_argument("--output", type=str, help="输出 JSON 报告路径")
    args = parser.parse_args()

    report = run_diagnose(quick=args.quick)

    if args.output:
        with open(args.output, "w", encoding="utf-8") as f:
            json.dump(report, f, ensure_ascii=False, indent=2)
        print(f"\n报告已保存到: {args.output}")


if __name__ == "__main__":
    main()
