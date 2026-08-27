"""
STORM (Synthesis of Topic Outlines through Retrieval and Multi-perspective Question Asking)
"""

# 基础数据结构与轻量工具直接导出
try:
    from .dataclass import *
    from .utils import *
    from .reranker import *
    from .encoder import *
except Exception:
    pass

# 重型传统模块进行保护性导入（避免阻塞轻量 async_core 运行）
try:
    from .storm_wiki import *
    from .collaborative_storm import *
    from .interface import *
    from .lm import *
    from .rm import *
except ImportError:
    # 当未安装 dspy 或重型依赖时，不阻塞根包与 async_core 的使用
    pass

# 导出现代异步内核
try:
    from . import async_core
except Exception:
    pass

__version__ = "1.2.0"
