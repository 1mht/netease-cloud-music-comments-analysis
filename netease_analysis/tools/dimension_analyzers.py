"""
v0.7.5 维度分析器模块（修复版）

核心修复：
1. 移除隐含判断的标签（positive_confident → algo_score）
2. 不生成结论，只给统计数据
3. 让AI自己判断情感

设计原则：
1. 算法输出是"数据"不是"结论"
2. 样本不带情感标签，只带算法分数
3. AI自己判断，发现算法错误
"""

import sys
import os
import logging
from datetime import datetime
from typing import List, Dict, Any, Optional, Tuple
from collections import defaultdict

# 添加路径
current_dir = os.path.dirname(os.path.abspath(__file__))
project_root = os.path.dirname(os.path.dirname(current_dir))
netease_path = os.path.join(project_root, "netease_cloud_music")
if netease_path not in sys.path:
    sys.path.insert(0, netease_path)

from database import Comment

logger = logging.getLogger(__name__)

# ===== 常量 =====
LENGTH_MICRO = 10
LENGTH_SHORT = 30
LENGTH_MEDIUM = 80
LENGTH_LONG = 200
VIRAL_THRESHOLD = 10000

# v0.8.6: 各维度数据需求定义
# 用于 Layer 1 评估数据充足性，决定是否需要补充采样
DIMENSION_DATA_REQUIREMENTS = {
    "sentiment": {
        "min_good": 300,  # 300+ 条 = good
        "min_acceptable": 150,  # 150-299 条 = acceptable
        "min_required": 50,  # 50+ 条才能分析，<50 = insufficient
        "reason": "情感分析需要足够样本量保证统计可靠性",
    },
    "content": {
        "min_good": 200,
        "min_acceptable": 100,
        "min_required": 30,
        "reason": "关键词提取需要足够文本量",
    },
    "temporal": {
        "min_years_good": 5,  # 覆盖5+年 = good
        "min_years_acceptable": 3,  # 覆盖3-4年 = acceptable
        "min_years_required": 2,  # 至少2年才能分析趋势
        "reason": "时间趋势分析需要多年份覆盖",
    },
    "structural": {
        "min_hot_good": 20,  # 20+ 条高赞 = good
        "min_hot_acceptable": 10,  # 10-19 条 = acceptable
        "min_hot_required": 3,  # 至少3条高赞
        "reason": "结构分析主要依赖高赞评论（>=1000赞）",
    },
    "social": {
        "min_good": 200,
        "min_acceptable": 100,
        "min_required": 30,
        "reason": "社交分析需要足够的点赞数据",
    },
    "linguistic": {
        "min_good": 200,
        "min_acceptable": 100,
        "min_required": 30,
        "reason": "语言风格分析需要足够样本",
    },
}


# ===== 辅助函数 =====


def _evaluate_data_sufficiency(
    dimension_id: str,
    current_count: int,
    years_covered: int = None,
    hot_count: int = None,
) -> dict:
    """
    v0.8.6: 评估某维度的数据充足性

    Args:
        dimension_id: 维度ID
        current_count: 当前样本数量
        years_covered: 覆盖年份数（仅 temporal 维度需要）
        hot_count: 高赞评论数（仅 structural 维度需要）

    Returns:
        {
            "level": "good" / "acceptable" / "insufficient",
            "current": 当前数量,
            "min_required": 最低要求,
            "min_good": 优质标准,
            "need_more": 还需要多少（0表示足够）,
            "reason": 解释
        }
    """
    req = DIMENSION_DATA_REQUIREMENTS.get(dimension_id, {})

    # temporal 维度用年份数评估
    if dimension_id == "temporal":
        years = years_covered or 0
        min_good = req.get("min_years_good", 5)
        min_acceptable = req.get("min_years_acceptable", 3)
        min_required = req.get("min_years_required", 2)

        if years >= min_good:
            level = "good"
            need_more = 0
        elif years >= min_acceptable:
            level = "acceptable"
            need_more = 0
        elif years >= min_required:
            level = "limited"
            need_more = min_acceptable - years
        else:
            level = "insufficient"
            need_more = min_required - years

        return {
            "level": level,
            "current_years": years,
            "min_required_years": min_required,
            "min_good_years": min_good,
            "need_more_years": max(0, need_more),
            "reason": req.get("reason", ""),
        }

    # structural 维度用高赞评论数评估
    if dimension_id == "structural":
        hot = hot_count or 0
        min_good = req.get("min_hot_good", 20)
        min_acceptable = req.get("min_hot_acceptable", 10)
        min_required = req.get("min_hot_required", 3)

        if hot >= min_good:
            level = "good"
            need_more = 0
        elif hot >= min_acceptable:
            level = "acceptable"
            need_more = 0
        elif hot >= min_required:
            level = "limited"
            need_more = min_acceptable - hot
        else:
            level = "insufficient"
            need_more = min_required - hot

        return {
            "level": level,
            "current_hot_comments": hot,
            "min_required_hot": min_required,
            "min_good_hot": min_good,
            "need_more_hot": max(0, need_more),
            "reason": req.get("reason", ""),
            "note": "需要更多高赞评论（>=1000赞）" if need_more > 0 else "",
        }

    # 其他维度用样本数量评估
    min_good = req.get("min_good", 200)
    min_acceptable = req.get("min_acceptable", 100)
    min_required = req.get("min_required", 30)

    if current_count >= min_good:
        level = "good"
        need_more = 0
    elif current_count >= min_acceptable:
        level = "acceptable"
        need_more = 0
    elif current_count >= min_required:
        level = "limited"
        need_more = min_acceptable - current_count
    else:
        level = "insufficient"
        need_more = min_required - current_count

    return {
        "level": level,
        "current_count": current_count,
        "min_required": min_required,
        "min_good": min_good,
        "need_more": max(0, need_more),
        "reason": req.get("reason", ""),
    }


