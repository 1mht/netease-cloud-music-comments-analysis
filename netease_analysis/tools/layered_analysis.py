"""
v0.8.5 分层分析工具 - 渐进式数据加载

设计原则：
- 每个 Layer 是独立的工具调用
- AI 在每层之间做决策
- 省 token、去噪音

Layer 架构：
- Layer 0: get_analysis_overview - 数据边界（AI第一眼）
- Layer 1: get_analysis_signals - 六维度信号（AI第二眼）
- Layer 2: get_analysis_samples - 验证样本（AI第三眼）
- Layer 2.5: search_comments_by_keyword - DB内关键词检索（用于验证）
- Layer 3: get_raw_comments - 原始评论（按需）

v0.8.5 新增：
- 每个 Layer 返回 deeper_options 字段
- 用户可以强制 AI 深入分析特定方向
- AI 初次可自行决定深度，但用户有最终控制权
"""

import sys
import os
import logging
from datetime import datetime
from typing import List, Dict, Any, Optional
from collections import defaultdict

# 添加路径
current_dir = os.path.dirname(os.path.abspath(__file__))
project_root = os.path.dirname(os.path.dirname(current_dir))
netease_path = os.path.join(project_root, "netease_cloud_music")
if netease_path not in sys.path:
    sys.path.insert(0, netease_path)

from database import init_db, Song, Comment
from netease_analysis.tools.workflow_errors import workflow_error

logger = logging.getLogger(__name__)

# 常量
MAX_ANALYSIS_SIZE = 5000


def get_session():
    """获取数据库session"""
    db_path = os.path.join(project_root, "data", "music_data_v2.db")
    return init_db(f"sqlite:///{db_path}")


# ============================================================
# Layer 0: 数据概览
# ============================================================


def get_analysis_overview(song_id: str) -> Dict[str, Any]:
    """
    Layer 0: 数据概览 - AI 第一眼看这里

    v0.8.6: 只展示数据边界，不做采样决策
    采样决策在 Layer 1 之后，根据各维度的 data_sufficiency 评估

    返回数据边界信息，帮助 AI 判断：
    - 数据量是否足够？
    - 覆盖范围是否合理？

    Args:
        song_id: 歌曲ID

    Returns:
        {
            "status": "success",
            "layer": 0,
            "song_info": {...},
            "data_boundary": {
                "db_count": 1234,
                "api_total": 50000,
                "coverage": "2.47%",
                "coverage_ratio": 0.0247,
                "year_span": "2015-01-01 ~ 2024-12-25",
                "years_covered": 10,
                "year_distribution": {...}
            },
            "quality_assessment": {...},
            "ai_guidance": {...},
            "sampling_note": "采样决策在 Layer 1 之后..."
        }
    """
    session = get_session()

    try:
        # 1. 获取歌曲
        song = session.query(Song).filter_by(id=song_id).first()
        if not song:
            return workflow_error("song_not_found", "get_analysis_overview")

        # 2. 统计数据库评论
        db_count = session.query(Comment).filter_by(song_id=song_id).count()
        if db_count == 0:
            return workflow_error("no_comments", "get_analysis_overview")

        comments = (
            session.query(Comment)
            .filter_by(song_id=song_id)
            .limit(MAX_ANALYSIS_SIZE)
            .all()
        )

        # 3. 获取 API 总量
        api_total = 0
        try:
            from netease_analysis.tools.pagination_sampling import (
                get_real_comments_count_from_api,
            )

            api_result = get_real_comments_count_from_api(song_id)
            api_total = api_result.get("total_comments", 0) if api_result else 0
        except Exception as e:
            logger.warning(f"获取API总量失败: {e}")

        # 4. 计算时间跨度和年份分布
        year_distribution = defaultdict(int)
        timestamps = []

        for c in comments:
            ts = getattr(c, "timestamp", 0) or 0
            if ts > 0:
                timestamps.append(ts)
                year = datetime.fromtimestamp(ts / 1000).year
                year_distribution[year] += 1

        year_distribution = dict(sorted(year_distribution.items()))

        if timestamps:
            min_ts, max_ts = min(timestamps), max(timestamps)
            earliest = datetime.fromtimestamp(min_ts / 1000).strftime("%Y-%m-%d")
            latest = datetime.fromtimestamp(max_ts / 1000).strftime("%Y-%m-%d")
            year_span = f"{earliest} ~ {latest}"
        else:
            year_span = "unknown"

        # 5. 覆盖率计算
        coverage = f"{db_count / api_total * 100:.2f}%" if api_total > 0 else "unknown"
        coverage_ratio = db_count / api_total if api_total > 0 else 0

        # 6. 数据量检查
        MIN_REQUIRED_FOR_ANALYSIS = 100

        if db_count < MIN_REQUIRED_FOR_ANALYSIS:
            return {
                "status": "must_sample_first",
                "layer": 0,
                "song_info": {
                    "id": song_id,
                    "name": song.name,
                    "artist": song.artists[0].name if song.artists else "Unknown",
                },
                "db_count": db_count,
                "min_required": MIN_REQUIRED_FOR_ANALYSIS,
            }

        return {
            "status": "success",
            "layer": 0,
            "song_info": {
                "id": song_id,
                "name": song.name,
                "artist": song.artists[0].name if song.artists else "Unknown",
                "album": song.album.name if song.album else "",
            },
            "data_boundary": {
                "db_count": db_count,
                "api_total": api_total,
                "coverage": coverage,
                "coverage_ratio": coverage_ratio,
                "year_span": year_span,
                "years_covered": len(year_distribution),
                "year_distribution": year_distribution,
            },
        }

    except Exception as e:
        logger.error(f"Layer 0 分析失败: {e}", exc_info=True)
        return {
            "status": "error",
            "error_type": "layer0_failed",
            "message": str(e),
            "song_id": song_id,
        }

    finally:
        session.close()


