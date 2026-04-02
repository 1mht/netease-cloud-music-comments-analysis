"""
v0.8.2 跨维度信号检测（第一性原理重构）

设计原则（架构设计.md）：
  - MCP提供"事实+可能原因"，不提供"结论+置信度"
  - 删除所有confidence断言
  - 让AI阅读样本自己判断

输出格式变更：
  旧格式（错误）：
    {"signal_name": "反讽模式", "confidence": 0.9, "description": "高概率存在反讽"}

  新格式（正确）：
    {"signal_id": "high_likes_low_score_pattern",
     "fact": "高赞评论中20%的算法分数<=0.3",
     "raw_numbers": {...},
     "possible_reasons": ["反讽/玩梗", "诗意表达", "深情感慨", "真实负面"],
     "ai_action": "请阅读样本判断属于哪种情况"}

核心规则：
1. 网抑云现象：时间×情感×关键词
2. 共情文化：社交×内容
3. 怀旧深度：结构×时间
4. 玩梗文化：语言×情感×社交
5. 事件驱动：时间×内容×社交
6. 高赞低分模式：社交×情感（替代原"反讽检测"）
"""

from typing import List, Dict, Any, Optional
from collections import defaultdict
from datetime import datetime


def detect_cross_signals(
    dimensions: Dict[str, dict],
    comments: List[Any] = None
) -> List[Dict[str, Any]]:
    """
    检测跨维度信号（v0.8.2第一性原理重构）

    Args:
        dimensions: 六维度分析结果
        comments: 原始评论列表（可选，用于深度分析）

    Returns:
        [
            {
                "signal_id": "wangyiyun_pattern",
                "fact": "情感关键词(寂寞,孤独)出现2+次，负面比例>=25%",
                "raw_numbers": {...},
                "possible_reasons": [...],
                "samples_location": "...",
                "ai_action": "..."
            },
            ...
        ]

    注意：v0.8.2删除了所有confidence字段，改为fact+possible_reasons
    """
    signals = []

    # 提取各维度数据
    sentiment = dimensions.get("sentiment", {})
    content = dimensions.get("content", {})
    temporal = dimensions.get("temporal", {})
    structural = dimensions.get("structural", {})
    social = dimensions.get("social", {})
    linguistic = dimensions.get("linguistic", {})

    # 规则1：网抑云现象（深夜emo文化）
    signal = _detect_wangyiyun_phenomenon(sentiment, content, temporal)
    if signal:
        signals.append(signal)

    # 规则2：共情文化（故事型评论获得高赞）
    signal = _detect_empathy_culture(social, content, linguistic)
    if signal:
        signals.append(signal)

    # 规则3：怀旧深度（时间跨度 × 长评比例）
    signal = _detect_nostalgia_depth(temporal, structural, content)
    if signal:
        signals.append(signal)

    # 规则4：玩梗文化（短评 + 高赞 + 低情感分）
    signal = _detect_meme_culture(linguistic, social, sentiment)
    if signal:
        signals.append(signal)

    # 规则5：事件驱动（时间异常 + 主题集中）
    signal = _detect_event_driven(temporal, content, social)
    if signal:
        signals.append(signal)

    # 规则6：反讽/假骂真夸（高赞 + 低情感分 + 特定词汇）
    signal = _detect_irony_pattern(sentiment, social, content)
    if signal:
        signals.append(signal)

    return signals