def _get_analyzer():
    """获取情感分析器"""
    try:
        from snownlp import SnowNLP

        return SnowNLP
    except ImportError:
        return None


def _timestamp_to_year(timestamp: int) -> Optional[int]:
    try:
        if timestamp > 0:
            return datetime.fromtimestamp(timestamp / 1000).year
        return None
    except:
        return None


def _classify_sentiment(score: float) -> str:
    if score >= 0.6:
        return "positive"
    elif score <= 0.4:
        return "negative"
    return "neutral"


# ===== SENTIMENT 维度 =====


def analyze_sentiment_v2(comments: List[Any]) -> dict:
    """
    分析情感维度（v0.7.4格式）

    Returns:
        {
            "dimension_id": "sentiment",
            "dimension_name": "情感分析",
            "algorithm_assessment": {...},
            "quantified_facts": {...},
            "samples": {...},
            "signals": [...]
        }
    """
    SnowNLP = _get_analyzer()
    if not SnowNLP or not comments:
        return _empty_result("sentiment", "情感分析")

    scores = []
    hot_scores = []
    normal_scores = []
    all_samples = []  # 收集所有样本，不预先分类

    for c in comments:
        content = getattr(c, "content", "") or ""
        if len(content) < 3:
            continue

        try:
            score = SnowNLP(content).sentiments
            liked = getattr(c, "liked_count", 0) or 0
            comment_id = getattr(c, "comment_id", "") or ""
            year = _timestamp_to_year(getattr(c, "timestamp", 0) or 0)

            scores.append(score)
            if liked >= 1000:
                hot_scores.append(score)
            else:
                normal_scores.append(score)

            # 收集样本（不加情感标签，只记录算法分数）
            all_samples.append(
                {
                    "id": str(comment_id),
                    "content": content[:100],
                    "likes": liked,
                    "year": year,
                    "algo_score": round(score, 3),  # 只给算法分数，不给情感标签
                }
            )

        except Exception:
            continue

    if not scores:
        return _empty_result("sentiment", "情感分析")

    # 统计
    positive = sum(1 for s in scores if s >= 0.6)
    negative = sum(1 for s in scores if s <= 0.4)
    neutral = len(scores) - positive - negative
    total = len(scores)

    mean_score = sum(scores) / total
    std_score = (sum((s - mean_score) ** 2 for s in scores) / total) ** 0.5

    hot_mean = sum(hot_scores) / len(hot_scores) if hot_scores else 0
    normal_mean = (
        sum(normal_scores) / len(normal_scores) if normal_scores else mean_score
    )

    # 一致性
    if std_score < 0.15:
        consistency = "high"
    elif std_score < 0.25:
        consistency = "medium"
    else:
        consistency = "low"

    # 计算置信度（算法本身的置信度，不是结论的置信度）
    base_confidence = 0.5  # 降低默认置信度，因为SnowNLP对音乐评论不可靠
    if total >= 300:
        base_confidence += 0.1
    if consistency == "high":
        base_confidence += 0.1
    elif consistency == "low":
        base_confidence -= 0.1

    # v0.8.2: 删除irony_risk断言，只保留事实数据
    # 原因：irony_risk="high"是断言，违反第一性原理
    # 正确做法：提供hot_low_score_ratio数据，让AI自己判断
    irony_gap = normal_mean - hot_mean  # 保留用于显示

    # 计算高赞评论中低分占比（事实数据，供AI参考）
    hot_low_score_count = sum(1 for s in hot_scores if s <= 0.3)
    hot_low_score_ratio = hot_low_score_count / len(hot_scores) if hot_scores else 0

    # v0.8.2: 置信度调整逻辑保留，但不输出irony_risk断言
    if hot_low_score_ratio >= 0.2:
        base_confidence -= 0.2
    elif hot_low_score_ratio >= 0.1 or irony_gap > 0.2:
        base_confidence -= 0.1

    confidence = min(0.7, max(0.2, base_confidence))  # 上限降到0.7，下限0.2

    # 检测异常信号（只标注现象，不下结论）
    signals = []

    # v0.8.2: 改为事实描述，删除"反讽风险"这个断言
    # 只告诉AI数据现象，让AI自己判断原因
    if hot_low_score_ratio >= 0.2 and len(hot_scores) >= 5:
        signals.append(
            f"高赞评论中{int(hot_low_score_ratio * 100)}%算法分<=0.3（共{len(hot_scores)}条高赞），"
            f"请阅读high_likes_low_score样本判断原因"
        )
    elif hot_low_score_ratio >= 0.1 and len(hot_scores) >= 5:
        signals.append(
            f"高赞评论中{int(hot_low_score_ratio * 100)}%算法分<=0.3，建议验证样本"
        )

    if std_score > 0.3:
        signals.append(f"情感离散度高({std_score:.2f})，存在明显分歧")
    if negative / total > 0.3:
        signals.append(f"低分评论占{int(negative / total * 100)}%，高于典型值")

    # 选择代表性样本：高分、低分、中间各取几条，让AI自己判断
    samples_high = sorted(
        [s for s in all_samples if s["algo_score"] >= 0.8],
        key=lambda x: -x["algo_score"],
    )[:5]
    samples_low = sorted(
        [s for s in all_samples if s["algo_score"] <= 0.2],
        key=lambda x: x["algo_score"],
    )[:5]
    samples_mid = [s for s in all_samples if 0.4 <= s["algo_score"] <= 0.6][:3]

    # v0.7.6: 高赞但低算法分数的样本 (反讽典型特征)
    high_likes_low_score = sorted(
        [s for s in all_samples if s["likes"] >= 50 and s["algo_score"] <= 0.5],
        key=lambda x: -x["likes"],
    )[:5]

    # v0.7.6: 高赞但高算法分数的样本 (对比用)
    high_likes_high_score = sorted(
        [s for s in all_samples if s["likes"] >= 50 and s["algo_score"] >= 0.7],
        key=lambda x: -x["likes"],
    )[:3]

    # v0.8.6: 数据充足性评估
    data_sufficiency = _evaluate_data_sufficiency("sentiment", total)

    return {
        "dimension_id": "sentiment",
        "dimension_name": "情感分析",
        # v0.8.6: 数据充足性（用于决定是否需要补充采样）
        "data_sufficiency": data_sufficiency,
        "algorithm_assessment": {
            # v0.8.2: 不生成结论，只描述算法做了什么
            "algorithm": "SnowNLP",
            "confidence": round(confidence, 2),
            "confidence_level": "low" if confidence < 0.5 else "medium",
            # v0.8.2: 删除irony_risk断言，改为在raw_numbers中提供数据
            "limitations": [
                "SnowNLP训练于商品评论，对音乐评论不适用",
                "对讽刺、反语、诗意表达识别能力很弱",
                "饭圈用语、网络梗、艺术表达常被误判",
                "请AI阅读样本验证实际情感",
            ],
            "note": "算法分数仅供参考，AI需阅读样本判断",
        },
        "quantified_facts": {
            "algo_output": {
                "high_score_ratio": round(positive / total, 3),  # 不说"正面"
                "mid_score_ratio": round(neutral / total, 3),
                "low_score_ratio": round(negative / total, 3),
            },
            "statistics": {
                "mean_score": round(mean_score, 3),
                "std": round(std_score, 3),
                "consistency": consistency,
                "hot_mean": round(hot_mean, 3),
                "normal_mean": round(normal_mean, 3),
                "irony_gap": round(irony_gap, 3),
                "hot_low_score_ratio": round(
                    hot_low_score_ratio, 3
                ),  # v0.7.7: 高赞中低分占比
                "hot_count": len(hot_scores),  # v0.7.7: 高赞评论数量
            },
            "sample_size": total,
            "method": "SnowNLP情感分析，分数0-1",
        },
        "samples": {
            "for_ai_verification": {
                "instruction": (
                    "请判断这些评论的实际情感，与algo_score对比，发现算法误判。"
                    "注意：high_likes_low_score样本可能是诗意表达/深情感慨/玩梗，不一定是负面。"
                ),
                "high_algo_score": samples_high,  # 算法给高分的（可能误判）
                "low_algo_score": samples_low,  # 算法给低分的（可能误判）
                "mid_algo_score": samples_mid,  # 算法不确定的
                # v0.8.2: 对比样本（用于验证算法准确性）
                "high_likes_low_score": high_likes_low_score,  # 高赞但算法给低分
                "high_likes_high_score": high_likes_high_score,  # 高赞且算法给高分（对比用）
            }
        },
        "signals": signals,
    }


