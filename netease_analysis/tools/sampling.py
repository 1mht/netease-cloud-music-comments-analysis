"""
采样策略 v6 - 简化版三级采样

设计原则（第一性原理）：
1. 固定结构：热评(15) + 最新(offset) + 年份(cursor)
2. 三个级别：quick(200) / standard(600) / deep(1000)
3. 动态分配：根据歌曲年份跨度自动调整比例
4. 服务六维度：保证 temporal 年份覆盖 + structural 高赞样本

边缘情况处理：
- 冷门歌(api_total < target)：全采
- 新歌(≤2年)：100% offset
- 中等新(3-5年)：20% offset + 80% 年份
- 正常(6-10年)：30% offset + 70% 年份
- 老歌(>10年)：限制采10年

v0.8.6
"""

import sys
import os
import time
import logging
import requests
from datetime import datetime
from typing import List, Dict, Any, Optional, Set
from collections import defaultdict
from dataclasses import dataclass, field

# 路径设置
current_dir = os.path.dirname(os.path.abspath(__file__))
project_root = os.path.dirname(os.path.dirname(current_dir))
netease_path = os.path.join(project_root, "netease_cloud_music")
if netease_path not in sys.path:
    sys.path.insert(0, netease_path)

from database import init_db, Song, Comment

logger = logging.getLogger(__name__)


# ==================== 配置 ====================

# 三级采样目标
LEVEL_TARGETS = {"quick": 200, "standard": 600, "deep": 1000}

# 年份跨度策略
YEAR_SPAN_STRATEGIES = {
    # (min_years, max_years): (offset_ratio, yearly_ratio)
    "new": (0, 2, 1.0, 0.0),  # 新歌：100% offset
    "medium": (3, 5, 0.2, 0.8),  # 中等新：20% offset + 80% 年份
    "normal": (6, 10, 0.3, 0.7),  # 正常：30% offset + 70% 年份
    "old": (11, 99, 0.3, 0.7),  # 老歌：30% offset + 70% 年份(限10年)
}

MAX_YEARS_TO_SAMPLE = 10  # 老歌最多采10年


# ==================== 工具函数 ====================


def get_session():
    """获取数据库session"""
    db_path = os.path.join(project_root, "data", "music_data_v2.db")
    return init_db(f"sqlite:///{db_path}")


def get_cookie() -> Optional[str]:
    """加载cookie"""
    cookie_path = os.path.join(project_root, "netease_cloud_music", "cookie.txt")
    if os.path.exists(cookie_path):
        try:
            with open(cookie_path, "r", encoding="utf-8") as f:
                cookie = f.read().strip()
                if cookie and not cookie.startswith("#"):
                    return cookie
        except:
            pass
    return None


def get_existing_comment_ids(song_id: str) -> Set[str]:
    """获取数据库中已有的评论ID"""
    session = get_session()
    try:
        existing = session.query(Comment.comment_id).filter_by(song_id=song_id).all()
        return set(str(c[0]) for c in existing if c[0])
    except Exception as e:
        logger.warning(f"获取已有ID异常: {e}")
        return set()
    finally:
        session.close()


def get_publish_year(song_id: str) -> int:
    """获取歌曲发布年份"""
    NETEASE_LAUNCH_YEAR = 2013

    session = get_session()
    try:
        song = session.query(Song).filter_by(id=song_id).first()
        if song and song.album and song.album.publish_time:
            year = datetime.fromtimestamp(song.album.publish_time / 1000).year
            return max(year, NETEASE_LAUNCH_YEAR)
    except:
        pass
    finally:
        session.close()

    return NETEASE_LAUNCH_YEAR


