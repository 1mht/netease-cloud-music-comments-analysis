"""
v0.7.6 综合分析工具（透明化版）

核心改进：
- v0.7.5: 移除隐含判断、增强反讽检测
- v0.7.6: 数据透明度报告、采样过程可追踪

工具：
1. analyze_comments_v2() - 返回透明化的六维度分析
2. get_raw_comments() - 获取原始评论（AI往下看）
"""

import sys
import os
import logging
from datetime import datetime
from typing import List, Dict, Any, Optional

# 添加路径
current_dir = os.path.dirname(os.path.abspath(__file__))
project_root = os.path.dirname(os.path.dirname(current_dir))
netease_path = os.path.join(project_root, "netease_cloud_music")
if netease_path not in sys.path:
    sys.path.insert(0, netease_path)

from database import init_db, Song, Comment
from netease_analysis.tools.workflow_errors import workflow_error
from netease_analysis.tools.dimension_analyzers import analyze_all_dimensions
from netease_analysis.tools.data_transparency import (
    create_transparency_report,
    assess_sample_adequacy,
    N_MIN_STANDARD,
)
from netease_analysis.tools.cross_dimension import detect_cross_signals

logger = logging.getLogger(__name__)

# 常量
MAX_ANALYSIS_SIZE = 5000
WORKFLOW_MIN_REQUIRED = 100  # 最少需要100条评论才能进行可靠分析


def get_session():
    """获取数据库session"""
    db_path = os.path.join(project_root, "data", "music_data_v2.db")
    return init_db(f"sqlite:///{db_path}")