# ===== CONTENT 维度 =====


def analyze_content_v2(comments: List[Any]) -> dict:
    """分析内容维度（v0.7.4格式）"""
    try:
        import jieba.analyse
        import logging as _logging

        # 避免 jieba 在 STDIO 模式下输出过多初始化日志
        jieba.setLogLevel(_logging.WARNING)
    except ImportError:
        return _empty_result("content", "内容分析")

    texts = [
        getattr(c, "content", "") or "" for c in comments if getattr(c, "content", "")
    ]
    if not texts:
        return _empty_result("content", "内容分析")

    full_text = " ".join(texts)

    try:
        tags = jieba.analyse.extract_tags(
            full_text,
            topK=20,
            withWeight=True,
            allowPOS=("n", "nr", "ns", "nt", "nz", "v", "vd", "vn", "a", "ad", "an"),
        )
    except:
        return _empty_result("content", "内容分析")

    keywords = [{"word": w, "weight": round(wt, 4)} for w, wt in tags]

    # 计算关键词出现率（粗略：按子串匹配，避免把TF-IDF权重误读为“占比”）
    total_texts = len(texts)
    for kw in keywords[:10]:
        word = kw.get("word", "")
        if not word:
            continue
        doc_freq = sum(1 for t in texts if word in t)
        kw["doc_freq"] = doc_freq
        kw["doc_ratio"] = round(doc_freq / total_texts, 4) if total_texts > 0 else 0

    # 主题分类
    themes = _classify_themes_v2(keywords, texts)

    # 长评样本
    long_samples = []
    for c in comments:
        content = getattr(c, "content", "") or ""
        if len(content) >= 50 and len(long_samples) < 5:
            long_samples.append(
                {
                    "id": str(getattr(c, "comment_id", "")),
                    "content": content[:150],
                    "likes": getattr(c, "liked_count", 0) or 0,
                    "purpose": "长评，信息量大",
                }
            )

    # 置信度
    confidence = 0.7 if len(texts) >= 100 else 0.5

    # 检测异常信号（只标注现象）
    signals = []
    if themes and themes[0]["percentage"] > 0.5:
        signals.append(
            f"'{themes[0]['name']}'主题匹配度{int(themes[0]['percentage'] * 100)}%"
        )

    # 关键词提示：明确区分 TF-IDF 权重 vs 真实出现率
    if keywords:
        top = keywords[0]
        word = top.get("word", "")
        weight = top.get("weight", 0)
        doc_freq = top.get("doc_freq")
        doc_ratio = top.get("doc_ratio")
        if doc_freq is not None and doc_ratio is not None:
            signals.append(
                f"关键词'{word}'(TF-IDF权重{weight}，出现于{doc_freq}/{total_texts}条评论)值得关注"
            )
        else:
            signals.append(f"关键词'{word}'(TF-IDF权重{weight})值得关注")

    # v0.8.6: 数据充足性评估
    data_sufficiency = _evaluate_data_sufficiency("content", len(texts))

    return {
        "dimension_id": "content",
        "dimension_name": "内容分析",
        # v0.8.6: 数据充足性
        "data_sufficiency": data_sufficiency,
        "algorithm_assessment": {
            # 不生成结论
            "algorithm": "TF-IDF + 规则主题分类",
            "confidence": round(confidence, 2),
            "confidence_level": "medium" if confidence >= 0.5 else "low",
            "limitations": [
                "jieba TF-IDF的weight是统计权重，不是出现占比/频率",
                "TF-IDF基于词频，无法理解语义",
                "主题分类基于规则匹配",
                "请AI阅读样本理解实际内容",
            ],
            "note": "关键词统计仅供参考，请AI阅读样本判断",
        },
        "quantified_facts": {
            "metrics": {"top_keywords": keywords[:10], "themes": themes[:5]},
            "statistics": {
                "unique_texts": len(texts),
                "avg_length": round(sum(len(t) for t in texts) / len(texts), 1),
            },
            "sample_size": len(texts),
            "method": "jieba TF-IDF关键词提取",
        },
        "samples": {
            "for_content_understanding": {
                "purpose": "理解评论深层含义",
                "information_rich": long_samples,
            }
        },
        "signals": signals,
    }


