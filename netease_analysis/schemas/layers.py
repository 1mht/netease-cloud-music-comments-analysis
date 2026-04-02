"""
分层输出架构 Schema

Layer 0: 元摘要 (~200 tokens)
Layer 1: 维度摘要 (~600 tokens)
Layer 2: 维度详情 (~500 tokens/维度)
Layer 3: 原始数据 (按需)
"""

from dataclasses import dataclass, field
from typing import List, Dict, Any, Optional, Union
from datetime import datetime

from .quality import DataQuality, SamplingInfo
from .dimensions import (
    DimensionID,
    SentimentSummary,
    ContentSummary,
    TemporalSummary,
    StructuralSummary,
    SocialSummary,
    LinguisticSummary,
    list_available_dimensions,
)


# ===== Layer 0: 元摘要 =====

@dataclass
class SongInfo:
    """歌曲基本信息"""
    id: str
    name: str
    artist: str = ""
    album: str = ""

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "name": self.name,
            "artist": self.artist,
            "album": self.album,
        }


@dataclass
class DataOverview:
    """数据概况"""
    total_comments: int           # API报告的总数
    sampled_comments: int         # 实际分析的数量
    sampling_method: str          # 采样方法
    time_range: Dict[str, str] = field(default_factory=dict)  # earliest/latest

    def to_dict(self) -> dict:
        return {
            "total_comments": self.total_comments,
            "sampled_comments": self.sampled_comments,
            "sampling_method": self.sampling_method,
            "time_range": self.time_range,
        }


@dataclass
class Highlight:
    """关键发现"""
    dimension: str
    finding: str

    def to_dict(self) -> dict:
        return {
            "dimension": self.dimension,
            "finding": self.finding,
        }


@dataclass
class ContextNote:
    """知识注解（条件触发）"""
    trigger: str              # 触发条件
    note: str                 # 注解内容
    source: str = ""          # 来源
    confidence: str = "medium"  # high/medium/low

    def to_dict(self) -> dict:
        return {
            "trigger": self.trigger,
            "note": self.note,
            "source": self.source,
            "confidence": self.confidence,
        }


@dataclass
class Layer0Meta:
    """
    Layer 0: 元摘要

    ~200 tokens，包含数据质量、事实压缩、可用维度列表
    AI用来：快速判断情况，决定是否深入
    """
    song: SongInfo
    data: DataOverview
    quality: DataQuality
    summary: str                              # 事实压缩（基于数据的陈述）
    highlights: List[Highlight] = field(default_factory=list)  # 关键发现（最多3条）
    available_dimensions: List[Dict[str, Any]] = field(default_factory=list)
    context_notes: List[ContextNote] = field(default_factory=list)  # 知识注解

    layer: int = 0
    type: str = "meta_summary"

    def __post_init__(self):
        if not self.available_dimensions:
            self.available_dimensions = list_available_dimensions()

    def to_dict(self) -> dict:
        return {
            "layer": self.layer,
            "type": self.type,
            "song": self.song.to_dict(),
            "data": self.data.to_dict(),
            "quality": self.quality.to_dict(),
            "summary": self.summary,
            "highlights": [h.to_dict() for h in self.highlights],
            "available_dimensions": self.available_dimensions,
            "context_notes": [n.to_dict() for n in self.context_notes],
        }


# ===== Layer 1: 维度摘要 =====

@dataclass
class Layer1Summary:
    """
    Layer 1: 维度摘要

    ~600 tokens (6维度×100)，每个维度的核心结论和关键指标
    AI用来：跨维度推理，综合分析
    """
    dimensions: Dict[str, Any] = field(default_factory=dict)

    layer: int = 1
    type: str = "dimension_summaries"

    def set_dimension(self, dimension_id: str, summary_data: dict):
        """设置某个维度的摘要"""
        self.dimensions[dimension_id] = summary_data

    def get_dimension(self, dimension_id: str) -> Optional[dict]:
        """获取某个维度的摘要"""
        return self.dimensions.get(dimension_id)

    def to_dict(self) -> dict:
        return {
            "layer": self.layer,
            "type": self.type,
            "dimensions": self.dimensions,
        }


# ===== Layer 2: 维度详情 =====

@dataclass
class Layer2Detail:
    """
    Layer 2: 维度详情

    ~500 tokens/维度，完整的方法、结果、子分析、局限性
    AI用来：回答用户追问，解释分析方法
    """
    dimension_id: str
    dimension_name: str
    method: Dict[str, Any] = field(default_factory=dict)
    result: Dict[str, Any] = field(default_factory=dict)
    sub_analyses: Dict[str, Any] = field(default_factory=dict)
    examples: Dict[str, Any] = field(default_factory=dict)
    data_quality: Dict[str, Any] = field(default_factory=dict)
    limitations: List[str] = field(default_factory=list)

    layer: int = 2

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


# ===== Layer 3: 原始数据 =====