# ============================================================
# Layer 1: 六维度信号
# ============================================================


def get_analysis_signals(song_id: str) -> Dict[str, Any]:
    """
    Layer 1: 六维度信号 - AI 第二眼看这里

    返回六个维度的量化指标和异常信号，帮助 AI 判断：
    - 哪些维度有异常需要关注？
    - 哪些信号需要通过样本验证？

    Args:
        song_id: 歌曲ID

    Returns:
        {
            "status": "success",
            "layer": 1,
            "dimensions": {
                "sentiment": {"metrics": {...}, "signals": [...], "level": "good"},
                "content": {...},
                "temporal": {...},
                "structural": {...},
                "social": {...},
                "linguistic": {...}
            },
            "cross_dimension_signals": [...],
            "signals_summary": {
                "total": 5,
                "needs_verification": ["反讽信号", "时间异常"]
            },
            "ai_guidance": {...}
        }
    """
    session = get_session()

    try:
        # 1. 获取歌曲
        song = session.query(Song).filter_by(id=song_id).first()
        if not song:
            return workflow_error("song_not_found", "get_analysis_signals")

        # 2. 获取评论
        comments = (
            session.query(Comment)
            .filter_by(song_id=song_id)
            .limit(MAX_ANALYSIS_SIZE)
            .all()
        )
        if not comments:
            return workflow_error("no_comments", "get_analysis_signals")

        # 2.5 v0.8.7: 强制检查 - 数据量不足时阻断
        MIN_REQUIRED_FOR_ANALYSIS = 100
        comment_count = len(comments)

        if comment_count < MIN_REQUIRED_FOR_ANALYSIS:
            return {
                "status": "must_sample_first",
                "layer": 1,
                "db_count": comment_count,
                "min_required": MIN_REQUIRED_FOR_ANALYSIS,
            }

        # 3. 分析所有维度
        from netease_analysis.tools.dimension_analyzers import analyze_all_dimensions

        dimensions_result = analyze_all_dimensions(comments)

        # 4. 提取跨维度信号
        from netease_analysis.tools.cross_dimension import detect_cross_signals

        cross_signals = detect_cross_signals(dimensions_result, comments)

        # 5. 提取各维度核心指标和信号（简化版，不含样本）
        dimensions_summary = {}
        all_signals = []

        for dim_name, dim_data in dimensions_result.items():
            if dim_name == "anchor_contrast_samples":
                continue  # 样本在 Layer 2 返回

            qf = dim_data.get("quantified_facts", {})
            signals = dim_data.get("signals", [])
            data_suff = dim_data.get("data_sufficiency", {})

            dimensions_summary[dim_name] = {
                "sample_size": qf.get("sample_size", 0),
                "data_sufficiency": data_suff,
                "metrics": qf.get("metrics", {}),
                "signals": signals,
            }

            for sig in signals:
                all_signals.append({"source": dim_name, "signal": sig})

        total_signals = len(all_signals) + len(cross_signals)

        return {
            "status": "success",
            "layer": 1,
            "dimensions": dimensions_summary,
            "cross_dimension_signals": [
                {
                    "signal_id": sig.get("signal_id", ""),
                    "fact": sig.get("fact", ""),
                    "possible_reasons": sig.get("possible_reasons", []),
                }
                for sig in cross_signals
            ],
            "signals_summary": {
                "total": total_signals,
                "from_dimensions": len(all_signals),
                "cross_dimension": len(cross_signals),
            },
        }

    except Exception as e:
        logger.error(f"Layer 1 分析失败: {e}", exc_info=True)
        return {
            "status": "error",
            "error_type": "layer1_failed",
            "message": str(e),
            "song_id": song_id,
        }

    finally:
        session.close()