def _classify_themes_v2(keywords: List[dict], texts: List[str]) -> List[dict]:
    """基于规则分类主题"""
    theme_rules = {
        "怀旧": ["青春", "回忆", "那年", "时光", "曾经", "当年", "想起", "年轻"],
        "情感": ["感动", "眼泪", "哭", "心", "爱", "难过", "伤心", "痛"],
        "音乐": ["旋律", "编曲", "唱功", "好听", "经典", "神曲", "歌词"],
        "故事": ["记得", "那时", "故事", "后来", "从前", "第一次"],
    }

    keyword_words = set(k["word"] for k in keywords)
    theme_scores = {}

    for theme, words in theme_rules.items():
        matches = sum(
            1 for w in words if w in keyword_words or any(w in t for t in texts[:100])
        )
        theme_scores[theme] = matches

    total = sum(theme_scores.values()) or 1
    themes = [
        {"name": name, "percentage": round(score / total, 3)}
        for name, score in sorted(theme_scores.items(), key=lambda x: -x[1])
        if score > 0
    ]

    return themes[:5]


# ===== TEMPORAL 维度 =====


def analyze_temporal_v2(comments: List[Any]) -> dict:
    """
    分析时间维度（v0.8.2重构）

    第一性原理：
    - 采样策略是每年固定采~200条，所以年份分布只反映采样配置
    - "某年是平均的X倍"基于采样结果，没有意义
    - 有意义的信息：年份覆盖范围、缺失年份、热评的年份分布

    输出：
    - 时间覆盖范围（事实）
    - 缺失年份（事实）
    - 热评年份分布（有代表性）
    - 各年份样本数（仅供参考，标注采样偏差）
    """
    year_buckets = defaultdict(list)
    hot_year_buckets = defaultdict(list)  # 热评按年份分组

    current_year = datetime.now().year

    for c in comments:
        ts = getattr(c, "timestamp", 0) or 0
        year = _timestamp_to_year(ts)
        liked = getattr(c, "liked_count", 0) or 0

        if year:
            year_buckets[year].append(c)
            if liked >= 1000:
                hot_year_buckets[year].append(c)

    if not year_buckets:
        return _empty_result("temporal", "时间分析")

    years = sorted(year_buckets.keys())
    first_year = years[0]
    last_year = years[-1]
    time_span = last_year - first_year + 1 if len(years) > 1 else 1

    # ===== 检测缺失年份 =====
    expected_years = set(range(first_year, last_year + 1))
    actual_years = set(years)
    missing_years = sorted(expected_years - actual_years)

    # ===== 热评年份分布（有代表性）=====
    hot_years = sorted(hot_year_buckets.keys())
    hot_timeline = []
    for y in hot_years:
        hot_timeline.append({"year": y, "count": len(hot_year_buckets[y])})
    total_hot = sum(len(hot_year_buckets[y]) for y in hot_years)

    # ===== 主样本年份分布（仅供参考）=====
    sample_timeline = []
    for y in years:
        sample_timeline.append({"year": y, "count": len(year_buckets[y])})

    # ===== 信号（基于事实，不基于采样比较）=====
    signals = []

    # 信号1：时间跨度
    if time_span >= 5:
        signals.append(
            f"评论时间跨度{time_span}年（{first_year}-{last_year}），可分析长期趋势"
        )
    elif time_span <= 2:
        signals.append(f"评论时间跨度仅{time_span}年，temporal分析参考价值有限")

    # 信号2：缺失年份
    if missing_years:
        signals.append(
            f"缺失年份：{missing_years}，这些年份无采样数据，"
            f"可能原因：歌曲发行时间、采样策略、评论确实稀少"
        )

    # 信号3：热评集中年份（热评有代表性）
    if hot_timeline:
        hot_years_with_count = [(t["year"], t["count"]) for t in hot_timeline]
        max_hot_year, max_hot_count = max(hot_years_with_count, key=lambda x: x[1])
        if max_hot_count >= 5:
            signals.append(
                f"热评集中在{max_hot_year}年（{max_hot_count}条），"
                f"建议阅读该年份样本理解评论区高峰"
            )

    # 信号4：最新评论距今时间
    if last_year < current_year - 1:
        signals.append(f"最新评论在{last_year}年，近期({current_year}年)无采样数据")

    # ===== 各年份代表性样本 =====
    year_samples = {}
    # 最早年份样本
    earliest_year = years[0]
    year_samples["earliest"] = []
    for c in year_buckets[earliest_year][:3]:
        year_samples["earliest"].append(
            {
                "id": str(getattr(c, "comment_id", "")),
                "content": (getattr(c, "content", "") or "")[:100],
                "likes": getattr(c, "liked_count", 0) or 0,
                "year": earliest_year,
                "purpose": "最早年份样本，了解评论区初期氛围",
            }
        )

    # 最新年份样本
    latest_year = years[-1]
    if latest_year != earliest_year:
        year_samples["latest"] = []
        for c in year_buckets[latest_year][:3]:
            year_samples["latest"].append(
                {
                    "id": str(getattr(c, "comment_id", "")),
                    "content": (getattr(c, "content", "") or "")[:100],
                    "likes": getattr(c, "liked_count", 0) or 0,
                    "year": latest_year,
                    "purpose": "最新年份样本，了解评论区当前氛围",
                }
            )

    # 置信度：基于时间跨度和热评数量
    if time_span >= 5 and total_hot >= 10:
        confidence = 0.7
        confidence_level = "medium"
    elif time_span >= 3 or total_hot >= 5:
        confidence = 0.5
        confidence_level = "low"
    else:
        confidence = 0.3
        confidence_level = "very_low"

    # v0.8.6: 数据充足性评估（temporal 用年份数）
    data_sufficiency = _evaluate_data_sufficiency(
        "temporal", current_count=len(comments), years_covered=len(years)
    )

    return {
        "dimension_id": "temporal",
        "dimension_name": "时间分析",
        # v0.8.6: 数据充足性
        "data_sufficiency": data_sufficiency,
        "algorithm_assessment": {
            "algorithm": "时间覆盖统计（热评vs主样本分离）",
            "confidence": round(confidence, 2),
            "confidence_level": confidence_level,
            "limitations": [
                "主样本来自cursor年份跳转采样，年份分布仅反映采样策略",
                "年份间的数量比较无意义（采样配置为每年~200条）",
                "只有热评的年份分布有一定代表性",
                f"缺失年份{missing_years}无数据" if missing_years else "无缺失年份",
            ],
            "note": "关注时间覆盖范围和缺失年份，不要比较年份间的数量",
        },
        "quantified_facts": {
            "coverage": {
                "first_year": first_year,
                "last_year": last_year,
                "time_span_years": time_span,
                "missing_years": missing_years,
                "years_with_data": years,
            },
            "hot_comments_by_year": {  # 有代表性
                "timeline": hot_timeline,
                "total": total_hot,
                "note": "热评是API直接返回的，年份分布有参考价值",
            },
            "sample_distribution_reference": {  # 仅供参考
                "timeline": sample_timeline,
                "warning": "此分布仅反映采样策略（每年~200条），不代表真实评论量分布",
            },
            "sample_size": len(comments),
        },
        "samples": {"by_year": year_samples},
        "signals": signals,
        "ai_guidance": {
            "focus_on": "时间覆盖范围和缺失年份，热评集中的年份",
            "ignore": "年份间的数量比较（采样偏差）",
            "next_step": "如需深入分析特定年份，可调用get_raw_comments(year=XXXX)",
        },
    }


