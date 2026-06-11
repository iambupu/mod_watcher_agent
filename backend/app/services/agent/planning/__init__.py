# 中文注释：标记 planning 包，保证后端模块可以按包路径导入。

from app.services.agent.planning.query_diagnosis import diagnose_query

__all__ = ["diagnose_query"]
