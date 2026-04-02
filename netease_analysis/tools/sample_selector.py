"""
v0.7.4 样本选择器

设计目标：
1. 去重：避免选择内容相似的评论
2. 多样性：覆盖不同年份、情感、类型
3. 代表性：每个样本代表一类评论
4. 目的明确：每个样本都有选择原因

核心算法：
- Jaccard相似度去重
- 分层抽样（年份、情感）
- 优先选择高信息量样本
"""

import sys
import os
from typing import List, Dict, Any, Optional, Tuple
from collections import defaultdict
from datetime import datetime
import re

# 添加路径
current_dir = os.path.dirname(os.path.abspath(__file__))
project_root = os.path.dirname(os.path.dirname(current_dir))
netease_path = os.path.join(project_root, 'netease_cloud_music')
if netease_path not in sys.path:
    sys.path.insert(0, netease_path)


# ===== 相似度计算 =====

def jaccard_similarity(text1: str, text2: str) -> float:
    """计算两个文本的Jaccard相似度"""
    if not text1 or not text2:
        return 0.0

    # 分词
    chars1 = set(text1)
    chars2 = set(text2)

    intersection = len(chars1 & chars2)
    union = len(chars1 | chars2)

    return intersection / union if union > 0 else 0.0


def is_similar(text1: str, text2: str, threshold: float = 0.6) -> bool:
    """判断两个文本是否相似"""
    return jaccard_similarity(text1, text2) >= threshold


def deduplicate_samples(
    samples: List[Dict],
    content_key: str = "content",
    similarity_threshold: float = 0.6,
    max_count: int = 10
) -> Tuple[List[Dict], int]:
    """
    去重样本

    Args:
        samples: 样本列表
        content_key: 内容字段名
        similarity_threshold: 相似度阈值
        max_count: 最大返回数量

    Returns:
        (去重后的样本, 去重数量)
    """
    if not samples:
        return [], 0

    unique_samples = []
    removed = 0

    for sample in samples:
        content = sample.get(content_key, "")

        # 检查是否与已选样本相似
        is_duplicate = False
        for existing in unique_samples:
            existing_content = existing.get(content_key, "")
            if is_similar(content, existing_content, similarity_threshold):
                is_duplicate = True
                # 更新代表数量
                existing["similar_count"] = existing.get("similar_count", 1) + 1
                removed += 1
                break

        if not is_duplicate:
            sample["similar_count"] = 1
            unique_samples.append(sample)

            if len(unique_samples) >= max_count:
                break

    return unique_samples, removed


# ===== 分层抽样 =====

def stratified_sample(
    comments: List[Any],
    strata_key: str,
    target_per_stratum: int = 3,
    max_total: int = 15
) -> List[Dict]:
    """
    分层抽样

    Args:
        comments: 评论列表
        strata_key: 分层键（year/sentiment/length_category）
        target_per_stratum: 每层目标数量
        max_total: 最大总数

    Returns:
        分层抽样结果
    """
    # 分组
    strata = defaultdict(list)

    for c in comments:
        content = getattr(c, 'content', '') or ''
        liked = getattr(c, 'liked_count', 0) or 0
        ts = getattr(c, 'timestamp', 0) or 0
        cid = getattr(c, 'comment_id', '') or ''

        # 计算分层键值
        if strata_key == "year":
            if ts > 0:
                try:
                    key = datetime.fromtimestamp(ts / 1000).year
                except:
                    key = "unknown"
            else:
                key = "unknown"
        elif strata_key == "length_category":
            length = len(content)
            if length < 20:
                key = "short"
            elif length < 80:
                key = "medium"
            else:
                key = "long"
        else:
            key = "default"

        strata[key].append({
            "id": str(cid),
            "content": content,
            "likes": liked,
            "stratum": key
        })

    # 从每层抽样
    result = []
    keys = sorted(strata.keys(), key=lambda k: len(strata[k]), reverse=True)

    for key in keys:
        stratum_samples = strata[key]

        # 按点赞排序
        stratum_samples.sort(key=lambda x: x["likes"], reverse=True)

        # 取前N个
        selected = stratum_samples[:target_per_stratum]
        result.extend(selected)

        if len(result) >= max_total:
            break

    return result[:max_total]


# ===== 目的驱动选择 =====

