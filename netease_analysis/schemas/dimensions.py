"""
六维度 Schema 定义

SENTIMENT: 情感分析 - 评论区的情感倾向和分布
CONTENT: 内容分析 - 讨论的主题和关键词
TEMPORAL: 时间分析 - 随时间的变化趋势
STRUCTURAL: 结构分析 - 评论区的组成结构
SOCIAL: 社交分析 - 互动特征和用户行为
LINGUISTIC: 语言分析 - 语言风格特征
"""

from dataclasses import dataclass, field
from typing import List, Dict, Any, Optional, Literal
from enum import Enum


class DimensionID(str, Enum):
    """维度ID枚举"""
    SENTIMENT = "sentiment"
    CONTENT = "content"
    TEMPORAL = "temporal"
    STRUCTURAL = "structural"
    SOCIAL = "social"
    LINGUISTIC = "linguistic"


# ===== Layer 1: 维度摘要 =====

@dataclass
class BaseDimensionSummary:
    """维度摘要基类"""
    dimension_id: str = ""
    dimension_name: str = ""
    description: str = ""
    summary: str = ""         # 核心结论（AI可直接引用）
    has_detail: bool = True   # 是否有详情可查
    method_brief: str = ""    # 方法简述

    def to_dict(self) -> dict:
        return {
            "dimension_id": self.dimension_id,
            "dimension_name": self.dimension_name,
            "description": self.description,
            "summary": self.summary,
            "has_detail": self.has_detail,
            "method_brief": self.method_brief,
        }


@dataclass
class SentimentSummary(BaseDimensionSummary):
    """情感维度摘要"""
    dimension_id: str = "sentiment"
    dimension_name: str = "情感分析"
    description: str = "评论区的情感倾向和分布"
    method_brief: str = "SnowNLP情感分析"

    # 关键指标
    polarity: Dict[str, float] = field(default_factory=dict)  # positive/neutral/negative
    mean_score: float = 0.0
    consistency: str = "medium"  # high/medium/low

    def to_dict(self) -> dict:
        base = super().to_dict()
        base["key_metrics"] = {
            "polarity": self.polarity,
            "mean_score": self.mean_score,
            "consistency": self.consistency,
        }
        return base


@dataclass
class ContentSummary(BaseDimensionSummary):
    """内容维度摘要"""
    dimension_id: str = "content"
    dimension_name: str = "内容分析"
    description: str = "评论区讨论的主题和关键词"
    method_brief: str = "TF-IDF + K-Means聚类"

    # 关键指标
    top_themes: List[Dict[str, Any]] = field(default_factory=list)
    top_keywords: List[Dict[str, Any]] = field(default_factory=list)

    def to_dict(self) -> dict:
        base = super().to_dict()
        base["key_metrics"] = {
            "top_themes": self.top_themes,
            "top_keywords": self.top_keywords,
        }
        return base


@dataclass
class TemporalSummary(BaseDimensionSummary):
    """时间维度摘要"""
    dimension_id: str = "temporal"
    dimension_name: str = "时间分析"
    description: str = "评论区随时间的变化趋势"
    method_brief: str = "按时间分组统计 + 趋势检测"

    # 关键指标
    time_span_years: float = 0.0
    activity_trend: str = "stable"  # growing/stable/declining
    inflection_points: List[Dict[str, Any]] = field(default_factory=list)
    recent_vs_early: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict:
        base = super().to_dict()
        base["key_metrics"] = {
            "time_span_years": self.time_span_years,
            "activity_trend": self.activity_trend,
            "inflection_points": self.inflection_points,
            "recent_vs_early": self.recent_vs_early,
        }
        return base


@dataclass
class StructuralSummary(BaseDimensionSummary):
    """结构维度摘要"""
    dimension_id: str = "structural"
    dimension_name: str = "结构分析"
    description: str = "评论区的组成结构"
    method_brief: str = "直接统计 + 分组对比"

    # 关键指标
    length_distribution: Dict[str, float] = field(default_factory=dict)  # short/medium/long
    hot_comment_count: int = 0
    hot_vs_normal_sentiment: Dict[str, float] = field(default_factory=dict)

    def to_dict(self) -> dict:
        base = super().to_dict()
        base["key_metrics"] = {
            "length_distribution": self.length_distribution,
            "hot_comment_count": self.hot_comment_count,
            "hot_vs_normal_sentiment": self.hot_vs_normal_sentiment,
        }
        return base