# ===== STRUCTURAL 维度 =====


def analyze_structural_v2(comments: List[Any]) -> dict:
    """
    分析结构维度（v0.8.2重构）

    第一性原理：
    - 主样本来自cursor年份跳转采样，长度分布只反映采样策略，不反映真实评论区
    - 热评（>=1000赞）是API直接返回的，有真实代表性
    - 所以：只对热评做有意义的分析，主样本统计仅供参考
    """
    if not comments:
        return _empty_result("structural", "结构分析")

    # 分离热评和主样本
    hot_comments = []
    main_comments = []

    for c in comments:
        content = getattr(c, "content", "") or ""
        liked = getattr(c, "liked_count", 0) or 0
        length = len(content)

        if liked >= 1000:
            hot_comments.append({"content": content, "length": length, "likes": liked})
        else:
            main_comments.append({"content": content, "length": length, "likes": liked})

    # ===== 热评分析（有代表性）=====
    hot_lengths = [h["length"] for h in hot_comments]
    hot_analysis = None
    if hot_lengths:
        hot_short = sum(1 for l in hot_lengths if l <= LENGTH_SHORT)
        hot_long = sum(1 for l in hot_lengths if l > LENGTH_MEDIUM)
        hot_total = len(hot_lengths)
        hot_analysis = {
            "count": hot_total,
            "short_ratio": round(hot_short / hot_total, 3) if hot_total > 0 else 0,
            "long_ratio": round(hot_long / hot_total, 3) if hot_total > 0 else 0,
            "mean_length": round(sum(hot_lengths) / hot_total, 1)
            if hot_total > 0
            else 0,
            "max_length": max(hot_lengths) if hot_lengths else 0,
            "note": "热评是API直接返回的，长度分布有代表性",
        }

    # ===== 主样本统计（仅供参考）=====
    main_lengths = [m["length"] for m in main_comments]
    main_total = len(main_lengths)

    if main_total > 0:
        micro = sum(1 for l in main_lengths if l <= LENGTH_MICRO)
        short = sum(1 for l in main_lengths if LENGTH_MICRO < l <= LENGTH_SHORT)
        medium = sum(1 for l in main_lengths if LENGTH_SHORT < l <= LENGTH_MEDIUM)
        long_count = sum(1 for l in main_lengths if LENGTH_MEDIUM < l <= LENGTH_LONG)
        extended = sum(1 for l in main_lengths if l > LENGTH_LONG)

        main_distribution = {
            "micro": round(micro / main_total, 3),
            "short": round(short / main_total, 3),
            "medium": round(medium / main_total, 3),
            "long": round(long_count / main_total, 3),
            "extended": round(extended / main_total, 3),
        }
        main_mean = round(sum(main_lengths) / main_total, 1)
    else:
        main_distribution = {}
        main_mean = 0

    # ===== 信号（只基于热评，因为有代表性）=====
    signals = []
    if hot_analysis:
        if hot_analysis["short_ratio"] >= 0.7:
            signals.append(
                f"热评中{int(hot_analysis['short_ratio'] * 100)}%是短评(<=30字)，"
                f"评论区可能以情绪表达/玩梗为主"
            )
        if hot_analysis["long_ratio"] >= 0.3:
            signals.append(
                f"热评中{int(hot_analysis['long_ratio'] * 100)}%是长评(>80字)，"
                f"评论区可能有深度讨论/故事分享"
            )
        if hot_analysis["mean_length"] > 50:
            signals.append(f"热评平均{hot_analysis['mean_length']:.0f}字，内容较为丰富")

    # 如果没有热评，承认无法分析
    if not hot_comments:
        signals.append("无高赞评论(>=1000赞)，本维度无有效数据")

    # v0.8.6: 数据充足性评估（structural 用高赞评论数）
    data_sufficiency = _evaluate_data_sufficiency(
        "structural", current_count=len(comments), hot_count=len(hot_comments)
    )

    return {
        "dimension_id": "structural",
        "dimension_name": "结构分析",
        # v0.8.6: 数据充足性
        "data_sufficiency": data_sufficiency,
        "algorithm_assessment": {
            "algorithm": "长度分布统计（热评vs主样本分离）",
            "confidence": 0.7 if hot_comments else 0.3,  # 有热评才有意义
            "confidence_level": "medium" if hot_comments else "low",
            "limitations": [
                "主样本来自cursor年份跳转采样，长度分布仅反映采样策略",
                "只有热评(>=1000赞)的长度分布有代表性",
                "长度不代表内容质量",
            ],
            "note": "热评分析有效，主样本统计仅供参考",
        },
        "quantified_facts": {
            "hot_comments_analysis": hot_analysis,  # 有代表性
            "main_sample_reference": {  # 仅供参考
                "distribution": main_distribution,
                "mean_length": main_mean,
                "sample_size": main_total,
                "warning": "此数据仅反映采样结果，不代表真实评论区分布",
            },
        },
        "samples": {},
        "signals": signals,
        "ai_guidance": {
            "if_hot_exists": "请关注热评的长度分布，判断评论区是情绪型还是内容型",
            "if_no_hot": "无高赞评论，本维度数据参考价值低，建议跳过",
        },
    }