class SampleSelector:
    """
    目的驱动的样本选择器

    支持的目的：
    - for_algorithm_verification: 验证算法判断
    - for_content_understanding: 理解内容深层含义
    - for_temporal_analysis: 分析时间趋势
    - for_anomaly_detection: 检测异常模式
    """

    def __init__(self, comments: List[Any]):
        self.comments = comments
        self._cache = {}

    def select_for_algorithm_verification(
        self,
        scores: List[Tuple[Any, float]],
        algorithm_name: str = "SnowNLP"
    ) -> Dict[str, List[Dict]]:
        """
        选择用于验证算法的样本

        Args:
            scores: [(comment, score), ...] 评论与分数对
            algorithm_name: 算法名称

        Returns:
            {
                "purpose": "验证算法判断",
                "positive_confident": [...],
                "negative_confident": [...],
                "algorithm_uncertain": [...]
            }
        """
        positive_confident = []
        negative_confident = []
        uncertain = []

        for c, score in scores:
            content = getattr(c, 'content', '') or ''
            liked = getattr(c, 'liked_count', 0) or 0
            ts = getattr(c, 'timestamp', 0) or 0
            cid = getattr(c, 'comment_id', '') or ''

            year = None
            if ts > 0:
                try:
                    year = datetime.fromtimestamp(ts / 1000).year
                except:
                    pass

            sample = {
                "id": str(cid),
                "content": content[:100],
                "likes": liked,
                "year": year,
                "score": round(score, 3)
            }

            # 高置信正面
            if score >= 0.8 and len(positive_confident) < 5:
                positive_confident.append(sample)
            # 高置信负面
            elif score <= 0.2 and len(negative_confident) < 5:
                negative_confident.append(sample)
            # 不确定
            elif 0.4 <= score <= 0.6 and len(uncertain) < 3:
                sample["note"] = "算法不确定，需AI判断"
                uncertain.append(sample)

        # 去重
        positive_confident, _ = deduplicate_samples(positive_confident, max_count=5)
        negative_confident, _ = deduplicate_samples(negative_confident, max_count=5)
        uncertain, _ = deduplicate_samples(uncertain, max_count=3)

        return {
            "purpose": f"验证{algorithm_name}情感判断是否准确",
            "positive_confident": positive_confident,
            "negative_confident": negative_confident,
            "algorithm_uncertain": uncertain
        }

    def select_for_content_understanding(
        self,
        min_length: int = 50,
        max_samples: int = 5
    ) -> Dict[str, List[Dict]]:
        """
        选择用于理解内容的样本

        优先选择：
        1. 长评（信息量大）
        2. 高赞（已被验证）
        3. 多样性（不同年份/主题）
        """
        candidates = []

        for c in self.comments:
            content = getattr(c, 'content', '') or ''
            if len(content) < min_length:
                continue

            liked = getattr(c, 'liked_count', 0) or 0
            ts = getattr(c, 'timestamp', 0) or 0
            cid = getattr(c, 'comment_id', '') or ''

            year = None
            if ts > 0:
                try:
                    year = datetime.fromtimestamp(ts / 1000).year
                except:
                    pass

            candidates.append({
                "id": str(cid),
                "content": content[:150],
                "likes": liked,
                "year": year,
                "length": len(content),
                "purpose": "长评，信息量大"
            })

        # 按点赞排序
        candidates.sort(key=lambda x: x["likes"], reverse=True)

        # 去重并保证多样性
        selected, _ = deduplicate_samples(candidates, max_count=max_samples)

        return {
            "purpose": "理解评论深层含义",
            "information_rich": selected
        }

    def select_for_temporal_analysis(
        self,
        anomaly_years: List[int] = None,
        samples_per_year: int = 3
    ) -> Dict[str, List[Dict]]:
        """
        选择用于时间分析的样本

        优先选择：
        1. 异常年份的评论
        2. 每个年份的代表性评论
        """
        year_buckets = defaultdict(list)

        for c in self.comments:
            content = getattr(c, 'content', '') or ''
            liked = getattr(c, 'liked_count', 0) or 0
            ts = getattr(c, 'timestamp', 0) or 0
            cid = getattr(c, 'comment_id', '') or ''

            if ts <= 0:
                continue

            try:
                year = datetime.fromtimestamp(ts / 1000).year
            except:
                continue

            year_buckets[year].append({
                "id": str(cid),
                "content": content[:100],
                "likes": liked,
                "year": year
            })

        result = {"purpose": "分析时间异常原因"}

        # 异常年份样本
        if anomaly_years:
            for ay in anomaly_years[:3]:
                if ay in year_buckets:
                    samples = sorted(year_buckets[ay], key=lambda x: x["likes"], reverse=True)
                    samples = samples[:samples_per_year]
                    for s in samples:
                        s["purpose"] = f"{ay}年评论激增，样本用于分析原因"
                    result[f"year_{ay}"] = samples

        # 如果没有异常年份，选择跨年份样本
        if not anomaly_years:
            years = sorted(year_buckets.keys())
            for y in years[:5]:
                samples = sorted(year_buckets[y], key=lambda x: x["likes"], reverse=True)
                samples = samples[:2]
                result[f"year_{y}"] = samples

        return result

    def select_for_social_analysis(
        self,
        top_n: int = 10,
        viral_threshold: int = 10000
    ) -> Dict[str, List[Dict]]:
        """
        选择用于社交分析的样本

        选择策略：
        1. Top N高赞评论
        2. 病毒式评论（>10000赞）
        """
        all_comments = []

        for c in self.comments:
            content = getattr(c, 'content', '') or ''
            liked = getattr(c, 'liked_count', 0) or 0
            ts = getattr(c, 'timestamp', 0) or 0
            cid = getattr(c, 'comment_id', '') or ''

            all_comments.append({
                "id": str(cid),
                "content": content[:100],
                "likes": liked,
                "purpose": "高赞评论，分析什么内容容易获得共鸣"
            })

        # 按点赞排序
        all_comments.sort(key=lambda x: x["likes"], reverse=True)

        # 去重
        top_liked, _ = deduplicate_samples(all_comments, max_count=top_n)

        # 病毒式评论
        viral = [c for c in top_liked if c["likes"] >= viral_threshold]

        return {
            "purpose": "分析什么内容容易获得高赞",
            "top_liked": top_liked,
            "viral_count": len(viral)
        }

    def select_anchor_samples(
        self,
        most_liked_count: int = 5,
        earliest_count: int = 5,
        latest_count: int = 5,
        longest_count: int = 3
    ) -> Dict[str, Any]:
        """
        选择锚点样本 - AI验证基准

        v0.8.2新增
        锚点样本的意义：
        - 提供客观可验证的基准点
        - AI可以用这些样本验证算法判断是否准确
        - 不依赖算法分数，纯基于客观指标

        选择策略：
        1. 最高赞：社区认可的内容（反映大众共识）
        2. 最早评论：元老视角（歌曲刚发布时的反应）
        3. 最新评论：当前氛围（最近的社区状态）
        4. 最长评论：深度内容（高信息量样本）
        """
        all_samples = []

        for c in self.comments:
            content = getattr(c, 'content', '') or ''
            liked = getattr(c, 'liked_count', 0) or 0
            ts = getattr(c, 'timestamp', 0) or 0
            cid = getattr(c, 'comment_id', '') or ''

            year = None
            date_str = None
            if ts > 0:
                try:
                    dt = datetime.fromtimestamp(ts / 1000)
                    year = dt.year
                    date_str = dt.strftime('%Y-%m-%d')
                except:
                    pass

            all_samples.append({
                "id": str(cid),
                "content": content,
                "content_truncated": content[:150] if len(content) > 150 else content,
                "likes": liked,
                "timestamp": ts,
                "year": year,
                "date": date_str,
                "length": len(content)
            })

        # 1. 最高赞（社区认可）
        by_likes = sorted(all_samples, key=lambda x: x["likes"], reverse=True)
        most_liked = []
        for s in by_likes[:most_liked_count * 2]:  # 取多一些用于去重
            sample = {
                "id": s["id"],
                "content": s["content_truncated"],
                "likes": s["likes"],
                "date": s["date"],
                "anchor_reason": "最高赞 - 社区认可的内容"
            }
            most_liked.append(sample)
        most_liked, _ = deduplicate_samples(most_liked, max_count=most_liked_count)

        # 2. 最早评论（元老视角）
        valid_ts = [s for s in all_samples if s["timestamp"] > 0]
        by_time_asc = sorted(valid_ts, key=lambda x: x["timestamp"])
        earliest = []
        for s in by_time_asc[:earliest_count * 2]:
            sample = {
                "id": s["id"],
                "content": s["content_truncated"],
                "likes": s["likes"],
                "date": s["date"],
                "anchor_reason": "最早评论 - 元老视角"
            }
            earliest.append(sample)
        earliest, _ = deduplicate_samples(earliest, max_count=earliest_count)

        # 3. 最新评论（当前氛围）
        by_time_desc = sorted(valid_ts, key=lambda x: x["timestamp"], reverse=True)
        latest = []
        for s in by_time_desc[:latest_count * 2]:
            sample = {
                "id": s["id"],
                "content": s["content_truncated"],
                "likes": s["likes"],
                "date": s["date"],
                "anchor_reason": "最新评论 - 当前氛围"
            }
            latest.append(sample)
        latest, _ = deduplicate_samples(latest, max_count=latest_count)

        # 4. 最长评论（深度内容）
        by_length = sorted(all_samples, key=lambda x: x["length"], reverse=True)
        longest = []
        for s in by_length[:longest_count * 3]:  # 长评可能相似度高，取更多
            if s["length"] >= 50:  # 至少50字才算长评
                sample = {
                    "id": s["id"],
                    "content": s["content"][:200],  # 长评展示更多
                    "likes": s["likes"],
                    "date": s["date"],
                    "length": s["length"],
                    "anchor_reason": "最长评论 - 深度内容"
                }
                longest.append(sample)
        longest, _ = deduplicate_samples(longest, max_count=longest_count)

        return {
            "purpose": "锚点样本 - AI验证基准，不依赖算法判断",
            "most_liked": most_liked,
            "earliest": earliest,
            "latest": latest,
            "longest": longest,
            "note": "这些样本基于客观指标选择，可用于验证算法判断的准确性"
        }

    def select_contrast_samples(
        self,
        scores: List[Tuple[Any, float]],
        high_likes_low_score_count: int = 5,
        low_likes_long_count: int = 3
    ) -> Dict[str, Any]:
        """
        选择对比样本 - 发现异常模式

        v0.8.2新增
        对比样本的意义：
        - 发现算法可能误判的情况
        - 帮助AI识别反讽、暗语等复杂表达
        - 找出被忽视的高质量内容

        选择策略：
        1. 高赞低分：高点赞但算法判为负面 → 可能是反讽/暗语/算法误判
        2. 低赞长评：低点赞但内容很长 → 被忽视的深度思考
        """
        # 建立评论ID到分数的映射
        score_map = {}
        for c, score in scores:
            cid = str(getattr(c, 'comment_id', '') or '')
            if cid:
                score_map[cid] = score

        all_samples = []

        for c in self.comments:
            content = getattr(c, 'content', '') or ''
            liked = getattr(c, 'liked_count', 0) or 0
            ts = getattr(c, 'timestamp', 0) or 0
            cid = str(getattr(c, 'comment_id', '') or '')

            date_str = None
            if ts > 0:
                try:
                    date_str = datetime.fromtimestamp(ts / 1000).strftime('%Y-%m-%d')
                except:
                    pass

            score = score_map.get(cid)

            all_samples.append({
                "id": cid,
                "content": content,
                "content_truncated": content[:150] if len(content) > 150 else content,
                "likes": liked,
                "date": date_str,
                "length": len(content),
                "score": score
            })

        # 1. 高赞低分（可能反讽/暗语）
        # 条件：点赞 >= 100 且 分数 <= 0.3
        high_likes_low_score = []
        candidates = [s for s in all_samples
                      if s["score"] is not None
                      and s["likes"] >= 100
                      and s["score"] <= 0.3]
        candidates.sort(key=lambda x: x["likes"], reverse=True)

        for s in candidates[:high_likes_low_score_count * 2]:
            sample = {
                "id": s["id"],
                "content": s["content_truncated"],
                "likes": s["likes"],
                "algorithm_score": round(s["score"], 3),
                "date": s["date"],
                "contrast_reason": "高赞低分 - 可能是反讽/暗语/算法误判",
                "ai_task": "请判断这条评论的真实情感，算法可能误判"
            }
            high_likes_low_score.append(sample)
        high_likes_low_score, _ = deduplicate_samples(
            high_likes_low_score, max_count=high_likes_low_score_count
        )

        # 2. 低赞长评（被忽视的深度）
        # 条件：点赞 <= 10 且 长度 >= 100
        low_likes_long = []
        candidates = [s for s in all_samples
                      if s["likes"] <= 10
                      and s["length"] >= 100]
        candidates.sort(key=lambda x: x["length"], reverse=True)

        for s in candidates[:low_likes_long_count * 2]:
            sample = {
                "id": s["id"],
                "content": s["content"][:200],  # 长评展示更多
                "likes": s["likes"],
                "length": s["length"],
                "date": s["date"],
                "contrast_reason": "低赞长评 - 被忽视的深度思考",
                "ai_task": "请评估这条长评的价值，可能包含独特见解"
            }
            low_likes_long.append(sample)
        low_likes_long, _ = deduplicate_samples(
            low_likes_long, max_count=low_likes_long_count
        )

        return {
            "purpose": "对比样本 - 发现异常模式，帮助AI识别复杂表达",
            "high_likes_low_score": high_likes_low_score,
            "low_likes_but_long": low_likes_long,
            "note": "高赞低分可能是反讽/暗语；低赞长评可能是被忽视的高质量内容"
        }

    def select_diverse_samples(
        self,
        target_count: int = 20,
        dimensions: List[str] = None
    ) -> Dict[str, Any]:
        """
        选择多样化样本

        Args:
            target_count: 目标数量
            dimensions: 多样性维度 (year/length/sentiment)

        Returns:
            多样化样本集
        """
        dimensions = dimensions or ["year", "length"]

        all_samples = []
        seen_ids = set()

        # 从每个维度分层抽样
        for dim in dimensions:
            samples = stratified_sample(
                self.comments,
                strata_key=dim,
                target_per_stratum=3,
                max_total=target_count // len(dimensions)
            )

            for s in samples:
                if s["id"] not in seen_ids:
                    seen_ids.add(s["id"])
                    s["diversity_source"] = dim
                    all_samples.append(s)

        # 去重
        final_samples, removed = deduplicate_samples(all_samples, max_count=target_count)

        return {
            "total_selected": len(final_samples),
            "deduplicated_count": removed,
            "dimensions_used": dimensions,
            "samples": final_samples
        }