def calculate_sampling_params(
    target: int, years_span: int, api_total: int
) -> Dict[str, Any]:
    """
    计算采样参数

    Args:
        target: 目标数量 (200/600/1000)
        years_span: 年份跨度
        api_total: API评论总数

    Returns:
        {
            "hot": 15,
            "recent": 最新评论数,
            "per_year": 每年采样数,
            "effective_years": 实际采样年份数
        }
    """
    hot = 15
    remaining = target - hot

    # 边缘1: 冷门歌 → 全采
    if api_total < target:
        return {
            "hot": hot,
            "recent": min(api_total, 1000),  # offset上限约1000
            "per_year": 0,
            "effective_years": 0,
            "strategy": "cold_song",
        }

    # 边缘2: 新歌(≤2年) → 100% offset
    if years_span <= 2:
        return {
            "hot": hot,
            "recent": remaining,
            "per_year": 0,
            "effective_years": 0,
            "strategy": "new_song",
        }

    # 确定策略
    if years_span <= 5:
        # 中等新(3-5年): 20% offset + 80% 年份
        offset_ratio, yearly_ratio = 0.2, 0.8
        effective_years = years_span
        strategy = "medium_song"
    elif years_span <= 10:
        # 正常(6-10年): 30% offset + 70% 年份
        offset_ratio, yearly_ratio = 0.3, 0.7
        effective_years = years_span
        strategy = "normal_song"
    else:
        # 老歌(>10年): 30% offset + 70% 年份，限10年
        offset_ratio, yearly_ratio = 0.3, 0.7
        effective_years = MAX_YEARS_TO_SAMPLE
        strategy = "old_song"

    recent = int(remaining * offset_ratio)
    yearly_total = int(remaining * yearly_ratio)
    per_year = yearly_total // effective_years

    return {
        "hot": hot,
        "recent": recent,
        "per_year": per_year,
        "effective_years": effective_years,
        "strategy": strategy,
    }


# ==================== 采样函数 ====================


def sample_hot_comments(song_id: str, existing_ids: Set[str]) -> List[Dict]:
    """采样热评（独立渠道，平台精选）"""
    url = f"http://music.163.com/api/v1/resource/comments/R_SO_4_{song_id}?limit=20&offset=0"
    headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"}

    cookie = get_cookie()
    if cookie:
        headers["Cookie"] = cookie

    result = []
    try:
        resp = requests.get(url, headers=headers, timeout=10)
        data = resp.json()

        if data.get("code") != 200:
            return result

        for c in data.get("hotComments", [])[:15]:
            cid = str(c.get("commentId", ""))
            if cid and cid not in existing_ids:
                result.append(
                    {
                        "comment_id": cid,
                        "content": c.get("content", ""),
                        "liked_count": c.get("likedCount", 0),
                        "timestamp": c.get("time", 0),
                        "user_nickname": c.get("user", {}).get("nickname", ""),
                        "source": "hot",
                    }
                )

        logger.info(f"[v6] 热评: {len(result)}条")
    except Exception as e:
        logger.warning(f"[v6] 热评采样异常: {e}")

    return result


def sample_recent_comments(
    song_id: str, existing_ids: Set[str], limit: int
) -> List[Dict]:
    """采样最新评论（offset翻页）"""
    url = f"http://music.163.com/api/v1/resource/comments/R_SO_4_{song_id}"
    headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"}

    cookie = get_cookie()
    if cookie:
        headers["Cookie"] = cookie

    result = []
    seen_ids = set(existing_ids)
    page_size = 20
    max_offset = min(limit, 1000)  # offset上限约1000

    for offset in range(0, max_offset, page_size):
        if len(result) >= limit:
            break

        try:
            resp = requests.get(
                f"{url}?limit={page_size}&offset={offset}", headers=headers, timeout=10
            )
            data = resp.json()

            if data.get("code") != 200:
                break

            comments = data.get("comments", [])
            if not comments:
                break

            for c in comments:
                cid = str(c.get("commentId", ""))
                if cid and cid not in seen_ids:
                    seen_ids.add(cid)
                    result.append(
                        {
                            "comment_id": cid,
                            "content": c.get("content", ""),
                            "liked_count": c.get("likedCount", 0),
                            "timestamp": c.get("time", 0),
                            "user_nickname": c.get("user", {}).get("nickname", ""),
                            "source": "recent",
                        }
                    )

            time.sleep(0.3)

        except Exception as e:
            logger.warning(f"[v6] 最新评论采样异常: {e}")
            break

    logger.info(f"[v6] 最新评论: {len(result)}条")
    return result[:limit]


