"""
数据质量信号 Schema

定义数据质量评估、采样信息等数据结构
"""

from dataclasses import dataclass, field
from typing import List, Optional, Literal
from enum import Enum


class QualityLevel(str, Enum):
    """数据质量级别"""
    HIGH = "high"         # 样本量充足，时间覆盖完整
    MEDIUM = "medium"     # 样本量适中，可能有偏差
    LOW = "low"           # 样本量不足，结论需谨慎


class TimeCoverage(str, Enum):
    """时间覆盖范围"""
    FULL = "full"           # 完整覆盖歌曲生命周期
    PARTIAL = "partial"     # 部分覆盖
    RECENT_ONLY = "recent_only"  # 仅近期数据


@dataclass
class DataQuality:
    """
    数据质量评估

    用于 Layer 0 中的 quality 字段
    """
    level: QualityLevel
    sample_ratio: float           # 采样比例 (实际分析数/总数)
    time_coverage: TimeCoverage
    warnings: List[str] = field(default_factory=list)

    # 详细指标
    total_comments: int = 0       # API报告的总评论数
    sampled_comments: int = 0     # 实际分析的评论数
    unique_users: Optional[int] = None  # 唯一用户数（如有）

    def to_dict(self) -> dict:
        return {
            "level": self.level.value,
            "sample_ratio": round(self.sample_ratio, 4),
            "time_coverage": self.time_coverage.value,
            "warnings": self.warnings,
            "total_comments": self.total_comments,
            "sampled_comments": self.sampled_comments,
            "unique_users": self.unique_users,
        }

    @classmethod
    def evaluate(cls, total: int, sampled: int, years_covered: float = 0) -> "DataQuality":
        """
        根据数据情况自动评估质量

        Args:
            total: 总评论数
            sampled: 采样评论数
            years_covered: 时间跨度（年）
        """
        warnings = []

        # 计算采样比例
        ratio = sampled / total if total > 0 else 0

        # 评估时间覆盖
        if years_covered >= 3:
            time_cov = TimeCoverage.FULL
        elif years_covered >= 1:
            time_cov = TimeCoverage.PARTIAL
        else:
            time_cov = TimeCoverage.RECENT_ONLY
            warnings.append("时间覆盖不足1年，可能存在时效性偏差")

        # 评估质量级别
        if sampled >= 500 and ratio >= 0.05:
            level = QualityLevel.HIGH
        elif sampled >= 100 and ratio >= 0.01:
            level = QualityLevel.MEDIUM
            if sampled < 300:
                warnings.append(f"样本量偏小({sampled}条)，部分统计可能不稳定")
        else:
            level = QualityLevel.LOW
            warnings.append(f"样本量不足({sampled}条)，结论需谨慎解读")

        return cls(
            level=level,
            sample_ratio=ratio,
            time_coverage=time_cov,
            warnings=warnings,
            total_comments=total,
            sampled_comments=sampled,
        )


@dataclass
class SamplingInfo:
    """
    采样信息（透明展示）

    v0.7.1+ 自动采样时的详细信息
    """
    auto_sampled: bool = False
    strategy: str = "full"        # full / stratified_v2.2 / random

    # 分层采样详情
    hot_count: int = 0            # 热评数量
    recent_count: int = 0         # 最新评论数量
    historical_count: int = 0     # 历史分层数量
    total_unique: int = 0         # 去重后总数

    # 时间覆盖
    years_covered: int = 0
    year_list: List[int] = field(default_factory=list)

    note: str = ""

    def to_dict(self) -> dict:
        return {
            "auto_sampled": self.auto_sampled,
            "strategy": self.strategy,
            "hot_count": self.hot_count,
            "recent_count": self.recent_count,
            "historical_count": self.historical_count,
            "total_unique": self.total_unique,
            "years_covered": self.years_covered,
            "year_list": self.year_list,
            "note": self.note,
        }


# ===== 常量定义 =====

# 样本量阈值
DEGRADED_MODE_THRESHOLD = 5      # <=5条：降级模式（不分析）
MIN_VIABLE_SIZE = 30             # 30条：极低置信度
RECOMMENDED_SIZE = 100           # 100条：正常置信度
MAX_ANALYSIS_SIZE = 5000         # 5000条：内存安全上限

# Workflow 强制校验
WORKFLOW_MIN_REQUIRED = 500      # 低于此值触发自动采样（Cochran公式建议384，加安全系数）

# 时间分析阈值
TIMELINE_MIN_COMMENTS = 100      # 时间线分析最低评论数
TIMELINE_MIN_YEARS = 2           # 时间线分析最低覆盖年数


def assess_confidence(sample_size: int) -> str:
    """
    根据样本量评估置信度

    Returns:
        "extremely_low" / "low" / "normal" / "high"
    """
    if sample_size <= DEGRADED_MODE_THRESHOLD:
        return "degraded"  # 无法分析
    elif sample_size < MIN_VIABLE_SIZE:
        return "extremely_low"
    elif sample_size < RECOMMENDED_SIZE:
        return "low"
    elif sample_size < 500:
        return "normal"
    else:
        return "high"