# ============================================================
# Layer 2: 验证样本
# ============================================================


def get_analysis_samples(
    song_id: str, focus_dimensions: List[str] = None
) -> Dict[str, Any]:
    """
    Layer 2: 验证样本 - AI 第三眼看这里

    返回锚点样本和对比样本，帮助 AI：
    - 验证 Layer 1 发现的信号
    - 判断算法是否误判
    - 理解评论区真实氛围

    Args:
        song_id: 歌曲ID
        focus_dimensions: 重点关注的维度（可选）

    Returns:
        {
            "status": "success",
            "layer": 2,
            "anchors": {
                "most_liked": [...],
                "earliest": [...],
                "latest": [...],
                "longest": [...]
            },
            "contrast": {
                "high_likes_low_score": [...],
                "low_likes_but_long": [...]
            },
            "verification_tasks": [...],
            "ai_guidance": {...}
        }
    """
    session = get_session()

    try:
        # 1. 获取歌曲
        song = session.query(Song).filter_by(id=song_id).first()
        if not song:
            return workflow_error("song_not_found", "get_analysis_samples")

        # 2. 获取评论
        comments = (
            session.query(Comment)
            .filter_by(song_id=song_id)
            .limit(MAX_ANALYSIS_SIZE)
            .all()
        )
        if not comments:
            return workflow_error("no_comments", "get_analysis_samples")

        # 3. 分析维度以获取样本
        from netease_analysis.tools.dimension_analyzers import analyze_all_dimensions

        dimensions_result = analyze_all_dimensions(comments)

        # 4. 提取锚点和对比样本
        anchor_contrast = dimensions_result.get("anchor_contrast_samples", {})

        anchors_raw = anchor_contrast.get("anchors", {})
        contrast_raw = anchor_contrast.get("contrast", {})

        # 5. 格式化样本（只保留关键信息）
        def format_sample(s):
            """格式化单个样本"""
            if isinstance(s, str):
                # 如果是字符串，返回简单结构
                return {
                    "content": s[:200],
                    "likes": 0,
                    "date": "",
                    "algorithm_score": None,
                }
            if isinstance(s, dict):
                return {
                    "content": s.get("content", "")[:200],
                    "likes": s.get("likes", 0),
                    "date": s.get("date", ""),
                    "algorithm_score": s.get("algorithm_score", s.get("score", None)),
                }
            return {
                "content": str(s)[:200],
                "likes": 0,
                "date": "",
                "algorithm_score": None,
            }

        # anchors 的结构：{purpose, most_liked, earliest, latest, longest, note}
        # 只提取样本列表字段
        anchor_keys = ["most_liked", "earliest", "latest", "longest"]
        formatted_anchors = {}
        for key in anchor_keys:
            samples = anchors_raw.get(key, [])
            if samples and isinstance(samples, list):
                formatted_anchors[key] = [format_sample(s) for s in samples[:5]]

        # contrast 的结构：{purpose, high_likes_low_score, low_likes_but_long, note}
        contrast_keys = ["high_likes_low_score", "low_likes_but_long"]
        formatted_contrast = {}
        for key in contrast_keys:
            samples = contrast_raw.get(key, [])
            if samples and isinstance(samples, list):
                formatted_contrast[key] = [format_sample(s) for s in samples[:5]]

        # 6. 构建验证任务
        verification_tasks = []

        if formatted_contrast.get("high_likes_low_score"):
            verification_tasks.append(
                {
                    "task": "验证高赞低分样本",
                    "question": "这些高赞但算法低分的评论是：反讽/玩梗？诗意表达？还是真实负面？",
                    "samples_key": "contrast.high_likes_low_score",
                }
            )

        if formatted_anchors.get("most_liked"):
            verification_tasks.append(
                {
                    "task": "分析高赞共鸣",
                    "question": "最高赞评论反映了什么共鸣？与歌曲主题相关吗？",
                    "samples_key": "anchors.most_liked",
                }
            )

        if formatted_anchors.get("earliest") and formatted_anchors.get("latest"):
            verification_tasks.append(
                {
                    "task": "对比早期vs最新",
                    "question": "评论区氛围有变化吗？早期和最新评论风格是否不同？",
                    "samples_key": "anchors.earliest vs anchors.latest",
                }
            )

        anchor_count = sum(len(v) for v in formatted_anchors.values())
        contrast_count = sum(len(v) for v in formatted_contrast.values())

        return {
            "status": "success",
            "layer": 2,
            "anchors": formatted_anchors,
            "contrast": formatted_contrast,
            "sample_counts": {
                "anchors": anchor_count,
                "contrast": contrast_count,
                "total": anchor_count + contrast_count,
            },
        }

    except Exception as e:
        logger.error(f"Layer 2 分析失败: {e}", exc_info=True)
        return {
            "status": "error",
            "error_type": "layer2_failed",
            "message": str(e),
            "song_id": song_id,
        }

    finally:
        session.close()