def _detect_wangyiyun_phenomenon(
    sentiment: dict,
    content: dict,
    temporal: dict
) -> Optional[Dict]:
    """
    检测网抑云现象（v0.8.2重构：事实+可能原因）

    特征：
    - 情感偏负面或两极化
    - 内容关键词包含：孤独、深夜、失眠、难过、眼泪等
    """
    # 提取数据
    sent_qf = sentiment.get("quantified_facts", {})
    sent_stats = sent_qf.get("statistics", {})
    sent_algo = sent_qf.get("algo_output", {})

    content_qf = content.get("quantified_facts", {})
    keywords = content_qf.get("metrics", {}).get("top_keywords", [])
    keyword_words = [k.get("word", "") for k in keywords]

    # 网抑云关键词
    wangyiyun_keywords = {
        "孤独", "深夜", "失眠", "难过", "眼泪", "哭",
        "心碎", "分手", "伤心", "想你", "思念", "抑郁",
        "凌晨", "一个人", "寂寞", "泪", "痛"
    }

    # 计算匹配度
    matched_keywords = [w for w in keyword_words if w in wangyiyun_keywords]

    # 情感两极化检测
    std_score = sent_stats.get("std", 0)
    low_score_ratio = sent_algo.get("low_score_ratio", 0)

    # 判断条件
    has_emotional_keywords = len(matched_keywords) >= 2
    has_negative_tendency = low_score_ratio >= 0.25
    has_polarization = std_score >= 0.25

    if has_emotional_keywords and (has_negative_tendency or has_polarization):
        # v0.8.2: 改为事实描述，删除confidence
        condition_desc = "负面比例>=25%" if has_negative_tendency else f"情感离散度高({std_score:.2f})"

        return {
            "signal_id": "wangyiyun_pattern",
            "fact": (
                f"情感关键词({', '.join(matched_keywords[:3])})出现{len(matched_keywords)}次，"
                f"且{condition_desc}"
            ),
            "raw_numbers": {
                "matched_keywords": matched_keywords,
                "keyword_count": len(matched_keywords),
                "low_score_ratio": round(low_score_ratio, 3),
                "sentiment_std": round(std_score, 3)
            },
            "possible_reasons": [
                "真实的情感共鸣（歌曲本身触发听众情绪）",
                "网抑云跟风文化（模仿式伤感评论）",
                "深夜情绪释放（评论区作为情绪出口）",
                "算法误判（SnowNLP对情感词汇敏感但不理解语境）"
            ],
            "samples_location": "dimensions.sentiment.samples.for_ai_verification",
            "ai_action": (
                "请阅读情感维度样本，判断：\n"
                "1. 这些负面关键词是真实情感还是玩梗？\n"
                "2. 评论区整体氛围是什么？"
            )
        }

    return None


def _detect_empathy_culture(
    social: dict,
    content: dict,
    linguistic: dict
) -> Optional[Dict]:
    """
    检测共情文化（v0.8.2重构：事实+可能原因）

    特征：
    - 高赞评论以故事型为主
    - 内容主题偏向情感/怀旧
    - 评论有叙事结构
    """
    social_qf = social.get("quantified_facts", {})
    concentration = social_qf.get("metrics", {}).get("concentration", 0)

    ling_qf = linguistic.get("quantified_facts", {})
    type_dist = ling_qf.get("metrics", {}).get("type_distribution", {})
    story_ratio = type_dist.get("Story", 0)

    content_qf = content.get("quantified_facts", {})
    themes = content_qf.get("metrics", {}).get("themes", [])
    top_theme = themes[0].get("name") if themes else None

    # 判断条件
    has_story_culture = story_ratio >= 0.15
    has_emotional_theme = top_theme in ["怀旧", "情感", "故事"]
    has_high_concentration = concentration >= 0.3

    if has_story_culture and has_emotional_theme and has_high_concentration:
        return {
            "signal_id": "empathy_culture_pattern",
            "fact": (
                f"故事型评论占{int(story_ratio*100)}%，"
                f"主题以'{top_theme}'为主，"
                f"前1%评论占{int(concentration*100)}%点赞"
            ),
            "raw_numbers": {
                "story_ratio": round(story_ratio, 3),
                "top_theme": top_theme,
                "concentration": round(concentration, 3)
            },
            "possible_reasons": [
                "歌曲触发个人回忆（听众分享自己的故事）",
                "评论区形成共情社区（故事获得高赞认同）",
                "怀旧情绪集体释放",
                "故事型评论更容易获得点赞（长度优势）"
            ],
            "samples_location": "anchor_contrast_samples.anchors.longest",
            "ai_action": (
                "请阅读longest样本，判断：\n"
                "1. 高赞故事评论的共同特点是什么？\n"
                "2. 评论区的核心情感共鸣点是什么？"
            )
        }

    return None