# ===== SOCIAL 维度 =====


def analyze_social_v2(comments: List[Any]) -> dict:
    """分析社交维度（v0.7.4格式）"""
    if not comments:
        return _empty_result("social", "社交分析")

    likes = sorted([getattr(c, "liked_count", 0) or 0 for c in comments], reverse=True)
    total_likes = sum(likes)

    if not likes or total_likes == 0:
        return _empty_result("social", "社交分析")

    # 集中度
    top_1_pct_count = max(1, len(likes) // 100)
    top_1_pct_likes = sum(likes[:top_1_pct_count])
    concentration = top_1_pct_likes / total_likes

    # 热评样本
    hot_samples = []
    for c in sorted(
        comments, key=lambda x: getattr(x, "liked_count", 0) or 0, reverse=True
    )[:10]:
        hot_samples.append(
            {
                "id": str(getattr(c, "comment_id", "")),
                "content": (getattr(c, "content", "") or "")[:100],
                "likes": getattr(c, "liked_count", 0) or 0,
                "purpose": "高赞评论，用于分析什么内容容易获得共鸣",
            }
        )

    # 检测异常信号
    signals = []
    if concentration > 0.5:
        signals.append(f"前1%评论占{int(concentration * 100)}%点赞")

    viral_count = sum(1 for l in likes if l >= VIRAL_THRESHOLD)
    if viral_count > 0:
        signals.append(f"存在{viral_count}条病毒式评论(>{VIRAL_THRESHOLD}赞)")

    # v0.8.6: 数据充足性评估
    data_sufficiency = _evaluate_data_sufficiency("social", len(comments))

    return {
        "dimension_id": "social",
        "dimension_name": "社交分析",
        # v0.8.6: 数据充足性
        "data_sufficiency": data_sufficiency,
        "algorithm_assessment": {
            "algorithm": "点赞分布统计",
            "confidence": 0.85,
            "confidence_level": "high",
            "limitations": ["点赞数为快照", "无法区分真实点赞和刷赞"],
            "note": "纯统计数据，请AI分析高赞内容",
        },
        "quantified_facts": {
            "metrics": {
                "concentration": round(concentration, 3),
                "max_likes": max(likes),
                "median_likes": likes[len(likes) // 2],
                "viral_count": viral_count,
            },
            "statistics": {
                "total_likes": total_likes,
                "mean_likes": round(total_likes / len(likes), 1),
            },
            "sample_size": len(comments),
            "method": "点赞分布统计",
        },
        "samples": {
            "for_social_analysis": {
                "purpose": "分析什么内容容易获得高赞",
                "top_liked": hot_samples,
            }
        },
        "signals": signals,
    }


# ===== LINGUISTIC 维度 =====


def analyze_linguistic_v2(comments: List[Any]) -> dict:
    """分析语言维度（v0.7.4格式）"""
    if not comments:
        return _empty_result("linguistic", "语言分析")

    type_counts = {"Short": 0, "Meme": 0, "Story": 0, "Review": 0}
    type_samples = {t: [] for t in type_counts}

    for c in comments:
        content = getattr(c, "content", "") or ""
        ctype = _classify_comment_type(content)
        type_counts[ctype] += 1

        if len(type_samples[ctype]) < 3:
            type_samples[ctype].append(
                {
                    "id": str(getattr(c, "comment_id", "")),
                    "content": content[:80],
                    "likes": getattr(c, "liked_count", 0) or 0,
                    "type": ctype,
                }
            )

    total = sum(type_counts.values())
    if total == 0:
        return _empty_result("linguistic", "语言分析")

    type_pcts = {t: round(c / total, 3) for t, c in type_counts.items()}
    dominant = max(type_counts, key=type_counts.get)

    # 检测异常信号
    signals = []
    if type_pcts["Short"] > 0.6:
        signals.append(f"短评占{int(type_pcts['Short'] * 100)}%")
    if type_pcts["Story"] > 0.2:
        signals.append(f"故事型评论占{int(type_pcts['Story'] * 100)}%")

    # v0.8.6: 数据充足性评估
    data_sufficiency = _evaluate_data_sufficiency("linguistic", total)

    return {
        "dimension_id": "linguistic",
        "dimension_name": "语言分析",
        # v0.8.6: 数据充足性
        "data_sufficiency": data_sufficiency,
        "algorithm_assessment": {
            "algorithm": "规则分类（长度+关键词）",
            "confidence": 0.6,
            "confidence_level": "low",
            "limitations": ["分类基于简单规则", "边界情况分类不准", "请AI阅读样本判断"],
            "note": "规则分类仅供参考",
        },
        "quantified_facts": {
            "metrics": {"type_distribution": type_pcts, "dominant_type": dominant},
            "statistics": {"counts": type_counts},
            "sample_size": total,
            "method": "4类评论分类",
        },
        "samples": {
            "for_linguistic_analysis": {
                "purpose": "各类型评论示例",
                "by_type": type_samples,
            }
        },
        "signals": signals,
    }


def _classify_comment_type(content: str) -> str:
    """分类评论类型"""
    if not content or len(content) < 6:
        return "Short"

    length = len(content)

    music_terms = {
        "编曲",
        "作词",
        "作曲",
        "音色",
        "吉他",
        "贝斯",
        "混音",
        "前奏",
        "和声",
        "唱功",
        "旋律",
        "歌词",
        "副歌",
    }
    if sum(1 for t in music_terms if t in content) >= 2:
        return "Review"

    story_kw = {
        "记得",
        "那年",
        "那时",
        "当时",
        "曾经",
        "后来",
        "故事",
        "第一次",
        "小时候",
        "以前",
    }
    if sum(1 for k in story_kw if k in content) >= 2 and length >= 30:
        return "Story"

    if 15 <= length <= 30:
        return "Meme"

    if length < 15:
        return "Short"

    return "Meme"


# ===== 空结果 =====


def _empty_result(dim_id: str, dim_name: str) -> dict:
    return {
        "dimension_id": dim_id,
        "dimension_name": dim_name,
        "algorithm_assessment": {
            "summary": "数据不足，无法分析",
            "confidence": 0,
            "confidence_level": "low",
            "limitations": ["样本量不足"],
            "algorithm": "N/A",
            "note": "数据不足",
        },
        "quantified_facts": {
            "metrics": {},
            "statistics": {},
            "sample_size": 0,
            "method": "N/A",
        },
        "samples": {},
        "signals": ["数据不足，建议增加采样量"],
    }


# ===== 统一入口 =====


def analyze_all_dimensions(
    comments: List[Any], include_anchor_contrast: bool = True
) -> Dict[str, Any]:
    """
    分析所有维度（v0.7.4格式，v0.8.2增强）

    v0.8.2新增：
    - 锚点样本（anchors）：最高赞、最早、最新、最长
    - 对比样本（contrast）：高赞低分、低赞长评

    Args:
        comments: 评论列表
        include_anchor_contrast: 是否包含锚点和对比样本（默认True）

    Returns:
        {
            "sentiment": {...},
            "content": {...},
            "temporal": {...},
            "structural": {...},
            "social": {...},
            "linguistic": {...},
            "anchor_contrast_samples": {...}  # v0.8.2新增
        }
    """
    result = {
        "sentiment": analyze_sentiment_v2(comments),
        "content": analyze_content_v2(comments),
        "temporal": analyze_temporal_v2(comments),
        "structural": analyze_structural_v2(comments),
        "social": analyze_social_v2(comments),
        "linguistic": analyze_linguistic_v2(comments),
    }

    # v0.8.2: 添加锚点和对比样本
    if include_anchor_contrast and comments:
        try:
            # 修复导入路径：使用相对导入
            from netease_analysis.tools.sample_selector import (
                select_anchor_and_contrast_samples,
            )

            # 获取情感分数用于对比样本
            SnowNLP = _get_analyzer()
            scores = []
            if SnowNLP:
                for c in comments:
                    content = getattr(c, "content", "") or ""
                    if len(content) >= 3:
                        try:
                            score = SnowNLP(content).sentiments
                            scores.append((c, score))
                        except:
                            pass

            anchor_contrast = select_anchor_and_contrast_samples(comments, scores)
            result["anchor_contrast_samples"] = anchor_contrast
            logger.info(
                f"锚点/对比样本生成成功: anchors={len(anchor_contrast.get('anchors', {}).get('most_liked', []))}"
            )

        except ImportError as e:
            logger.error(f"sample_selector模块导入失败: {e}，跳过锚点/对比样本")
        except Exception as e:
            logger.error(f"生成锚点/对比样本失败: {e}", exc_info=True)

    return result


def get_dimension_analyzer_v2(dimension_id: str):
    """获取指定维度的v2分析器"""
    analyzers = {
        "sentiment": analyze_sentiment_v2,
        "content": analyze_content_v2,
        "temporal": analyze_temporal_v2,
        "structural": analyze_structural_v2,
        "social": analyze_social_v2,
        "linguistic": analyze_linguistic_v2,
    }
    return analyzers.get(dimension_id)