@dataclass
class SocialSummary(BaseDimensionSummary):
    """社交维度摘要"""
    dimension_id: str = "social"
    dimension_name: str = "社交分析"
    description: str = "评论区的互动特征"
    method_brief: str = "点赞分布统计 + 集中度分析"

    # 关键指标
    engagement_concentration: float = 0.0  # 前1%评论占比
    max_likes: int = 0
    median_likes: int = 0
    viral_threshold: int = 10000
    viral_count: int = 0

    def to_dict(self) -> dict:
        base = super().to_dict()
        base["key_metrics"] = {
            "engagement_concentration": self.engagement_concentration,
            "max_likes": self.max_likes,
            "median_likes": self.median_likes,
            "viral_threshold": self.viral_threshold,
            "viral_count": self.viral_count,
        }
        return base


@dataclass
class LinguisticSummary(BaseDimensionSummary):
    """语言维度摘要"""
    dimension_id: str = "linguistic"
    dimension_name: str = "语言分析"
    description: str = "评论区的语言风格特征"
    method_brief: str = "风格分类 + 模式匹配"

    # 关键指标
    dominant_style: str = "colloquial"  # formal/colloquial/literary/internet
    emoji_usage_rate: float = 0.0
    format_patterns: List[Dict[str, Any]] = field(default_factory=list)
    avg_sentence_length: float = 0.0

    def to_dict(self) -> dict:
        base = super().to_dict()
        base["key_metrics"] = {
            "dominant_style": self.dominant_style,
            "emoji_usage_rate": self.emoji_usage_rate,
            "format_patterns": self.format_patterns,
            "avg_sentence_length": self.avg_sentence_length,
        }
        return base


# ===== Layer 2: 维度详情 =====

@dataclass
class BaseDimensionDetail:
    """维度详情基类"""
    layer: int = 2
    dimension_id: str = ""
    dimension_name: str = ""

    method: Dict[str, Any] = field(default_factory=dict)
    result: Dict[str, Any] = field(default_factory=dict)
    sub_analyses: Dict[str, Any] = field(default_factory=dict)
    examples: Dict[str, Any] = field(default_factory=dict)
    data_quality: Dict[str, Any] = field(default_factory=dict)
    limitations: List[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "layer": self.layer,
            "dimension_id": self.dimension_id,
            "dimension_name": self.dimension_name,
            "method": self.method,
            "result": self.result,
            "sub_analyses": self.sub_analyses,
            "examples": self.examples,
            "data_quality": self.data_quality,
            "limitations": self.limitations,
        }


@dataclass
class SentimentDetail(BaseDimensionDetail):
    """情感维度详情"""
    dimension_id: str = "sentiment"
    dimension_name: str = "情感分析"

    def __post_init__(self):
        self.method = {
            "name": "SnowNLP情感分析",
            "description": "对每条评论计算情感分数(0-1)，0为负面，1为正面",
            "library": "snownlp",
        }
        self.limitations = [
            "SnowNLP对讽刺、反语识别能力较弱",
            "训练数据主要来自商品评论，可能不完全适用于音乐评论",
            "表情符号未纳入情感计算",
        ]


@dataclass
class ContentDetail(BaseDimensionDetail):
    """内容维度详情"""
    dimension_id: str = "content"
    dimension_name: str = "内容分析"

    def __post_init__(self):
        self.method = {
            "name": "TF-IDF关键词提取 + K-Means主题聚类",
            "description": "使用TF-IDF提取关键词，K-Means聚类识别主题",
            "libraries": ["jieba", "sklearn"],
        }
        self.limitations = [
            "主题名称由预设规则生成，可能不准确",
            "K-Means对初始中心敏感，结果可能有波动",
            "停用词表影响关键词提取结果",
        ]


