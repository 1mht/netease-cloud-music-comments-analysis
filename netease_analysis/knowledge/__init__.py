"""
领域知识库模块

架构说明：
- config/*.json: 纯数据配置文件（可热更新）
- knowledge_loader.py: 统一加载器
- 向后兼容: 旧的导入路径仍然有效

使用方式：
>>> from netease_analysis.knowledge import get_platform_domain_knowledge
>>> knowledge = get_platform_domain_knowledge()
"""

from .knowledge_loader import (
    get_platform_domain_knowledge,
    get_cultural_knowledge,
    get_artist_background,
    reload_all_knowledge,
    KnowledgeLoader
)

__all__ = [
    'get_platform_domain_knowledge',
    'get_cultural_knowledge',
    'get_artist_background',
    'reload_all_knowledge',
    'KnowledgeLoader'
]