def _detect_nostalgia_depth(
    temporal: dict,
    structural: dict,
    content: dict
) -> Optional[Dict]:
    """
    检测怀旧深度（v0.8.2重构：事实+可能原因）

    特征：
    - 时间跨度长（>5年）
    - 长评比例高
    - 内容主题偏怀旧
    """
    temporal_qf = temporal.get("quantified_facts", {})
    time_span = temporal_qf.get("metrics", {}).get("time_span_years", 0)

    structural_qf = structural.get("quantified_facts", {})
    length_dist = structural_qf.get("metrics", {}).get("length_distribution", {})
    long_ratio = length_dist.get("long", 0) + length_dist.get("extended", 0)

    content_qf = content.get("quantified_facts", {})
    themes = content_qf.get("metrics", {}).get("themes", [])
    nostalgia_theme = next(
        (t for t in themes if t.get("name") == "怀旧"),
        None
    )
    nostalgia_pct = nostalgia_theme.get("percentage", 0) if nostalgia_theme else 0

    # 判断条件
    has_long_timespan = time_span >= 5
    has_long_comments = long_ratio >= 0.1
    has_nostalgia_theme = nostalgia_pct >= 0.2

    if has_long_timespan and has_long_comments and has_nostalgia_theme:
        return {
            "signal_id": "nostalgia_depth_pattern",
            "fact": (
                f"评论跨越{time_span}年，"
                f"长评(>80字)占{int(long_ratio*100)}%，"
                f"怀旧主题词匹配{int(nostalgia_pct*100)}%"
            ),
            "raw_numbers": {
                "time_span_years": time_span,
                "long_comment_ratio": round(long_ratio, 3),
                "nostalgia_percentage": round(nostalgia_pct, 3)
            },
            "possible_reasons": [
                "老歌持续吸引新老听众（跨代共鸣）",
                "歌曲与个人成长经历关联（青春记忆）",
                "评论区沉淀了多年情感",
                "长评用户倾向于分享深度回忆"
            ],
            "samples_location": "anchor_contrast_samples.anchors.earliest",
            "ai_action": (
                "请对比earliest和latest样本：\n"
                "1. 早期评论和近期评论有什么不同？\n"
                "2. 评论的怀旧主题是什么？"
            )
        }

    return None


def _detect_meme_culture(
    linguistic: dict,
    social: dict,
    sentiment: dict
) -> Optional[Dict]:
    """
    检测玩梗文化（v0.8.2重构：事实+可能原因）

    特征：
    - 短评占比高（>60%）
    - 高赞评论情感分低
    """
    ling_qf = linguistic.get("quantified_facts", {})
    type_dist = ling_qf.get("metrics", {}).get("type_distribution", {})
    short_ratio = type_dist.get("Short", 0) + type_dist.get("Meme", 0)

    sent_qf = sentiment.get("quantified_facts", {})
    sent_stats = sent_qf.get("statistics", {})
    hot_mean = sent_stats.get("hot_mean", 0.5)
    hot_low_ratio = sent_stats.get("hot_low_score_ratio", 0)

    # 判断条件
    has_short_dominant = short_ratio >= 0.6
    has_low_hot_sentiment = hot_mean <= 0.45 or hot_low_ratio >= 0.15

    if has_short_dominant and has_low_hot_sentiment:
        return {
            "signal_id": "meme_culture_pattern",
            "fact": (
                f"短评(Short+Meme)占{int(short_ratio*100)}%，"
                f"高赞评论平均情感分{hot_mean:.2f}"
            ),
            "raw_numbers": {
                "short_ratio": round(short_ratio, 3),
                "hot_sentiment_mean": round(hot_mean, 3),
                "hot_low_score_ratio": round(hot_low_ratio, 3)
            },
            "possible_reasons": [
                "评论区以互动/玩梗为主（短评文化）",
                "复读机式评论（跟风复制）",
                "算法对网络用语/梗文化误判",
                "高赞短评可能是抢楼/占位"
            ],
            "samples_location": "anchor_contrast_samples.anchors.most_liked",
            "ai_action": (
                "请阅读most_liked样本：\n"
                "1. 高赞短评的内容是什么？\n"
                "2. 是否有重复/梗文化特征？\n"
                "3. 算法情感分数是否可信？"
            )
        }

    return None