# ===== 便捷函数 =====

def select_samples_for_dimension(
    comments: List[Any],
    dimension: str,
    **kwargs
) -> Dict[str, Any]:
    """
    为指定维度选择样本

    Args:
        comments: 评论列表
        dimension: 维度ID
        **kwargs: 额外参数

    Returns:
        样本字典
    """
    selector = SampleSelector(comments)

    if dimension == "sentiment":
        # 需要传入分数
        scores = kwargs.get("scores", [])
        return selector.select_for_algorithm_verification(scores)

    elif dimension == "content":
        return selector.select_for_content_understanding()

    elif dimension == "temporal":
        anomaly_years = kwargs.get("anomaly_years", [])
        return selector.select_for_temporal_analysis(anomaly_years)

    elif dimension == "social":
        return selector.select_for_social_analysis()

    elif dimension == "linguistic":
        # 复用内容理解样本
        return selector.select_for_content_understanding(min_length=30)

    else:
        # 默认返回多样化样本
        return selector.select_diverse_samples()


# ===== 导出 =====

__all__ = [
    "SampleSelector",
    "select_samples_for_dimension",
    "deduplicate_samples",
    "stratified_sample",
    "jaccard_similarity",
    # v0.8.2新增
    "select_anchor_and_contrast_samples",
]


