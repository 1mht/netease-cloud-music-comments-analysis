"""
知识库加载器 - 统一的知识管理接口

设计原则：
1. 配置与代码分离 - 所有知识存储在JSON文件
2. 统一接口 - 所有知识通过加载器访问
3. 缓存机制 - 避免重复读取文件
4. 可扩展 - 新增知识类型只需添加JSON文件
"""

import json
import os
from typing import Dict, Any, Optional
from pathlib import Path


class KnowledgeLoader:
    """知识库加载器（单例模式）"""

    _instance = None
    _cache: Dict[str, Any] = {}

    def __new__(cls):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
        return cls._instance

    def __init__(self):
        self.config_dir = Path(__file__).parent / "config"

    def load_knowledge(self, knowledge_type: str, use_cache: bool = True) -> Dict[str, Any]:
        """
        加载指定类型的知识

        Args:
            knowledge_type: 知识类型（如 'platform_knowledge', 'cultural_context'）
            use_cache: 是否使用缓存（默认True，开发时可设False）

        Returns:
            知识字典

        Raises:
            FileNotFoundError: 知识文件不存在
            json.JSONDecodeError: JSON格式错误
        """
        # 检查缓存
        if use_cache and knowledge_type in self._cache:
            return self._cache[knowledge_type]

        # 读取JSON文件
        file_path = self.config_dir / f"{knowledge_type}.json"

        if not file_path.exists():
            raise FileNotFoundError(f"Knowledge file not found: {file_path}")

        with open(file_path, 'r', encoding='utf-8') as f:
            knowledge_data = json.load(f)

        # 缓存
        if use_cache:
            self._cache[knowledge_type] = knowledge_data

        return knowledge_data

    def reload_knowledge(self, knowledge_type: Optional[str] = None):
        """
        重新加载知识（用于热更新）

        Args:
            knowledge_type: 指定知识类型，None则重载全部
        """
        if knowledge_type:
            if knowledge_type in self._cache:
                del self._cache[knowledge_type]
                self.load_knowledge(knowledge_type, use_cache=True)
        else:
            self._cache.clear()

    def get_platform_knowledge(self) -> Dict[str, Any]:
        """获取平台知识（向后兼容接口）"""
        return self.load_knowledge('platform_knowledge')

    def get_cultural_context(self) -> Dict[str, Any]:
        """获取文化背景知识（向后兼容接口）"""
        return self.load_knowledge('cultural_context')

    def get_artist_context(self, artist_name: str) -> Optional[Dict[str, Any]]:
        """
        获取艺术家背景知识

        Args:
            artist_name: 艺术家名字

        Returns:
            艺术家背景信息，如果不存在返回None
        """
        cultural_context = self.get_cultural_context()
        artists = cultural_context.get('artist_backgrounds', {}).get('artists', {})
        return artists.get(artist_name)

    def get_slang_definition(self, keyword: str) -> Optional[Dict[str, Any]]:
        """
        获取黑话/网络用语定义

        Args:
            keyword: 关键词（如"网抑云"）

        Returns:
            定义信息，如果不存在返回None
        """
        cultural_context = self.get_cultural_context()
        keywords = cultural_context.get('platform_slang', {}).get('keywords', {})
        return keywords.get(keyword)

    def list_available_knowledge(self) -> list:
        """列出所有可用的知识文件"""
        if not self.config_dir.exists():
            return []

        json_files = list(self.config_dir.glob("*.json"))
        return [f.stem for f in json_files]


# 全局加载器实例
_loader = KnowledgeLoader()


# 便捷函数（向后兼容）
def get_platform_domain_knowledge() -> Dict[str, Any]:
    """获取平台领域知识（向后兼容旧接口）"""
    return _loader.get_platform_knowledge()


def get_cultural_knowledge() -> Dict[str, Any]:
    """获取文化背景知识"""
    return _loader.get_cultural_context()


def get_artist_background(artist_name: str) -> Optional[Dict[str, Any]]:
    """获取艺术家背景"""
    return _loader.get_artist_context(artist_name)


def reload_all_knowledge():
    """重新加载所有知识（热更新）"""
    _loader.reload_knowledge()