@dataclass
class CommentAnnotation:
    """评论标注（来自Layer 1/2的计算结果）"""
    sentiment_score: float = 0.5
    sentiment_label: str = "neutral"
    matched_theme: str = ""
    matched_keywords: List[str] = field(default_factory=list)
    length_category: str = "medium"
    has_emoji: bool = False
    detected_patterns: List[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "sentiment_score": self.sentiment_score,
            "sentiment_label": self.sentiment_label,
            "matched_theme": self.matched_theme,
            "matched_keywords": self.matched_keywords,
            "length_category": self.length_category,
            "has_emoji": self.has_emoji,
            "detected_patterns": self.detected_patterns,
        }


@dataclass
class RawComment:
    """原始评论"""
    id: str
    content: str
    time: str                    # ISO格式时间
    likes: int = 0
    annotations: Optional[CommentAnnotation] = None
    user: Dict[str, str] = field(default_factory=dict)

    def to_dict(self) -> dict:
        result = {
            "id": self.id,
            "content": self.content,
            "time": self.time,
            "likes": self.likes,
        }
        if self.annotations:
            result["annotations"] = self.annotations.to_dict()
        if self.user:
            result["user"] = self.user
        return result


@dataclass
class MatchStats:
    """匹配统计"""
    total_in_sample: int         # 样本总数
    matched_count: int           # 符合条件的数量
    returned_count: int          # 实际返回的数量
    match_ratio: float = 0.0     # 匹配比例

    def to_dict(self) -> dict:
        return {
            "total_in_sample": self.total_in_sample,
            "matched_count": self.matched_count,
            "returned_count": self.returned_count,
            "match_ratio": round(self.match_ratio, 4),
        }


@dataclass
class Layer3Raw:
    """
    Layer 3: 原始数据

    原始评论，支持条件筛选
    AI用来：引用具体例子，验证假设，展示证据
    """
    request: Dict[str, Any]                   # 请求信息（song_id + filter）
    match_stats: MatchStats
    comments: List[RawComment] = field(default_factory=list)
    aggregate: Dict[str, Any] = field(default_factory=dict)  # 聚合统计（可选）
    data_quality: Dict[str, Any] = field(default_factory=dict)

    layer: int = 3
    type: str = "raw_comments"

    def to_dict(self) -> dict:
        return {
            "layer": self.layer,
            "type": self.type,
            "request": self.request,
            "match_stats": self.match_stats.to_dict(),
            "comments": [c.to_dict() for c in self.comments],
            "aggregate": self.aggregate,
            "data_quality": self.data_quality,
        }


# ===== 组合响应 =====

@dataclass
class LayerResponse:
    """
    分层响应（analyze_comments_comprehensive 的返回值）

    默认返回 Layer 0 + Layer 1
    """
    layer_0: Layer0Meta
    layer_1: Layer1Summary
    sampling_info: Optional[SamplingInfo] = None

    status: str = "success"
    schema_version: str = "0.7.3"

    def to_dict(self) -> dict:
        result = {
            "status": self.status,
            "schema_version": self.schema_version,
            "layer_0": self.layer_0.to_dict(),
            "layer_1": self.layer_1.to_dict(),
        }
        if self.sampling_info:
            result["sampling_info"] = self.sampling_info.to_dict()
        return result


# ===== Layer 3 筛选条件 =====

@dataclass
class Layer3Filter:
    """
    Layer 3 筛选条件

    支持多维度组合筛选
    """
    # 情感筛选
    sentiment: Optional[str] = None           # positive/neutral/negative/all
    sentiment_range: Optional[tuple] = None   # (0.8, 1.0)

    # 主题筛选
    theme: Optional[str] = None

    # 关键词筛选
    keyword: Optional[str] = None
    keywords_any: Optional[List[str]] = None
    keywords_all: Optional[List[str]] = None

    # 时间筛选
    time_range: Optional[Dict[str, str]] = None  # {"start": "2020-01-01", "end": "2020-12-31"}
    year: Optional[int] = None

    # 互动筛选
    min_likes: Optional[int] = None
    is_hot: Optional[bool] = None
    is_viral: Optional[bool] = None  # >10000赞

    # 结构筛选
    length: Optional[str] = None      # short/medium/long
    min_length: Optional[int] = None

    # 语言筛选
    has_emoji: Optional[bool] = None
    style: Optional[str] = None
    has_pattern: Optional[str] = None

    # 排序和限制
    sort_by: str = "likes"            # likes/time/sentiment/length
    sort_order: str = "desc"          # asc/desc
    limit: int = 20
    offset: int = 0

    def to_dict(self) -> dict:
        """转为字典（只包含非None值）"""
        result = {}
        for key, value in self.__dict__.items():
            if value is not None:
                result[key] = value
        return result

    @classmethod
    def from_dict(cls, data: dict) -> "Layer3Filter":
        """从字典创建"""
        return cls(**{k: v for k, v in data.items() if hasattr(cls, k)})