def analyze_comments_v2(
    song_id: str,
    include_dimensions: List[str] = None,
    auto_sample: bool = True,
    sampling_level: str = "standard",  # v0.8.2: 采样程度选择 (fast/standard/deep)
) -> Dict[str, Any]:
    """
    综合分析工具 v0.8.2

    输出格式变更：
    - 每个维度包含: algorithm_assessment, quantified_facts, samples, signals
    - algorithm_assessment 是"假设"，AI可验证/推翻
    - samples 按目的组织，便于AI验证

    Args:
        song_id: 歌曲ID
        include_dimensions: 要包含的维度（默认全部6个）
        auto_sample: 数据不足时是否自动采样
        sampling_level: 采样程度 (v0.8.2新增)
            - "fast": 快速预览（~30s，~500条）
            - "standard": 标准模式（~60s，~1000条）
            - "deep": 深度采样（~120s，~2000条）

    Returns:
        {
            "status": "success",
            "schema_version": "0.7.5",
            "meta": {...},           # 元信息
            "dimensions": {...},     # 六维度分析结果
            "cross_dimension_signals": [...],  # 跨维度信号
            "sampling_report": {...} # 采样报告（如有）
        }
    """
    session = get_session()

    try:
        # ===== 1. 获取歌曲 =====
        song = session.query(Song).filter_by(id=song_id).first()
        if not song:
            return workflow_error("song_not_found", "analyze_comments_v2")

        # ===== 2. 获取评论 =====
        comments = (
            session.query(Comment)
            .filter_by(song_id=song_id)
            .limit(MAX_ANALYSIS_SIZE)
            .all()
        )
        total_count = session.query(Comment).filter_by(song_id=song_id).count()

        if not comments:
            return workflow_error("no_comments", "analyze_comments_v2")

        sampled_count = len(comments)
        sampling_report = None

        # ===== 3. 采样决策（v0.8.2: 智能决策，按维度评估） =====
        from netease_analysis.tools.sampling_decision import (
            smart_sampling_decision,
            execute_smart_sampling,
        )

        smart_decision = smart_sampling_decision(song_id)
        sampling_need = smart_decision.get("sampling_need", {})
        dimension_status = smart_decision.get("dimension_status", {})

        # 判断是否需要采样
        action = sampling_need.get("action", "sufficient")
        triggered = action in ["need_sampling", "recommend_sampling"]

        # 构建采样决策（v0.8.2白盒化：展示所有六维度的评估状态）
        sampling_decision = {
            "db_count": total_count,
            "action": action,
            "triggered": triggered,
            "reason": sampling_need.get("reason", ""),
            # v0.8.2白盒化：显示所有六个维度的完整状态（不只是不足的）
            "dimension_evaluation": {
                dim: {
                    "level": status.get("level", "unknown"),
                    "current": status.get("current", ""),
                    "reason": status.get("reason", ""),
                    "can_improve": status.get("can_improve", True),
                }
                for dim, status in dimension_status.items()
            },
            # 可改善的不足维度
            "improvable_insufficient": sampling_need.get("improvable_insufficient", []),
        }

        # ===== 4. 自动采样（v0.8.2: 按维度需求补充采样） =====
        if auto_sample and triggered:
            try:
                from netease_analysis.tools.sampling_v5 import (
                    sample_comments_v5,
                    SamplingConfig,
                )
                from netease_analysis.tools.pagination_sampling import (
                    get_real_comments_count_from_api,
                )
                from collections import defaultdict
                # datetime已在文件顶部导入

                # v0.8.2: 根据用户选择的采样程度创建配置
                sampling_config = SamplingConfig.from_speed(sampling_level)
                sampling_decision["sampling_level"] = sampling_level
                sampling_decision["sampling_config"] = {
                    "target_samples": sampling_config.target_samples,
                    "max_requests": sampling_config.max_requests,
                    "max_time_seconds": sampling_config.max_time_seconds,
                }

                # 获取API总量
                api_result = get_real_comments_count_from_api(song_id)
                api_total = api_result.get("total_comments", 0) if api_result else 0
                sampling_decision["api_total"] = api_total

                # v0.8.2: 检测缺失年份（针对temporal维度）
                target_years = None
                if "temporal" in sampling_need.get("improvable_insufficient", []):
                    # 统计当前数据库中各年份的评论数
                    year_counts = defaultdict(int)
                    for c in comments:
                        ts = getattr(c, "timestamp", 0) or 0
                        if ts:
                            year = datetime.fromtimestamp(ts / 1000).year
                            year_counts[year] += 1

                    # 找出缺失或不足的年份（样本数 < 10）
                    current_year = datetime.now().year
                    earliest_year = min(year_counts.keys()) if year_counts else 2013
                    missing_years = []
                    for year in range(earliest_year, current_year + 1):
                        if year_counts.get(year, 0) < 10:
                            missing_years.append(year)

                    if missing_years:
                        target_years = missing_years
                        sampling_decision["target_years"] = missing_years
                        logger.info(f"[采样] 检测到缺失/不足年份: {missing_years}")

                # 执行采样（使用用户选择的配置）
                sample_result = sample_comments_v5(
                    song_id=song_id,
                    api_total=api_total,
                    save_to_db=True,
                    config=sampling_config,
                    target_years=target_years,
                )

                if sample_result:
                    # 重新获取评论
                    comments = (
                        session.query(Comment)
                        .filter_by(song_id=song_id)
                        .limit(MAX_ANALYSIS_SIZE)
                        .all()
                    )
                    sampled_count = len(comments)

                    meta = sample_result.get("meta", {})
                    sampling_report = {
                        "auto_sampled": True,
                        "strategy": f"v5.0_{meta.get('stop_reason', 'unknown')}",
                        "n_actual": sample_result.get("total_unique"),
                        "samples_saved": sample_result.get("samples_saved"),
                        "stop_reason": meta.get("stop_reason"),
                        "time_coverage": meta.get("time_coverage_note"),
                        "meta": meta,
                    }

                    # 更新采样决策信息
                    actual_sampled = sample_result.get("total_unique", 0)
                    coverage_rate = (
                        (actual_sampled / api_total * 100) if api_total > 0 else 0
                    )
                    sampling_decision.update(
                        {
                            "sampled_count": actual_sampled,
                            "coverage_rate": f"{coverage_rate:.2f}%",
                            "db_after_sampling": sampled_count,
                        }
                    )

                    logger.info(
                        f"[采样] 完成! 新增{sample_result.get('samples_saved')}条"
                    )

            except Exception as e:
                logger.warning(f"[采样] 失败: {e}")

        # ===== 4. 分析所有维度（v2格式） =====
        dimensions_result = analyze_all_dimensions(comments)

        # ===== 5. 构建元信息 =====
        timestamps = [
            getattr(c, "timestamp", 0) or 0
            for c in comments
            if getattr(c, "timestamp", 0)
        ]
        if timestamps:
            min_ts, max_ts = min(timestamps), max(timestamps)
            earliest = (
                datetime.fromtimestamp(min_ts / 1000).strftime("%Y-%m-%d")
                if min_ts > 0
                else "unknown"
            )
            latest = (
                datetime.fromtimestamp(max_ts / 1000).strftime("%Y-%m-%d")
                if max_ts > 0
                else "unknown"
            )
            years_covered = (
                round((max_ts - min_ts) / (1000 * 60 * 60 * 24 * 365), 1)
                if min_ts > 0
                else 0
            )
        else:
            earliest, latest, years_covered = "unknown", "unknown", 0

        # v0.8.2: 从评论中统计年份分布（无论是否触发采样都输出）
        year_distribution = {}
        for c in comments:
            ts = getattr(c, "timestamp", 0) or 0
            if ts > 0:
                year = datetime.fromtimestamp(ts / 1000).year
                year_distribution[year] = year_distribution.get(year, 0) + 1
        # 按年份排序
        year_distribution = dict(sorted(year_distribution.items()))

        # 数据质量评估
        if sampled_count >= 300:
            quality_level = "good"
        elif sampled_count >= 100:
            quality_level = "acceptable"
        else:
            quality_level = "limited"

        meta = {
            "song": {
                "id": song_id,
                "name": song.name,
                "artist": song.artists[0].name if song.artists else "Unknown",
                "album": song.album.name if song.album else "",
            },
            "data": {
                "total_in_db": total_count,
                "analyzed_count": sampled_count,
                "time_range": {
                    "earliest": earliest,
                    "latest": latest,
                    "years_covered": years_covered,
                },
                # v0.8.2: 始终输出年份分布
                "year_distribution": year_distribution,
            },
            "quality": {
                "level": quality_level,
                "note": _quality_note(quality_level, sampled_count),
            },
        }

        # ===== 6. v0.8.2: 使用新的跨维度信号检测 =====
        cross_signals_v2 = detect_cross_signals(dimensions_result, comments)
        # 向后兼容：转换为字符串列表
        cross_signals = []
        for sig in cross_signals_v2:
            desc = sig.get("description", "")
            task = sig.get("ai_task", "")
            if desc:
                cross_signals.append(f"[{sig.get('signal_name', '')}] {desc}")
        # 保留详细信号供AI使用
        cross_signals_detailed = cross_signals_v2

        # ===== 7. 筛选维度 =====
        if include_dimensions:
            dimensions_result = {
                k: v for k, v in dimensions_result.items() if k in include_dimensions
            }

        # ===== 8. v0.7.6: 创建透明度报告 =====
        api_total = None
        if sampling_report:
            api_total = sampling_report.get("api_total")
        elif hasattr(song, "api_total_comments_snapshot"):
            api_total = song.api_total_comments_snapshot

        transparency = create_transparency_report(
            song_id=song_id,
            db_count=sampled_count,
            api_total=api_total,
            sampling_occurred=sampling_report is not None,
            sampling_details=sampling_report,
        )

        # ===== 9. v0.8.2: 提取锚点/对比样本 =====
        anchor_contrast_samples = dimensions_result.pop("anchor_contrast_samples", None)

        # ===== 10. v0.8.3: 构建诱导式返回结构 =====
        # 核心设计：字段顺序 = AI阅读顺序

        # Step 1: 数据概览（AI第一眼看这里）
        data_info = meta.get("data", {})
        year_dist = data_info.get("year_distribution", {})
        api_total = sampling_decision.get("api_total", 0)
        db_count = sampling_decision.get("db_count", 0)
        coverage = f"{db_count / api_total * 100:.2f}%" if api_total > 0 else "未知"

        step1_data_overview = {
            "db_count": db_count,
            "api_total": api_total,
            "coverage": coverage,
            "year_span": f"{data_info.get('time_range', {}).get('earliest', '?')} ~ {data_info.get('time_range', {}).get('latest', '?')}",
            "years_covered": len(year_dist),
            "quality": data_info.get("quality_level", "unknown"),
            "ai_note": "覆盖率<1%时结论需谨慎，采样可能有偏差"
            if api_total > 0 and db_count / api_total < 0.01
            else "数据量可接受",
        }

        # Step 2: 提取需要验证的信号（AI第二眼看这里）
        step2_signals_to_verify = []
        for sig in cross_signals_detailed:
            step2_signals_to_verify.append(
                {
                    "signal": sig.get("fact", sig.get("description", "")),
                    "source": sig.get("signal_name", "cross_dimension"),
                    "action": sig.get("ai_action", "阅读step3样本验证"),
                }
            )
        # 从各维度提取signals
        for dim_name, dim_data in dimensions_result.items():
            for signal_text in dim_data.get("signals", []):
                step2_signals_to_verify.append(
                    {
                        "signal": signal_text,
                        "source": dim_name,
                        "action": f"查看{dim_name}维度样本验证",
                    }
                )

        # Step 3: 验证样本（AI第三眼看这里）
        step3_verification_samples = {}
        if anchor_contrast_samples:
            step3_verification_samples["anchors"] = anchor_contrast_samples.get(
                "anchors", {}
            )
            step3_verification_samples["contrast"] = anchor_contrast_samples.get(
                "contrast", {}
            )
            step3_verification_samples["ai_task"] = {
                "high_likes_low_score": "判断：反讽/玩梗 OR 诗意表达 OR 深情感慨 OR 真实负面？",
                "anchors.most_liked": "这些高赞评论反映了什么共鸣？",
                "anchors.earliest_vs_latest": "评论区氛围有变化吗？",
            }

        # 构建最终结果（顺序即阅读顺序）
        result = {
            "status": "success",
            "schema_version": "0.8.3",
            # ===== AI按顺序阅读 =====
            "step1_data_overview": step1_data_overview,
            "step2_signals_to_verify": step2_signals_to_verify,
            "step3_verification_samples": step3_verification_samples,
            # ===== 需要深入时看 =====
            "step4_if_needed": {
                "action": "调用 get_raw_comments_tool(song_id, year=X, min_likes=Y)",
                "when": "step3样本不足以下结论时",
            },
            # ===== 详细数据（备查）=====
            "details": {
                "meta": meta,
                "dimensions": dimensions_result,
                "sampling_decision": sampling_decision,
                "transparency": transparency,
            },
        }

        if sampling_report:
            result["details"]["sampling_report"] = sampling_report

        return result

    except Exception as e:
        logger.error(f"v2分析失败: {e}", exc_info=True)
        return {
            "status": "error",
            "error_type": "analysis_failed",
            "message": str(e),
            "song_id": song_id,
        }

    finally:
        session.close()