# ============================================================
# Layer 2.5: 关键词检索（DB内验证工具）
# ============================================================


def search_comments_by_keyword(
    song_id: str,
    keyword: str,
    limit: int = 20,
    min_likes: int = 0,
) -> Dict[str, Any]:
    """在数据库中检索包含指定关键词的评论。

    设计目标：
    - 用于验证 Layer 1 的“关键词异常”是否真实存在
    - 避免把 TF-IDF 权重误读为“占比”

    注意：这里是子串匹配，不做分词/同义词扩展。
    """
    session = get_session()

    try:
        song = session.query(Song).filter_by(id=song_id).first()
        if not song:
            return workflow_error("song_not_found", "search_comments_by_keyword")

        kw = (keyword or "").strip()
        if not kw:
            return {
                "status": "error",
                "error_type": "invalid_keyword",
                "message": "keyword 不能为空",
                "song_id": song_id,
            }

        query = (
            session.query(Comment)
            .filter_by(song_id=song_id)
            .filter(Comment.content.contains(kw))
        )

        if min_likes > 0:
            query = query.filter(Comment.liked_count >= min_likes)

        total = query.count()

        rows = query.order_by(Comment.liked_count.desc()).limit(limit).all()

        results = []
        for c in rows:
            ts = getattr(c, "timestamp", 0) or 0
            date_str = None
            year = None
            if ts > 0:
                dt = datetime.fromtimestamp(ts / 1000)
                year = dt.year
                date_str = dt.strftime("%Y-%m-%d")

            content = getattr(c, "content", "") or ""
            results.append(
                {
                    "id": str(getattr(c, "comment_id", "")),
                    "content": content[:200],
                    "likes": getattr(c, "liked_count", 0) or 0,
                    "year": year,
                    "date": date_str,
                    "user": getattr(c, "user_nickname", ""),
                }
            )

        return {
            "status": "success",
            "song_id": song_id,
            "song_name": song.name,
            "keyword": kw,
            "filter": {"min_likes": min_likes, "limit": limit},
            "match_total": total,
            "count": len(results),
            "comments": results,
            "note": "DB substring search; use for verification",
        }

    finally:
        session.close()


# ============================================================
# Layer 3: 原始评论 (已有 get_raw_comments)
# ============================================================

# 从 comprehensive_analysis.py 导入
from netease_analysis.tools.comprehensive_analysis import get_raw_comments


# ============================================================
# 导出
# ============================================================

__all__ = [
    "get_analysis_overview",  # Layer 0
    "get_analysis_signals",  # Layer 1
    "get_analysis_samples",  # Layer 2
    "search_comments_by_keyword",  # Layer 2.5
    "get_raw_comments",  # Layer 3
]