def select_anchor_and_contrast_samples(
    comments: List[Any],
    scores: List[Tuple[Any, float]] = None
) -> Dict[str, Any]:
    """
    v0.8.2新增：选择锚点和对比样本

    便捷函数，整合锚点样本和对比样本的选择

    Args:
        comments: 评论列表
        scores: 评论分数对列表 [(comment, score), ...]

    Returns:
        {
            'anchors': {...},   # 锚点样本
            'contrast': {...}   # 对比样本
        }
    """
    selector = SampleSelector(comments)

    result = {
        "anchors": selector.select_anchor_samples(),
    }

    # 构建 id→score 映射，注入到 anchors
    if scores:
        score_map = {}
        for c, s in scores:
            cid = str(getattr(c, "comment_id", "") or "")
            if cid:
                score_map[cid] = round(s, 3)

        for key in ("most_liked", "earliest", "latest", "longest"):
            for sample in result["anchors"].get(key, []):
                sid = str(sample.get("id", ""))
                sample["algorithm_score"] = score_map.get(sid)

        result["contrast"] = selector.select_contrast_samples(scores)
    else:
        result["contrast"] = {
            "purpose": "对比样本 - 需要算法分数",
            "high_likes_low_score": [],
            "low_likes_but_long": [],
            "note": "未提供算法分数，无法选择对比样本"
        }

    return result
