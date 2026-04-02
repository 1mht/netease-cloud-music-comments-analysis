"""
平台知识模块（已废弃，保留用于向后兼容）

新架构：
- 知识数据存储在 config/*.json
- 通过 knowledge_loader.py 统一加载
- 本文件仅作为兼容层

请使用：
from netease_analysis.knowledge import get_platform_domain_knowledge
"""

from .knowledge_loader import get_platform_domain_knowledge

__all__ = ['get_platform_domain_knowledge']