@dataclass
class TemporalDetail(BaseDimensionDetail):
    """时间维度详情"""
    dimension_id: str = "temporal"
    dimension_name: str = "时间分析"

    def __post_init__(self):
        self.method = {
            "name": "时间序列分析",
            "description": "按时间分组统计各指标，检测趋势和转折点",
            "granularity": "year",
            "trend_detection": "线性回归 + 突变检测",
        }
        self.limitations = [
            "早期评论可能存在幸存者偏差",
            "时间戳精度为天，无法分析小时级模式",
            "转折点检测基于年度聚合，可能遗漏月度变化",
        ]


@dataclass
class StructuralDetail(BaseDimensionDetail):
    """结构维度详情"""
    dimension_id: str = "structural"
    dimension_name: str = "结构分析"

    def __post_init__(self):
        self.method = {
            "name": "评论结构统计",
            "description": "统计评论长度分布、热评特征、回复结构",
            "thresholds": {
                "short_comment": "<20字符",
                "medium_comment": "20-100字符",
                "long_comment": ">100字符",
            }
        }
        self.limitations = [
            "热评数量由API返回决定",
            "长度阈值为人工设定，可能不适用所有场景",
        ]


@dataclass
class SocialDetail(BaseDimensionDetail):
    """社交维度详情"""
    dimension_id: str = "social"
    dimension_name: str = "社交分析"

    def __post_init__(self):
        self.method = {
            "name": "互动分布分析",
            "description": "分析点赞分布、互动集中度、用户多样性",
            "metrics": ["likes_distribution", "gini_coefficient", "user_diversity"],
        }
        self.limitations = [
            "点赞数为快照，不反映历史变化",
            "无法区分真实点赞和刷赞",
            "用户ID可能存在匿名化处理",
        ]


@dataclass
class LinguisticDetail(BaseDimensionDetail):
    """语言维度详情"""
    dimension_id: str = "linguistic"
    dimension_name: str = "语言分析"

    def __post_init__(self):
        self.method = {
            "name": "语言风格分析",
            "description": "分析写作风格、表情使用、格式模式",
            "techniques": ["风格分类", "表情统计", "正则匹配"],
        }
        self.limitations = [
            "风格分类基于简单规则，可能不准确",
            "格式模式检测依赖正则表达式，可能遗漏变体",
            "新出现的网络用语可能未被识别",
        ]


# ===== 维度工厂 =====

DIMENSION_SUMMARIES = {
    DimensionID.SENTIMENT: SentimentSummary,
    DimensionID.CONTENT: ContentSummary,
    DimensionID.TEMPORAL: TemporalSummary,
    DimensionID.STRUCTURAL: StructuralSummary,
    DimensionID.SOCIAL: SocialSummary,
    DimensionID.LINGUISTIC: LinguisticSummary,
}

DIMENSION_DETAILS = {
    DimensionID.SENTIMENT: SentimentDetail,
    DimensionID.CONTENT: ContentDetail,
    DimensionID.TEMPORAL: TemporalDetail,
    DimensionID.STRUCTURAL: StructuralDetail,
    DimensionID.SOCIAL: SocialDetail,
    DimensionID.LINGUISTIC: LinguisticDetail,
}


def get_dimension_summary_class(dimension_id: str):
    """获取维度摘要类"""
    try:
        dim = DimensionID(dimension_id)
        return DIMENSION_SUMMARIES.get(dim)
    except ValueError:
        return None


def get_dimension_detail_class(dimension_id: str):
    """获取维度详情类"""
    try:
        dim = DimensionID(dimension_id)
        return DIMENSION_DETAILS.get(dim)
    except ValueError:
        return None


def list_available_dimensions() -> List[Dict[str, Any]]:
    """列出所有可用维度"""
    return [
        {"id": "sentiment", "name": "情感分析", "has_data": True},
        {"id": "content", "name": "内容分析", "has_data": True},
        {"id": "temporal", "name": "时间分析", "has_data": True},
        {"id": "structural", "name": "结构分析", "has_data": True},
        {"id": "social", "name": "社交分析", "has_data": True},
        {"id": "linguistic", "name": "语言分析", "has_data": True},
    ]