def sample_yearly_comments(
    song_id: str,
    existing_ids: Set[str],
    start_year: int,
    effective_years: int,
    per_year: int,
) -> tuple:
    """
    采样年份评论（cursor年份跳转）

    Returns:
        (comments_list, year_distribution)
    """
    from netease_cloud_music.utils import create_weapi_params

    url = "https://music.163.com/weapi/comment/resource/comments/get?csrf_token="
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)",
        "Content-Type": "application/x-www-form-urlencoded",
        "Referer": "https://music.163.com/",
    }

    cookie = get_cookie()
    if cookie:
        headers["Cookie"] = cookie

    result = []
    seen_ids = set(existing_ids)
    year_dist = defaultdict(int)

    current_year = datetime.now().year

    # 确定要采样的年份（从最近往前）
    years_to_sample = []
    for i in range(effective_years):
        year = current_year - i
        if year >= start_year:
            years_to_sample.append(year)

    # 如果年份不够，从start_year开始补
    if len(years_to_sample) < effective_years:
        for year in range(start_year, current_year + 1):
            if year not in years_to_sample:
                years_to_sample.append(year)
            if len(years_to_sample) >= effective_years:
                break

    years_to_sample = sorted(years_to_sample)

    logger.info(f"[v6] 年份采样: {years_to_sample}, 每年{per_year}条")

    for year in years_to_sample:
        year_count = 0
        cursor = str(int(datetime(year, 7, 1).timestamp() * 1000))

        # 计算需要多少页
        pages_needed = (per_year // 20) + 1

        for page in range(pages_needed):
            if year_count >= per_year:
                break

            payload = {
                "rid": f"R_SO_4_{song_id}",
                "threadId": f"R_SO_4_{song_id}",
                "pageNo": "1",
                "pageSize": "20",
                "cursor": cursor,
                "offset": "0",
                "orderType": "1",
                "csrf_token": "",
            }

            try:
                params = create_weapi_params(payload)
                data = {"params": params["params"], "encSecKey": params["encSecKey"]}
                resp = requests.post(url, data=data, headers=headers, timeout=15)
                res_data = resp.json()

                if res_data.get("code") != 200:
                    break

                comments = res_data.get("data", {}).get("comments", [])
                if not comments:
                    break

                for c in comments:
                    if year_count >= per_year:
                        break

                    cid = str(c.get("commentId", ""))
                    c_time = c.get("time", 0)

                    if not cid or cid in seen_ids:
                        continue

                    # 只保留当年评论
                    if c_time:
                        c_year = datetime.fromtimestamp(c_time / 1000).year
                        if c_year != year:
                            continue

                    seen_ids.add(cid)
                    year_dist[year] += 1
                    year_count += 1

                    result.append(
                        {
                            "comment_id": cid,
                            "content": c.get("content", ""),
                            "liked_count": c.get("likedCount", 0),
                            "timestamp": c_time,
                            "user_nickname": c.get("user", {}).get("nickname", ""),
                            "source": "yearly",
                        }
                    )

                # 更新cursor
                if comments:
                    cursor = str(comments[-1].get("time", 0))

            except Exception as e:
                logger.warning(f"[v6] 年份{year}采样异常: {e}")
                break

            time.sleep(0.5)

        if year_count > 0:
            logger.info(f"[v6] {year}年: {year_count}条")

    return result, dict(year_dist)


def save_comments_to_db(song_id: str, comments: List[Dict]) -> int:
    """保存评论到数据库"""
    session = get_session()
    saved = 0

    try:
        for c in comments:
            cid = c.get("comment_id")
            if not cid:
                continue

            existing = session.query(Comment).filter_by(comment_id=cid).first()
            if existing:
                continue

            try:
                new_comment = Comment(
                    comment_id=cid,
                    song_id=song_id,
                    content=c.get("content", ""),
                    liked_count=c.get("liked_count", 0),
                    timestamp=c.get("timestamp", 0),
                    user_nickname=c.get("user_nickname", ""),
                )
                session.add(new_comment)
                saved += 1
            except:
                continue

        session.commit()
        logger.info(f"[v6] 保存{saved}条到数据库")
    except Exception as e:
        session.rollback()
        logger.error(f"保存失败: {e}")
    finally:
        session.close()

    return saved


# ==================== 主入口 ====================


def sample_comments(
    song_id: str, api_total: int, level: str = "standard", save_to_db: bool = True
) -> Dict[str, Any]:
    """
    v6 简化版采样主入口

    Args:
        song_id: 歌曲ID
        api_total: API评论总数
        level: "quick" / "standard" / "deep"
        save_to_db: 是否保存到数据库

    Returns:
        {
            "status": "success",
            "level": "standard",
            "target": 600,
            "actual": 587,
            "samples": {
                "hot": 15,
                "recent": 172,
                "yearly": 400
            },
            "coverage": {
                "years_span": 8,
                "years_sampled": 8,
                "year_distribution": {2017: 50, 2018: 50, ...}
            },
            "params_used": {...},
            "ai_guidance": {...}
        }
    """
    start_time = time.time()

    if level not in LEVEL_TARGETS:
        level = "standard"

    target = LEVEL_TARGETS[level]

    logger.info(f"[v6] 开始采样: song_id={song_id}, level={level}, target={target}")

    # 获取已有评论ID
    existing_ids = get_existing_comment_ids(song_id)
    db_count_before = len(existing_ids)

    # 如果数据库已有足够数据
    if db_count_before >= target:
        logger.info(f"[v6] 数据库已有{db_count_before}条，跳过采样")
        return _build_result_from_db(song_id, api_total, level, target, db_count_before)

    # 计算年份跨度
    publish_year = get_publish_year(song_id)
    current_year = datetime.now().year
    years_span = current_year - publish_year + 1

    # 计算采样参数
    params = calculate_sampling_params(target, years_span, api_total)
    logger.info(f"[v6] 采样参数: {params}")

    # 1. 热评
    hot_comments = sample_hot_comments(song_id, existing_ids)
    existing_ids.update(c["comment_id"] for c in hot_comments)

    # 2. 最新评论
    recent_comments = []
    if params["recent"] > 0:
        recent_comments = sample_recent_comments(
            song_id, existing_ids, params["recent"]
        )
        existing_ids.update(c["comment_id"] for c in recent_comments)

    # 3. 年份评论
    yearly_comments = []
    year_dist = {}
    if params["per_year"] > 0 and params["effective_years"] > 0:
        yearly_comments, year_dist = sample_yearly_comments(
            song_id,
            existing_ids,
            publish_year,
            params["effective_years"],
            params["per_year"],
        )

    elapsed = time.time() - start_time

    # 合并结果
    all_comments = hot_comments + recent_comments + yearly_comments
    fetched_total = len(all_comments)

    # 保存到数据库
    saved = 0
    if save_to_db and all_comments:
        saved = save_comments_to_db(song_id, all_comments)

    db_count_after = db_count_before + saved

    # 计算高赞数量（structural维度需要）
    # 注意：这里统计的是本轮抓到的样本中的高赞数，DB里可能更多
    high_likes_count = len([c for c in all_comments if c.get("liked_count", 0) >= 1000])

    result = {
        "status": "success",
        "level": level,
        "target": target,
        "actual": db_count_after,
        "actual_new": saved,
        "api_total": api_total,
        "sample_rate": f"{db_count_after / api_total * 100:.2f}%" if api_total > 0 else "N/A",
        "coverage": {
            "publish_year": publish_year,
            "years_span": years_span,
            "years_sampled": len(year_dist),
            "year_distribution": year_dist,
        },
        "samples": {
            "hot": len(hot_comments),
            "recent": len(recent_comments),
            "yearly": len(yearly_comments),
            "high_likes": high_likes_count,
        },
        "db": {"before": db_count_before, "after": db_count_after, "added": saved},
        "time_spent": f"{elapsed:.1f}s",
    }

    logger.info(
        f"[v6] 采样完成: fetched={fetched_total}, saved={saved}, db={db_count_before}->{db_count_after}, 耗时{elapsed:.1f}s"
    )

    return result


def _build_result_from_db(
    song_id: str, api_total: int, level: str, target: int, db_count: int
) -> Dict:
    """从数据库已有数据构建结果"""
    session = get_session()
    try:
        comments = session.query(Comment).filter_by(song_id=song_id).all()

        year_dist = defaultdict(int)
        high_likes = 0
        for c in comments:
            if c.timestamp:
                year = datetime.fromtimestamp(c.timestamp / 1000).year
                year_dist[year] += 1
            if c.liked_count and c.liked_count >= 1000:
                high_likes += 1

        years = sorted(year_dist.keys())
        years_span = (years[-1] - years[0] + 1) if years else 0

        return {
            "status": "success",
            "level": level,
            "target": target,
            "actual": db_count,
            "actual_new": 0,
            "api_total": api_total,
            "sample_rate": f"{db_count / api_total * 100:.2f}%" if api_total > 0 else "N/A",
            "note": "using_existing_db_data",
            "coverage": {
                "years_span": years_span,
                "years_sampled": len(year_dist),
                "year_distribution": dict(year_dist),
            },
            "samples": {
                "hot": 0,
                "recent": 0,
                "yearly": 0,
                "high_likes": high_likes,
            },
            "db": {"before": db_count, "after": db_count, "added": 0},
        }
    finally:
        session.close()