def _quality_note(level: str, count: int) -> str:
    """生成数据质量说明"""
    notes = {
        "good": f"样本量{count}条，统计结果可信",
        "acceptable": f"样本量{count}条，结果可参考但置信度有限",
        "limited": f"样本量仅{count}条，结果仅供参考，建议增加采样",
    }
    return notes.get(level, "")


def _extract_cross_dimension_signals(dimensions: Dict[str, dict]) -> List[str]:
    """
    提取跨维度信号

    检测各维度之间的关联和矛盾
    v0.7.6: 增强反讽/玩梗文化检测
    """
    signals = []

    sentiment = dimensions.get("sentiment", {})
    social = dimensions.get("social", {})
    temporal = dimensions.get("temporal", {})
    content = dimensions.get("content", {})
    linguistic = dimensions.get("linguistic", {})

    # 信号1: 反讽检测 (v0.7.7改进版 - 使用高赞中低分占比)
    sent_qf = sentiment.get("quantified_facts", {})
    sent_stats = sent_qf.get("statistics", {})

    hot_mean = sent_stats.get("hot_mean", 0)
    normal_mean = sent_stats.get("normal_mean", 0)
    hot_low_score_ratio = sent_stats.get("hot_low_score_ratio", 0)
    hot_count = sent_stats.get("hot_count", 0)

    # v0.7.7: 用高赞中低分占比检测反讽
    if hot_count >= 5 and hot_low_score_ratio >= 0.2:
        signals.append(
            f"⚠️ 强反讽信号：高赞评论中{int(hot_low_score_ratio * 100)}%是算法低分(<=0.3)，"
            f"高赞内容很可能是反讽/玩梗/假骂真夸。"
            f"【AI必须阅读sentiment维度的high_likes_low_score样本，不要信任算法情感分数】"
        )
    elif hot_count >= 5 and hot_low_score_ratio >= 0.1:
        signals.append(
            f"中等反讽风险：高赞评论中{int(hot_low_score_ratio * 100)}%是算法低分，请AI验证高赞内容"
        )
    elif hot_mean > 0 and normal_mean > 0:
        gap = normal_mean - hot_mean
        if gap > 0.15:
            signals.append(
                f"热评情感({hot_mean:.2f})低于普通评论({normal_mean:.2f})，可能存在反讽/调侃评论"
            )
        elif hot_mean > normal_mean + 0.15:
            signals.append(
                f"热评情感({hot_mean:.2f})高于普通评论({normal_mean:.2f})，正面评论更容易获得认同"
            )

    # 信号1.5: 短评占比高 + 热评情感低 = 玩梗文化
    ling_qf = linguistic.get("quantified_facts", {})
    short_ratio = (
        ling_qf.get("metrics", {}).get("type_distribution", {}).get("Short", 0)
    )

    if short_ratio > 0.7 and hot_mean < 0.4:
        signals.append(
            f"玩梗文化特征：短评占{int(short_ratio * 100)}% + 热评情感低({hot_mean:.2f})，"
            f"评论区可能充斥复读/梗/互动式评论，情感分数不可靠"
        )

    # 信号2: 时间异常与内容主题关联
    temporal_qf = temporal.get("quantified_facts", {})
    anomaly_years = temporal_qf.get("metrics", {}).get("anomaly_years", [])
    content_qf = content.get("quantified_facts", {})
    themes = content_qf.get("metrics", {}).get("themes", [])

    if anomaly_years and themes:
        top_theme = themes[0] if themes else {}
        for ay in anomaly_years:
            year = ay.get("year")
            ratio = ay.get("ratio", 1)
            if year and ratio > 2:
                signals.append(
                    f"{year}年评论量异常激增({ratio}倍)，主题以'{top_theme.get('name', '未知')}'为主，"
                    f"可能与特定事件相关（需AI结合背景知识分析）"
                )
                break

    # 信号3: 低样本量警告
    for dim_id, dim_result in dimensions.items():
        qf = dim_result.get("quantified_facts", {})
        sample_size = qf.get("sample_size", 0)
        if sample_size < 50:
            signals.append(f"{dim_id}维度样本量仅{sample_size}条，结果置信度较低")

    return signals