def _detect_event_driven(
    temporal: dict,
    content: dict,
    social: dict
) -> Optional[Dict]:
    """
    检测事件驱动（v0.8.2重构：事实+可能原因）

    特征：
    - 某年/某时期评论量异常激增
    - 关键词集中于特定主题
    """
    temporal_qf = temporal.get("quantified_facts", {})
    anomaly_years = temporal_qf.get("metrics", {}).get("anomaly_years", [])

    content_qf = content.get("quantified_facts", {})
    keywords = content_qf.get("metrics", {}).get("top_keywords", [])
    themes = content_qf.get("metrics", {}).get("themes", [])

    if anomaly_years:
        top_anomaly = anomaly_years[0]
        year = top_anomaly.get("year")
        ratio = top_anomaly.get("ratio", 1)

        if ratio >= 2:
            top_keywords = [k.get("word") for k in keywords[:5]]
            top_theme = themes[0].get("name") if themes else "未知"

            return {
                "signal_id": "event_driven_pattern",
                "fact": (
                    f"{year}年评论量是平均值的{ratio}倍"
                ),
                "raw_numbers": {
                    "anomaly_year": year,
                    "ratio": ratio,
                    "top_keywords": top_keywords,
                    "top_theme": top_theme
                },
                "possible_reasons": [
                    "热播剧/综艺使用该歌曲作为BGM",
                    "歌手有重大新闻/活动",
                    "歌曲被翻唱/二次创作",
                    "社交媒体传播引发怀旧潮",
                    "自然增长（歌曲热度上升期）"
                ],
                "samples_location": "dimensions.temporal.samples.for_temporal_analysis",
                "ai_action": (
                    f"请阅读{year}年的样本评论：\n"
                    "1. 评论中是否提到具体事件？\n"
                    "2. 关键词({})能否推测原因？".format(', '.join(top_keywords[:3]))
                )
            }

    return None


def _detect_irony_pattern(
    sentiment: dict,
    social: dict,
    content: dict
) -> Optional[Dict]:
    """
    检测高赞低分模式（v0.8.2重构：事实+可能原因）

    重要：这个函数曾导致"星河滚烫，你是人间理想"被误判为反讽
    实际上那是诗意表达，不是反讽！

    v0.8.2修改：
    - 删除"反讽模式"这个断言性名称
    - 改为"高赞低分模式"这个事实性描述
    - 删除confidence，给出多种可能原因让AI判断
    """
    sent_qf = sentiment.get("quantified_facts", {})
    sent_stats = sent_qf.get("statistics", {})
    hot_low_ratio = sent_stats.get("hot_low_score_ratio", 0)
    hot_count = sent_stats.get("hot_count", 0)
    irony_gap = sent_stats.get("irony_gap", 0)

    # 判断条件
    has_pattern = hot_low_ratio >= 0.1 and hot_count >= 5

    if has_pattern:
        # 根据比例描述强度，但不下结论
        if hot_low_ratio >= 0.2:
            strength = "显著"
        else:
            strength = "中等"

        return {
            "signal_id": "high_likes_low_score_pattern",
            "fact": (
                f"高赞评论(>=1000赞)中，{int(hot_low_ratio*100)}%的算法情感分<=0.3"
            ),
            "raw_numbers": {
                "hot_low_score_ratio": round(hot_low_ratio, 3),
                "hot_comment_count": hot_count,
                "sentiment_gap": round(irony_gap, 3),
                "pattern_strength": strength
            },
            "possible_reasons": [
                "反讽/假骂真夸（形式负面实际认可）",
                "艺术化/诗意表达（如'星河滚烫，你是人间理想'）",
                "深情感慨（如'这首歌毁了我的青春'实为深情）",
                "玩梗/网络用语（算法不理解）",
                "真实负面情感"
            ],
            "samples_location": "anchor_contrast_samples.contrast.high_likes_low_score",
            "ai_action": (
                "【必须阅读样本】请查看high_likes_low_score样本：\n"
                "1. 判断低分是算法误判还是真实负面\n"
                "2. 注意：诗意表达常被算法误判为负面\n"
                "3. 基于样本内容判断真实情感"
            )
        }

    return None


def format_signals_for_ai(signals: List[Dict]) -> str:
    """
    将信号格式化为AI友好的文本（v0.8.2重构）

    Args:
        signals: detect_cross_signals的返回值

    Returns:
        格式化的文本
    """
    if not signals:
        return "未检测到显著的跨维度信号。"

    lines = ["## 跨维度信号（事实+可能原因）\n"]

    for i, signal in enumerate(signals, 1):
        signal_id = signal.get("signal_id", "unknown")
        fact = signal.get("fact", "")
        possible_reasons = signal.get("possible_reasons", [])
        ai_action = signal.get("ai_action", "")

        lines.append(f"### {i}. {signal_id}")
        lines.append(f"- **事实**: {fact}")
        if possible_reasons:
            lines.append(f"- **可能原因**: {' | '.join(possible_reasons[:3])}")
        lines.append(f"- **AI任务**: {ai_action}")
        lines.append("")

    return "\n".join(lines)


# ===== 导出 =====

__all__ = [
    "detect_cross_signals",
    "format_signals_for_ai",
]
