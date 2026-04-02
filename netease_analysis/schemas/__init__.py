"""
v0.7.3 分层证据架构 Schema 定义

Layer 0: 元摘要 (~200 tokens) - 数据质量 + 事实压缩 + 可用维度
Layer 1: 维度摘要 (~600 tokens) - 6维度的核心结论
Layer 2: 维度详情 (~500 tokens/维度) - 完整方法、结果、局限性
Layer 3: 原始数据 (按需) - 原始评论 + 条件筛选

设计原则:
- 工具提供证据，AI负责推理
- Token高效，按需深入
- 向后兼容
"""

from .layers import (
    Layer0Meta,
    Layer1Summary,
    Layer2Detail,
    Layer3Raw,
    LayerResponse,
)

from .dimensions import (
    DimensionID,
    SentimentSummary,
    ContentSummary,
    TemporalSummary,
    StructuralSummary,
    SocialSummary,
    LinguisticSummary,
    SentimentDetail,
    ContentDetail,
    TemporalDetail,
    StructuralDetail,
    SocialDetail,
    LinguisticDetail,
)

from .quality import (
    QualityLevel,
    DataQuality,
    SamplingInfo,
    TimeCoverage,
    DEGRADED_MODE_THRESHOLD,
    MIN_VIABLE_SIZE,
    RECOMMENDED_SIZE,
    MAX_ANALYSIS_SIZE,
    WORKFLOW_MIN_REQUIRED,
    TIMELINE_MIN_COMMENTS,
    TIMELINE_MIN_YEARS,
    assess_confidence,
)

from .dimensions import (
    get_dimension_summary_class,
    get_dimension_detail_class,
    list_available_dimensions,
)

from .layers import (
    Layer3Filter,
)

__all__ = [
    # Layers
    "Layer0Meta",
    "Layer1Summary",
    "Layer2Detail",
    "Layer3Raw",
    "LayerResponse",
    # Dimensions
    "DimensionID",
    "SentimentSummary",
    "ContentSummary",
    "TemporalSummary",
    "StructuralSummary",
    "SocialSummary",
    "LinguisticSummary",
    "SentimentDetail",
    "ContentDetail",
    "TemporalDetail",
    "StructuralDetail",
    "SocialDetail",
    "LinguisticDetail",
    # Quality
    "QualityLevel",
    "DataQuality",
    "SamplingInfo",
]

__version__ = "0.7.3"