def get_dimension_samples_v2(
    song_id: str, dimension: str, purpose: str = None
) -> Dict[str, Any]:
    """
    获取指定维度的样本详情

    Args:
        song_id: 歌曲ID
        dimension: 维度ID (sentiment/content/temporal/structural/social/linguistic)
        purpose: 样本目的筛选 (for_algorithm_verification/for_content_understanding等)

    Returns:
        指定维度的样本数据
    """
    result = analyze_comments_v2(song_id, include_dimensions=[dimension])

    if result.get("status") != "success":
        return result

    dim_result = result.get("dimensions", {}).get(dimension, {})
    samples = dim_result.get("samples", {})

    if purpose and purpose in samples:
        return {
            "status": "success",
            "dimension": dimension,
            "purpose": purpose,
            "samples": samples[purpose],
        }

    return {"status": "success", "dimension": dimension, "all_samples": samples}


def get_raw_comments(
    song_id: str, year: int = None, min_likes: int = 0, limit: int = 20
) -> Dict[str, Any]:
    """
    获取原始评论（让AI往下看）

    Args:
        song_id: 歌曲ID
        year: 筛选年份（用于分析时间异常）
        min_likes: 最低点赞数
        limit: 返回条数

    Returns:
        原始评论列表
    """
    session = get_session()

    try:
        query = session.query(Comment).filter_by(song_id=song_id)

        # 年份筛选：必须在 SQL 层完成，否则“先取高赞再按年过滤”会导致空结果
        if year is not None:
            start_ts = int(datetime(year, 1, 1).timestamp() * 1000)
            end_ts = int(datetime(year + 1, 1, 1).timestamp() * 1000)
            query = query.filter(
                Comment.timestamp >= start_ts, Comment.timestamp < end_ts
            )

        if min_likes > 0:
            query = query.filter(Comment.liked_count >= min_likes)

        comments = query.order_by(Comment.liked_count.desc()).limit(limit).all()

        results = []
        for c in comments:
            ts = getattr(c, "timestamp", 0) or 0
            c_year = None
            c_date = None
            if ts > 0:
                dt = datetime.fromtimestamp(ts / 1000)
                c_year = dt.year
                c_date = dt.strftime("%Y-%m-%d")

            results.append(
                {
                    "id": str(getattr(c, "comment_id", "")),
                    "content": getattr(c, "content", ""),
                    "likes": getattr(c, "liked_count", 0) or 0,
                    "year": c_year,
                    "date": c_date,
                    "user": getattr(c, "user_nickname", ""),
                }
            )

        return {
            "status": "success",
            "song_id": song_id,
            "filter": {"year": year, "min_likes": min_likes},
            "count": len(results),
            "comments": results,
            "note": "原始评论数据，请AI自行分析",
        }

    finally:
        session.close()


# ===== 导出 =====

__all__ = [
    "analyze_comments_v2",
    "get_dimension_samples_v2",
    "get_raw_comments",
]
