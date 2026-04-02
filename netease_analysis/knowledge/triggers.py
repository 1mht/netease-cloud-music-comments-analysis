"""
v0.7.3 知识注解触发系统

条件触发 + 来源标注 + 可信度

设计原则：
- 不对数据下判断，只提供背景知识
- 让AI决定是否引用这些知识
- 所有注解都有来源标注
"""

import os
import json
import logging
import re
from typing import List, Dict, Any, Optional
from datetime import datetime

logger = logging.getLogger(__name__)

# 配置路径
current_dir = os.path.dirname(os.path.abspath(__file__))
TRIGGERS_CONFIG_PATH = os.path.join(current_dir, "triggers.json")


class KnowledgeTrigger:
    """知识注解触发器"""

    def __init__(self, config_path: str = None):
        """
        初始化触发器

        Args:
            config_path: 配置文件路径（默认使用内置配置）
        """
        self.config_path = config_path or TRIGGERS_CONFIG_PATH
        self.rules = self._load_rules()

    def _load_rules(self) -> Dict[str, Any]:
        """加载触发规则"""
        try:
            with open(self.config_path, "r", encoding="utf-8") as f:
                return json.load(f)
        except FileNotFoundError:
            logger.warning(f"触发规则文件未找到: {self.config_path}，使用默认规则")
            return self._default_rules()
        except Exception as e:
            logger.error(f"加载触发规则失败: {e}")
            return self._default_rules()

    def _default_rules(self) -> Dict[str, Any]:
        """默认规则"""
        return {
            "keyword_triggers": [
                {
                    "keywords": ["网抑云", "抑云"],
                    "min_count": 5,
                    "note": "2020年'网抑云'现象影响评论区风格",
                    "source": "网易云社区现象",
                    "confidence": "high",
                    "category": "cultural_phenomenon"
                },
                {
                    "keywords": ["爷青回", "爷的青春"],
                    "min_count": 10,
                    "note": "怀旧情绪流行语，反映用户年龄层和文化认同",
                    "source": "网络流行语",
                    "confidence": "medium",
                    "category": "cultural_phenomenon"
                },
                {
                    "keywords": ["DNA动了"],
                    "min_count": 3,
                    "note": "表示被触动产生共鸣，2021年流行语",
                    "source": "网络流行语",
                    "confidence": "medium",
                    "category": "cultural_phenomenon"
                }
            ],
            "temporal_triggers": [
                {
                    "condition": "year_2020_sentiment_drop",
                    "threshold": -0.1,
                    "note": "2020年情感下降可能与疫情期间社会情绪相关",
                    "source": "社会背景",
                    "confidence": "medium",
                    "category": "temporal_context"
                },
                {
                    "condition": "long_tail_nostalgia",
                    "threshold_years": 5,
                    "note": "老歌评论区以怀旧情绪为主，反映歌曲的时代意义",
                    "source": "音乐社区规律",
                    "confidence": "high",
                    "category": "temporal_context"
                }
            ],
            "content_triggers": [
                {
                    "condition": "nostalgia_dominant",
                    "threshold": 0.3,
                    "note": "怀旧主题占比高，评论区以追忆青春为主",
                    "source": "内容分析",
                    "confidence": "high",
                    "category": "content_pattern"
                },
                {
                    "condition": "high_story_ratio",
                    "threshold": 0.2,
                    "note": "故事型评论占比高，用户倾向分享个人经历",
                    "source": "结构分析",
                    "confidence": "medium",
                    "category": "content_pattern"
                }
            ],
            "social_triggers": [
                {
                    "condition": "high_engagement_concentration",
                    "threshold": 0.7,
                    "note": "互动高度集中，存在'抢热评'文化",
                    "source": "社交分析",
                    "confidence": "high",
                    "category": "social_pattern"
                }
            ]
        }

    def check_triggers(
        self,
        comments: List[Any] = None,
        dimensions_data: Dict[str, Any] = None,
        song_info: Dict[str, Any] = None
    ) -> List[Dict[str, Any]]:
        """
        检查所有触发条件

        Args:
            comments: 评论列表（用于关键词触发）
            dimensions_data: 维度分析结果（用于分析结果触发）
            song_info: 歌曲信息

        Returns:
            触发的知识注解列表
        """
        triggered_notes = []

        # 1. 关键词触发
        if comments:
            keyword_notes = self._check_keyword_triggers(comments)
            triggered_notes.extend(keyword_notes)

        # 2. 时间触发
        if dimensions_data:
            temporal_notes = self._check_temporal_triggers(dimensions_data)
            triggered_notes.extend(temporal_notes)

            # 3. 内容触发
            content_notes = self._check_content_triggers(dimensions_data)
            triggered_notes.extend(content_notes)

            # 4. 社交触发
            social_notes = self._check_social_triggers(dimensions_data)
            triggered_notes.extend(social_notes)

        # 去重并按置信度排序
        seen = set()
        unique_notes = []
        for note in triggered_notes:
            key = note.get("note", "")
            if key not in seen:
                seen.add(key)
                unique_notes.append(note)

        # 按置信度排序
        confidence_order = {"high": 0, "medium": 1, "low": 2}
        unique_notes.sort(key=lambda x: confidence_order.get(x.get("confidence", "low"), 2))

        return unique_notes[:5]  # 最多返回5条

    def _check_keyword_triggers(self, comments: List[Any]) -> List[Dict]:
        """检查关键词触发"""
        notes = []

        # 合并所有评论内容
        all_text = " ".join(
            getattr(c, 'content', '') or c.get('content', '') if isinstance(c, dict) else getattr(c, 'content', '')
            for c in comments
        )

        for rule in self.rules.get("keyword_triggers", []):
            keywords = rule.get("keywords", [])
            min_count = rule.get("min_count", 1)

            # 统计关键词出现次数
            count = sum(all_text.count(kw) for kw in keywords)

            if count >= min_count:
                notes.append({
                    "trigger": f"检测到关键词: {', '.join(keywords)} ({count}次)",
                    "note": rule.get("note", ""),
                    "source": rule.get("source", ""),
                    "confidence": rule.get("confidence", "medium"),
                    "category": rule.get("category", "unknown")
                })

        return notes

    def _check_temporal_triggers(self, dimensions_data: Dict) -> List[Dict]:
        """检查时间触发"""
        notes = []

        temporal_data = dimensions_data.get("temporal", ({}, {}))[0]
        if not temporal_data:
            return notes

        key_metrics = temporal_data.get("key_metrics", {})
        inflection_points = key_metrics.get("inflection_points", [])

        for rule in self.rules.get("temporal_triggers", []):
            condition = rule.get("condition", "")

            # 2020年情感下降
            if condition == "year_2020_sentiment_drop":
                for ip in inflection_points:
                    if ip.get("year") == 2020 and ip.get("change", 0) <= rule.get("threshold", -0.1):
                        notes.append({
                            "trigger": f"2020年情感下降 {ip.get('change', 0):.2f}",
                            "note": rule.get("note", ""),
                            "source": rule.get("source", ""),
                            "confidence": rule.get("confidence", "medium"),
                            "category": rule.get("category", "temporal_context")
                        })
                        break

            # 长尾怀旧阶段
            elif condition == "long_tail_nostalgia":
                time_span = key_metrics.get("time_span_years", 0)
                if time_span >= rule.get("threshold_years", 5):
                    notes.append({
                        "trigger": f"歌曲时间跨度 {time_span:.1f} 年",
                        "note": rule.get("note", ""),
                        "source": rule.get("source", ""),
                        "confidence": rule.get("confidence", "medium"),
                        "category": rule.get("category", "temporal_context")
                    })

        return notes

    def _check_content_triggers(self, dimensions_data: Dict) -> List[Dict]:
        """检查内容触发"""
        notes = []

        content_data = dimensions_data.get("content", ({}, {}))[0]
        if not content_data:
            return notes

        key_metrics = content_data.get("key_metrics", {})
        top_themes = key_metrics.get("top_themes", [])

        for rule in self.rules.get("content_triggers", []):
            condition = rule.get("condition", "")

            # 怀旧主题占主导
            if condition == "nostalgia_dominant":
                for theme in top_themes:
                    if theme.get("name") == "怀旧" and theme.get("percentage", 0) >= rule.get("threshold", 0.3):
                        notes.append({
                            "trigger": f"怀旧主题占比 {theme.get('percentage', 0):.1%}",
                            "note": rule.get("note", ""),
                            "source": rule.get("source", ""),
                            "confidence": rule.get("confidence", "medium"),
                            "category": rule.get("category", "content_pattern")
                        })
                        break

        return notes

    def _check_social_triggers(self, dimensions_data: Dict) -> List[Dict]:
        """检查社交触发"""
        notes = []

        social_data = dimensions_data.get("social", ({}, {}))[0]
        if not social_data:
            return notes

        key_metrics = social_data.get("key_metrics", {})

        for rule in self.rules.get("social_triggers", []):
            condition = rule.get("condition", "")

            # 高互动集中度
            if condition == "high_engagement_concentration":
                concentration = key_metrics.get("engagement_concentration", 0)
                if concentration >= rule.get("threshold", 0.7):
                    notes.append({
                        "trigger": f"互动集中度 {concentration:.1%}",
                        "note": rule.get("note", ""),
                        "source": rule.get("source", ""),
                        "confidence": rule.get("confidence", "medium"),
                        "category": rule.get("category", "social_pattern")
                    })

        return notes


# ===== 全局单例 =====

_default_trigger = None


def get_trigger() -> KnowledgeTrigger:
    """获取默认触发器（单例）"""
    global _default_trigger
    if _default_trigger is None:
        _default_trigger = KnowledgeTrigger()
    return _default_trigger


def check_knowledge_triggers(
    comments: List[Any] = None,
    dimensions_data: Dict[str, Any] = None,
    song_info: Dict[str, Any] = None
) -> List[Dict[str, Any]]:
    """
    便捷函数：检查知识触发

    Args:
        comments: 评论列表
        dimensions_data: 维度分析结果
        song_info: 歌曲信息

    Returns:
        触发的知识注解列表
    """
    trigger = get_trigger()
    return trigger.check_triggers(comments, dimensions_data, song_info)


# ===== 导出 =====

__all__ = [
    "KnowledgeTrigger",
    "get_trigger",
    "check_knowledge_triggers",
]
