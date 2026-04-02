"""
智能翻页采样模块 - AI决策驱动

设计理念:
1. 提供元信息（metadata），让AI了解数据全貌
2. AI根据任务需求，决定要哪几页
3. 灵活支持热门排序、时间排序

参考:
- netease_cloud_music/collector.py - 翻页逻辑（PAGE_SIZE=20, offset计算）
- netease_cloud_music/api_v2.py:104-119 - 热门/最新排序逻辑
"""

import sys
import os
import requests
from typing import List, Dict, Any, Optional
from datetime import datetime
import builtins as _builtins


def _safe_print(*args, **kwargs):
    """避免污染 STDIO 协议输出：默认将 print 输出到 stderr。"""
    if "file" not in kwargs:
        kwargs["file"] = sys.stderr
    return _builtins.print(*args, **kwargs)


# 仅影响本模块内的 print() 调用
print = _safe_print


# 添加路径
current_dir = os.path.dirname(os.path.abspath(__file__))
project_root = os.path.dirname(os.path.dirname(current_dir))
netease_path = os.path.join(project_root, "netease_cloud_music")
if netease_path not in sys.path:
    sys.path.insert(0, netease_path)

from database import init_db, Song, Comment
from netease_analysis.tools.workflow_errors import workflow_error  # v0.6.6: 统一错误处理

# 配置
PAGE_SIZE = 20  # 与collector.py保持一致


def get_session():
    """获取数据库session"""
    db_path = os.path.join(project_root, "data", "music_data_v2.db")
    return init_db(f"sqlite:///{db_path}")


def get_real_comments_count_from_api(song_id: str) -> Dict[str, Any]:
    """
    从网易云API直接获取真实评论总数（不爬取，只获取元数据）

    这是解决"不知道真实评论数"问题的关键工具！

    Args:
        song_id: 歌曲ID

    Returns:
        {
            "song_id": "1901371647",
            "api_total_comments": 307950,  # API上真实的总评论数
            "total_comments": 307950,      # 对外统一字段
            "api_total_pages": 15398,      # 真实的总页数（307950÷20）
            "has_more": True,               # 是否还有更多评论
            "note": "数据来自网易云API，未爬取评论内容"
        }

    用途：
        - 在爬取前了解数据规模
        - 预估爬取耗时
        - 决定采样策略

    速度：约1秒（只请求1条评论的API）
    """
    try:
        # 只请求第一页的1条评论，获取total字段
        url = f"http://music.163.com/api/v1/resource/comments/R_SO_4_{song_id}?limit=1&offset=0"

        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
        }

        # 加载Cookie（如果存在）
        cookie = _load_cookie()
        if cookie:
            headers["Cookie"] = cookie

        response = requests.get(url, headers=headers, timeout=10)

        if response.status_code != 200:
            return {
                "error": f"API请求失败: HTTP {response.status_code}",
                "song_id": song_id,
            }

        data = response.json()

        if data.get("code") != 200:
            return {"error": f"API返回错误: {data.get('code')}", "song_id": song_id}

        # 获取真实总数（显式处理None）
        total_comments = data.get("total") or 0
        total_pages = (total_comments + PAGE_SIZE - 1) // PAGE_SIZE  # 向上取整

        return {
            "song_id": song_id,
            "api_total_comments": total_comments,
            "total_comments": total_comments,
            "api_total_pages": total_pages,
            "has_more": data.get("more", False),
            "page_size": PAGE_SIZE,
            "note": "数据来自网易云API，未爬取评论内容，仅1秒即可获取真实总数",
        }

    except Exception as e:
        return {"error": f"获取评论总数失败: {str(e)}", "song_id": song_id}


def get_comments_metadata(
    song_id: str, include_api_count: bool = True
) -> Dict[str, Any]:
    """
    获取评论元信息（AI决策依据） - 同时返回数据库和API的真实数据

    Args:
        song_id: 歌曲ID
        include_api_count: 是否从API获取真实评论总数（默认True，耗时约1秒）

    Returns:
        {
            "song_id": "185811",
            "song_name": "晴天",

            # 数据库中的数据（已保存的）
            "database": {
                "total_comments": 70,
                "total_pages": 4,
                "data_completeness": "basic"
            },

            # API上的真实数据（未爬取，仅元信息）
            "api": {
                "total_comments": 307950,  # 真实总数！
                "total_pages": 15398,
                "estimated_crawl_time_minutes": 128  # 预估爬取耗时
            },

            "page_size": 20,
            "time_range": {...},  # 基于数据库中已有评论
            "engagement": {...},  # 基于数据库中已有评论

            # 对比和建议
            "comparison": {
                "database_coverage": "0.02%",  # 数据库覆盖率
                "missing_comments": 307880,
                "suggestion": "数据库仅有0.02%的评论，建议使用API模式或先爬取全部数据"
            }
        }
    """
    session = get_session()
    try:
        # v0.6.6: Song query uses id
        song = session.query(Song).filter_by(id=song_id).first()
        if not song:
            # v0.6.6: 使用 workflow_error 引导正确流程
            return workflow_error("song_not_found", "get_comments_metadata_tool")

        # 获取数据库中的所有评论
        comments = session.query(Comment).filter_by(song_id=song_id).all()

        # 统计删除情况
        active_comments = [c for c in comments if not c.is_deleted]
        deleted_comments = [c for c in comments if c.is_deleted]

        db_total_comments = len(active_comments)  # 只计算未删除的
        db_total_pages = (db_total_comments + PAGE_SIZE - 1) // PAGE_SIZE

        # 时间范围分析（基于数据库）
        timestamps = [c.timestamp for c in comments if c.timestamp]
        time_range = {}
        if timestamps:
            earliest_ts = min(timestamps)
            latest_ts = max(timestamps)
            span_days = (latest_ts - earliest_ts) / (1000 * 60 * 60 * 24)

            time_range = {
                "earliest": datetime.fromtimestamp(earliest_ts / 1000).strftime(
                    "%Y-%m-%d %H:%M:%S"
                ),
                "latest": datetime.fromtimestamp(latest_ts / 1000).strftime(
                    "%Y-%m-%d %H:%M:%S"
                ),
                "span_days": int(span_days),
            }
        else:
            time_range = {"note": "No timestamp data"}

        # 互动度分析（基于数据库）
        liked_counts = [c.liked_count for c in comments if c.liked_count]
        if liked_counts:
            avg_liked = sum(liked_counts) / len(liked_counts)
            max_liked = max(liked_counts)
            high_engagement_count = sum(1 for lc in liked_counts if lc > 100)
        else:
            avg_liked = 0
            max_liked = 0
            high_engagement_count = 0

        # 判断数据完整性
        data_completeness = "full" if db_total_comments >= 100 else "basic"

        # 构建数据库部分
        database_info = {
            "total_comments": db_total_comments,  # 未删除的评论数
            "total_pages": db_total_pages,
            "data_completeness": data_completeness,
            "deleted_comments": len(deleted_comments),  # 被删除的评论数
            "total_in_db": len(comments),  # 数据库总评论数(包含已删除)
        }

        # 删除统计(如果有删除的评论)
        if deleted_comments:
            deleted_timestamps = [
                c.deleted_at for c in deleted_comments if c.deleted_at
            ]
            if deleted_timestamps:
                latest_deletion = max(deleted_timestamps)
                database_info["latest_deletion_time"] = datetime.fromtimestamp(
                    latest_deletion / 1000
                ).strftime("%Y-%m-%d %H:%M:%S")

        # 从API获取真实总数
        api_info = {}
        comparison = {}

        if include_api_count:
            api_data = get_real_comments_count_from_api(song_id)
            if "error" not in api_data:
                api_total = api_data.get("api_total_comments", 0)
                api_info = {
                    "total_comments": api_total,
                    "total_pages": api_data.get("api_total_pages", 0),
                    "estimated_crawl_time_minutes": _estimate_crawl_time(api_total),
                }

                # 计算对比
                if api_total > 0:
                    coverage = (db_total_comments / api_total) * 100
                    missing = api_total - db_total_comments

                    # 判断数据状态
                    if coverage > 100:
                        data_status = "outdated"  # 数据过时
                    elif coverage >= 95:
                        data_status = "fresh"  # 数据新鲜
                    elif coverage >= 50:
                        data_status = "partial"  # 部分数据
                    else:
                        data_status = "insufficient"  # 数据不足

                    comparison = {
                        "database_coverage": f"{coverage:.2f}%",
                        "missing_comments": missing,
                        "data_status": data_status,  # 新增!明确的状态标识
                        "suggestion": _generate_suggestion(
                            db_total_comments, api_total
                        ),
                        "sampling_recommendation": _generate_sampling_recommendation(
                            db_total_comments, api_total, song_id
                        ),  # Phase 4: 新增采样建议
                    }

        # 返回完整结果
        result = {
            "song_id": song_id,
            "song_name": song.name,
            "database": database_info,
            "page_size": PAGE_SIZE,
            "time_range": time_range,
            "engagement": {
                "avg_liked_count": round(avg_liked, 2),
                "max_liked_count": max_liked,
                "high_engagement_count": high_engagement_count,
                "note": "基于数据库中已有评论",
            },
        }
        result["database_count"] = database_info.get("total_comments", 0)
        result["cache_status"] = getattr(song, "cache_level", "unknown")

        if api_info:
            result["api"] = api_info

        if comparison:
            result["comparison"] = comparison

        return result

    finally:
        session.close()


def get_comments_by_pages(
    song_id: str, pages: List[int], sort_by: str = "time", data_source: str = "auto"
) -> Dict[str, Any]:
    """
    AI指定要哪几页（灵活翻页）

    Args:
        song_id: 歌曲ID
        pages: AI决定的页码列表，例如 [1, 14, 27, 40, 54]（时间线均匀采样）
               或 [1, 2, 3]（只看最热门/最新）
               ⚠️ 限制: 最多50页，每页20条，最多返回1000条评论
        sort_by: 排序方式
            - "time": 按时间倒序（最新在前）
            - "hot": 按点赞数倒序（最热门在前）
        data_source: 数据来源选择
            - "auto": 自动选择（优先数据库，如果数据不足则从API获取）
            - "database": 仅从数据库获取
            - "api": 直接从网易云API获取（实时数据，但较慢）

    Returns:
        {
            "song_id": "185811",
            "sort_by": "time",
            "data_source": "api",  # 实际使用的数据源
            "pages_requested": [1, 14, 27, 40, 54],
            "pages_returned": 5,
            "comments": [
                {
                    "comment_id": "xxx",
                    "content": "...",
                    "liked_count": 120,
                    "timestamp": 1234567890,
                    "page": 1,
                    "position_in_page": 5
                },
                ...
            ],
            "total_comments_returned": 100
        }
    """
    # ===== 参数验证 (防止Token爆炸) =====
    MAX_PAGES = 50
    MAX_PAGE_NUMBER = 10000

    # 1. 验证页数限制
    if len(pages) > MAX_PAGES:
        return {
            "status": "error",
            "message": f"请求页数过多 ({len(pages)}页)，最多允许 {MAX_PAGES} 页",
            "requested_pages": len(pages),
            "max_allowed": MAX_PAGES,
            "estimated_comments": len(pages) * 20,
            "suggestion": "如需完整数据，请使用 crawl_all_comments_for_song 爬取全部到数据库",
        }

    # 2. 验证页码范围
    invalid_pages = [p for p in pages if p < 1 or p > MAX_PAGE_NUMBER]
    if invalid_pages:
        return {
            "status": "error",
            "message": f"页码超出有效范围: {invalid_pages}",
            "valid_range": f"1-{MAX_PAGE_NUMBER}",
            "suggestion": "请检查页码是否正确",
        }

    # 3. 验证sort_by参数
    if sort_by not in ["time", "hot"]:
        return {
            "status": "error",
            "message": f"无效的排序方式: {sort_by}",
            "valid_options": ["time", "hot"],
        }

    # 4. 验证data_source参数
    if data_source not in ["auto", "database", "api"]:
        return {
            "status": "error",
            "message": f"无效的数据源: {data_source}",
            "valid_options": ["auto", "database", "api"],
        }

    session = get_session()
    try:
        # 检查数据库中的评论数
        db_comment_count = session.query(Comment).filter_by(song_id=song_id).count()

        # ===== 自动选择数据源 (基于覆盖率智能判断) =====
        if data_source == "auto":
            # 获取完整的元数据(包括API总数和覆盖率)
            metadata = get_comments_metadata(song_id, include_api_count=True)

            # 提取覆盖率和数据状态
            if (
                "comparison" in metadata
                and "database_coverage" in metadata["comparison"]
            ):
                coverage_str = metadata["comparison"]["database_coverage"]
                try:
                    coverage = float(coverage_str.strip("%"))
                except:
                    coverage = 0

                data_status = metadata["comparison"].get("data_status", "unknown")

                # 智能判断逻辑
                if data_status == "insufficient" or coverage < 10:
                    actual_source = "api"
                    print(
                        f"[Auto模式] DB覆盖率{coverage:.1f}%不足 (status:{data_status}),从API获取最新数据"
                    )

                elif data_status == "fresh" or coverage >= 95:
                    actual_source = "database"
                    print(
                        f"[Auto模式] DB覆盖率{coverage:.1f}% (status:{data_status}),数据充足,使用数据库"
                    )

                elif data_status == "partial":  # 50-95%
                    # 根据绝对数量辅助判断
                    if db_comment_count >= 500:
                        actual_source = "database"
                        print(
                            f"[Auto模式] DB已有{db_comment_count}条评论(覆盖率{coverage:.1f}%),足够分析"
                        )
                    else:
                        actual_source = "api"
                        print(
                            f"[Auto模式] 补充采样以提高分析质量(当前{db_comment_count}条,覆盖率{coverage:.1f}%)"
                        )

                else:  # outdated或其他
                    actual_source = "api"
                    print(f"[Auto模式] 数据状态异常({data_status}),从API重新获取")

            else:
                # 降级策略: 没有comparison字段时使用简单判断
                if db_comment_count < 100:
                    actual_source = "api"
                    print(f"[Auto模式-降级] DB仅有{db_comment_count}条,从API获取")
                else:
                    actual_source = "database"
                    print(f"[Auto模式-降级] DB有{db_comment_count}条,使用数据库")
        else:
            actual_source = data_source

        # 从API获取评论
        if actual_source == "api":
            return _fetch_comments_from_api(song_id, pages, sort_by)

        # 从数据库获取评论
        all_comments = session.query(Comment).filter_by(song_id=song_id).all()

        if not all_comments:
            return {
                "status": "error",
                "message": "数据库中没有找到评论数据",
                "song_id": song_id,
                "suggestion": "请使用 data_source='api' 从网易云API获取评论",
            }

        # 排序
        if sort_by == "hot":
            # 参考 api_v2.py:106 - 热门排序（按点赞数倒序）
            sorted_comments = sorted(
                all_comments, key=lambda c: c.liked_count or 0, reverse=True
            )
        elif sort_by == "time":
            # 参考 api_v2.py:119 - 时间排序（最新在前）
            sorted_comments = sorted(
                all_comments, key=lambda c: c.timestamp or 0, reverse=True
            )
        else:
            return {
                "error": f"Invalid sort_by: {sort_by}",
                "valid_options": ["time", "hot"],
            }

        # 分页提取
        result_comments = []
        for page in pages:
            if page < 1:
                continue

            # 计算offset（参考 collector.py:45）
            offset = (page - 1) * PAGE_SIZE
            page_comments = sorted_comments[offset : offset + PAGE_SIZE]

            for i, comment in enumerate(page_comments, 1):
                result_comments.append(
                    {
                        "comment_id": comment.comment_id,
                        "content": comment.content,
                        "liked_count": comment.liked_count,
                        "timestamp": comment.timestamp,
                        "user_nickname": comment.user_nickname
                        if hasattr(comment, "user_nickname")
                        else None,
                        "page": page,
                        "position_in_page": i,
                    }
                )

        return {
            "song_id": song_id,
            "sort_by": sort_by,
            "data_source": actual_source,
            "pages_requested": pages,
            "pages_returned": len(pages),
            "total_comments_returned": len(result_comments),
            "comments": result_comments,
        }

    finally:
        session.close()


def _fetch_comments_from_api(
    song_id: str, pages: List[int], sort_by: str = "time"
) -> Dict[str, Any]:
    """
    从网易云API直接获取评论（不依赖数据库）

    Args:
        song_id: 歌曲ID
        pages: 页码列表
        sort_by: 排序方式 ("time" 或 "hot")

    Returns:
        评论数据字典
    """
    result_comments = []

    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    }

    # 加载Cookie（如果存在）
    cookie = _load_cookie()
    if cookie:
        headers["Cookie"] = cookie

    for page in pages:
        if page < 1:
            continue

        # 计算offset
        offset = (page - 1) * PAGE_SIZE

        # 构造API URL（使用V1 GET接口，参考collector.py:48）
        url = f"http://music.163.com/api/v1/resource/comments/R_SO_4_{song_id}?limit={PAGE_SIZE}&offset={offset}"

        try:
            response = requests.get(url, headers=headers, timeout=10)

            if response.status_code != 200:
                print(f"[API Error] 请求第 {page} 页失败: HTTP {response.status_code}")
                continue

            data = response.json()

            if data.get("code") != 200:
                print(f"[API Error] 第 {page} 页返回错误: {data.get('code')}")
                continue

            comments = data.get("comments", [])

            # 解析评论
            for i, comment in enumerate(comments, 1):
                user_info = comment.get("user", {})
                result_comments.append(
                    {
                        "comment_id": str(comment.get("commentId", "")),
                        "content": comment.get("content", ""),
                        "liked_count": comment.get("likedCount", 0),
                        "timestamp": comment.get("time", 0),
                        "user_nickname": user_info.get("nickname", ""),
                        "page": page,
                        "position_in_page": i,
                    }
                )

            # 简单的延迟，避免请求过快
            import time

            time.sleep(0.5)

        except Exception as e:
            print(f"[API Error] 请求第 {page} 页异常: {e}")
            continue

    # 如果需要按热门排序，重新排序
    if sort_by == "hot":
        result_comments.sort(key=lambda c: c["liked_count"], reverse=True)

    return {
        "song_id": song_id,
        "sort_by": sort_by,
        "data_source": "api",
        "pages_requested": pages,
        "pages_returned": len(pages),
        "total_comments_returned": len(result_comments),
        "comments": result_comments,
        "note": "数据直接来自网易云API，未保存到数据库",
    }


def _load_cookie():
    """加载Cookie文件（如果存在）"""
    try:
        cookie_path = os.path.join(project_root, "netease_cloud_music", "cookie.txt")
        if os.path.exists(cookie_path):
            with open(cookie_path, "r", encoding="utf-8") as f:
                content = f.read().strip()
                if content and not content.startswith("#"):
                    return content
    except Exception as e:
        print(f"[Warning] 读取Cookie失败: {e}")
    return None


def _estimate_crawl_time(total_comments: int) -> int:
    """
    预估爬取耗时（分钟）

    假设：
    - 每页20条评论
    - 每页爬取耗时约1.5秒（包括网络延迟和休眠）
    """
    if total_comments <= 0:
        return 0

    total_pages = (total_comments + PAGE_SIZE - 1) // PAGE_SIZE
    seconds_per_page = 1.5
    total_seconds = total_pages * seconds_per_page
    total_minutes = int(total_seconds / 60)

    return total_minutes


def _generate_sampling_recommendation(
    db_count: int, api_count: int, song_id: str
) -> dict:
    """Phase 4: 生成采样智能建议（AI决策树）

    Args:
        db_count: 数据库评论数
        api_count: API评论总数
        song_id: 歌曲ID

    Returns:
        采样建议字典
    """
    # 情况1：总评论 < 100
    if api_count < 100:
        return {
            "should_crawl_all": True,
            "should_sample": False,
            "reason": f"评论总数较少（{api_count}条），建议全量爬取",
            "recommended_action": f"crawl_all_comments_for_song(song_id='{song_id}')",
            "expected_time": f"约{_estimate_crawl_time(api_count)}分钟",
        }

    # 情况2：总评论 100-5000
    elif api_count <= 5000:
        total_pages = (api_count + 19) // 20
        step = max(total_pages // 5, 1)
        recommended_pages = [
            1 + i * step for i in range(5) if 1 + i * step <= total_pages
        ]

        return {
            "should_crawl_all": False,
            "should_sample": True,
            "reason": f"评论数适中（{api_count}条），建议采样分析即可",
            "recommended_action": f"get_comments_by_pages_tool(song_id='{song_id}', pages={recommended_pages})",
            "smart_sampling": {
                "recommended_pages": recommended_pages,
                "strategy": "均匀分布采样",
                "expected_count": f"约{len(recommended_pages) * 20}条",
                "call_example": f"get_comments_by_pages_tool(song_id='{song_id}', pages={recommended_pages})",
            },
        }

    # 情况3：总评论 > 5000
    else:
        total_pages = (api_count + 19) // 20
        step = max(total_pages // 5, 1)
        recommended_pages = [
            1 + i * step for i in range(5) if 1 + i * step <= total_pages
        ]

        return {
            "should_crawl_all": False,
            "should_sample": True,
            "reason": f"评论数较多（{api_count}条），强烈建议采样而非全量爬取",
            "recommended_action": f"get_comments_by_pages_tool(song_id='{song_id}', pages={recommended_pages})",
            "smart_sampling": {
                "recommended_pages": recommended_pages,
                "strategy": "均匀分布采样",
                "expected_count": f"约{len(recommended_pages) * 20}条",
                "call_example": f"get_comments_by_pages_tool(song_id='{song_id}', pages={recommended_pages})",
            },
            "warning": "全量爬取将耗时较长且可能超出分析工具限制（MAX=5000）",
        }


def _generate_suggestion(db_count: int, api_count: int) -> str:
    """
    根据数据库和API的评论数生成建议

    Args:
        db_count: 数据库中的评论数
        api_count: API上的真实评论数

    Returns:
        建议文本
    """
    if api_count == 0:
        return "该歌曲没有评论"

    # ===== 新增：样本量过小检测（最优先） =====
    MIN_SAMPLE_SIZE = 100  # 最小可靠样本量

    # 情况1：API总评论数太少（这是歌曲本身的问题）
    if api_count < MIN_SAMPLE_SIZE:
        return (
            f"⚠️ 样本量过小警告：该歌曲总共只有 {api_count} 条评论（数据库已有{db_count}条）。\n"
            f"统计学建议：至少需要100条评论才能进行可靠的情感分析。\n"
            f"当前数据质量：不建议分析（样本量不足，结论可能不可靠）\n"
            f"建议：1) 更换评论数更多的歌曲，或 2) 明确告知用户分析基于极小样本"
        )

    # 情况2：数据库评论数太少（即使API有很多）
    if db_count < MIN_SAMPLE_SIZE:
        coverage = (db_count / api_count) * 100
        return (
            f"⚠️ 数据库样本量过小：仅有 {db_count} 条评论（API共{api_count}条，覆盖率{coverage:.1f}%）。\n"
            f"统计学建议：至少需要100条评论才能进行可靠的情感分析。\n"
            f"当前数据质量：不足以支持可靠分析。\n"
            f"建议：1) 爬取更多评论（至少100条），或 2) 使用 data_source='api' 智能采样"
        )

    # ===== 以下是原有逻辑（样本量充足时才会执行） =====
    coverage = (db_count / api_count) * 100
    missing = api_count - db_count
    estimated_time = _estimate_crawl_time(api_count)

    # 数据过时检测 (覆盖率>100%)
    if coverage > 100:
        return (
            f"⚠️ 数据异常：数据库有{db_count}条评论，但API显示只有{api_count}条（覆盖率{coverage:.1f}%）。"
            f"这通常意味着：1) 网易云删除了部分评论，或 2) 数据库数据已过时。"
            f"建议：1) 重新爬取最新数据（推荐），或 2) 使用现有数据但需注意可能不准确"
        )

    # 数据完整且新鲜 (95-100%)
    elif coverage >= 95:
        if missing == 0:
            return "✅ 数据库评论数与API一致，数据完整且新鲜，可直接分析"
        else:
            return (
                f"数据库已包含{coverage:.1f}%的评论（缺失{missing}条最新评论）。"
                f"建议：1) 使用现有数据直接分析（推荐，数据已很完整），或 2) 补充爬取{missing}条最新评论"
            )

    # 数据较完整 (50-95%)
    elif coverage >= 50:
        return (
            f"数据库包含{coverage:.1f}%的评论（缺失{missing}条）。"
            f"建议：1) 使用现有数据快速分析，或 2) 爬取完整数据（预估耗时{estimated_time}分钟）"
        )

    # 数据不足但可用 (10-50%)
    elif coverage >= 10:
        return (
            f"数据库仅包含{coverage:.1f}%的评论（缺失{missing}条）。"
            f"建议：1) 使用 data_source='api' 智能采样，或 2) 爬取全部数据（预估耗时{estimated_time}分钟）"
        )

    # 数据严重不足 (<10%)
    else:
        return (
            f"数据库仅包含{coverage:.2f}%的评论（缺失{missing}条）。"
            f"建议：1) 使用 data_source='api' 按需采样（快速），或 2) 先调用 crawl_all_comments_for_song 爬取全部（预估耗时{estimated_time}分钟）"
        )


# 领域知识已迁移到独立模块
# 延迟导入避免循环依赖
def _get_platform_knowledge():
    """延迟导入以避免循环依赖"""
    import sys
    import os

    knowledge_path = os.path.join(
        os.path.dirname(os.path.dirname(__file__)), "knowledge"
    )
    if knowledge_path not in sys.path:
        sys.path.insert(0, knowledge_path)
    from knowledge_loader import get_platform_domain_knowledge as _get

    return _get()


# 保持向后兼容
get_platform_domain_knowledge = lambda: _get_platform_knowledge()


def get_cultural_context(song_id: str) -> Dict[str, Any]:
    """
    提供文化背景提示（帮助AI理解"网抑云"等现象）

    这是"认知拓展"的关键工具！

    设计重构：
    - ❌ 旧版：硬编码知识在代码中
    - ✅ 新版：从JSON配置文件加载知识

    Args:
        song_id: 歌曲ID

    Returns:
        {
            "song_name": "晴天",
            "artist": "周杰伦",
            "cultural_context": {
                "platform_slang": {...},     # 网抑云、emo等网络用语
                "artist_background": {...},   # 艺术家文化背景
                "song_era": {...},           # 歌曲年代特征
                "comment_patterns": {...}    # 评论区文化模式
            },
            "usage": "AI可以用这些背景知识理解评论区的'黑话'和文化现象"
        }
    """
    from netease_analysis.knowledge import KnowledgeLoader

    session = get_session()
    try:
        song = session.query(Song).filter_by(id=song_id).first()

        if not song:
            return {
                "status": "error",
                "message": "歌曲未找到",
                "suggestion": "请先使用 search_songs_tool 搜索歌曲并添加到数据库",
            }

        # 加载文化背景知识库
        loader = KnowledgeLoader()
        cultural_knowledge = loader.get_cultural_context()

        # 提取相关知识
        artist_name = song.artists[0].name if song.artists else "Unknown"

        # 构建响应
        cultural_context = {
            "platform_slang": cultural_knowledge.get("platform_slang", {}),
            "artist_background": loader.get_artist_context(artist_name),
            "song_era": _determine_song_era(song, cultural_knowledge),
            "comment_patterns": cultural_knowledge.get("comment_culture_patterns", {}),
        }

        return {
            "song_name": song.name,
            "artist": artist_name,
            "cultural_context": cultural_context,
            "usage": "AI可以用这些背景知识理解评论区的'黑话'和文化现象，所有知识来自可扩展的JSON配置",
        }

    finally:
        session.close()


def _determine_song_era(
    song, cultural_knowledge: Dict[str, Any]
) -> Optional[Dict[str, Any]]:
    """
    判断歌曲所属年代（辅助函数）

    Args:
        song: Song对象
        cultural_knowledge: 文化知识字典

    Returns:
        年代信息字典，或None
    """
    if not hasattr(song, "publish_time") or not song.publish_time:
        return None

    year = song.publish_time // (1000 * 60 * 60 * 24 * 365) + 1970
    eras = cultural_knowledge.get("song_era_markers", {}).get("eras", {})

    # 根据年份匹配年代
    for era_key, era_info in eras.items():
        if "-" in era_key:
            start_str, end_str = era_key.replace("s", "").split("-")
            start = int(start_str)
            end = int(end_str) if end_str != "now" else 2030

            if start <= year < end:
                return {"era": era_key, "year": year, **era_info}

    return {"year": year, "era": "未知年代"}


# ========== 兼容旧接口（可选保留） ==========


def get_representative_comments(song_id: str, limit: int = 10) -> Dict[str, Any]:
    """
    快速获取代表性评论（给AI的精华摘要）

    算法:
    1. 最高赞 3 条
    2. 最新 2 条
    3. 情感极端（最正面 2 条，最负面 2 条）
    4. 随机补充到 limit

    注: 这个函数是旧版的"封装式"工具，保留以供快速查看
    """
    session = get_session()
    try:
        from snownlp import SnowNLP
        import random

        all_comments = session.query(Comment).filter_by(song_id=song_id).all()

        if not all_comments:
            return {
                "status": "error",
                "message": "数据库中没有找到评论数据",
                "suggestion": "请先使用 get_comments_by_pages_tool(data_source='api') 获取评论",
            }

        # 1. 最高赞 3 条
        top_liked = sorted(
            all_comments, key=lambda x: x.liked_count or 0, reverse=True
        )[:3]

        # 2. 最新 2 条
        recent = sorted(all_comments, key=lambda x: x.timestamp or 0, reverse=True)[:2]

        # 3. 情感极端
        scored = []
        for c in all_comments:
            try:
                score = SnowNLP(c.content).sentiments
                scored.append((c, score))
            except:
                pass

        scored.sort(key=lambda x: x[1])
        most_negative = [c for c, s in scored[:2]]
        most_positive = [c for c, s in scored[-2:]]

        # 4. 随机补充
        random_sample = random.sample(all_comments, min(1, len(all_comments)))

        # 合并去重
        all_selected = set(
            [c.id for c in top_liked]
            + [c.id for c in recent]
            + [c.id for c in most_negative]
            + [c.id for c in most_positive]
            + [c.id for c in random_sample]
        )

        # 取前limit条
        selected_comments = [c for c in all_comments if c.id in all_selected][:limit]

        return {
            "total_comments": len(all_comments),
            "representative_count": len(selected_comments),
            "comments": [
                {
                    "content": c.content,
                    "liked_count": c.liked_count,
                    "timestamp": c.timestamp,
                }
                for c in selected_comments
            ],
            "note": "精选代表性评论，包含高赞、最新、情感极端等（快速查看用）",
        }

    finally:
        session.close()


# ========== v0.7.1: 分层采样策略 v2.2 ==========


def stratified_sample_by_cursor(
    song_id: str, years: List[int] = None, samples_per_year: int = 50
) -> Dict[str, Any]:
    """
    Layer 3: 基于cursor时间跳转的历史分层采样

    突破offset限制！可以跳转到任意历史时间点采样。

    Args:
        song_id: 歌曲ID
        years: 要采样的年份列表，如[2024, 2023, 2022, ...]
               默认: 2024-2014共11年
        samples_per_year: 每年采样数量，默认50条

    Returns:
        {
            "song_id": "408332757",
            "strategy": "cursor_stratified",
            "years_sampled": [2024, 2023, ...],
            "samples_per_year": 50,
            "total_sampled": 550,
            "comments": [...],
            "year_distribution": {2024: 50, 2023: 48, ...}
        }
    """
    import time
    from netease_cloud_music.utils import create_weapi_params

    # 默认年份: 2024-2014
    if years is None:
        current_year = datetime.now().year
        years = list(range(current_year, 2013, -1))  # 2024, 2023, ..., 2014

    url = "https://music.163.com/weapi/comment/resource/comments/get?csrf_token="
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
        "Content-Type": "application/x-www-form-urlencoded",
        "Referer": "https://music.163.com/",
    }

    # 加载Cookie
    cookie = _load_cookie()
    if cookie:
        headers["Cookie"] = cookie

    all_samples = []
    year_distribution = {}

    for year in years:
        # 跳转到该年年中 (7月1日)
        cursor = str(int(datetime(year, 7, 1).timestamp() * 1000))
        year_samples = []
        max_requests = 5  # 每年最多请求5次，避免过度请求
        request_count = 0

        while len(year_samples) < samples_per_year and request_count < max_requests:
            request_count += 1

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
                    print(f"[cursor采样] {year}年 API错误: {res_data.get('code')}")
                    break

                comments = res_data.get("data", {}).get("comments", [])
                if not comments:
                    break

                # 只保留该年的评论
                for c in comments:
                    c_time = c.get("time", 0)
                    if c_time:
                        c_year = datetime.fromtimestamp(c_time / 1000).year
                        if c_year == year and len(year_samples) < samples_per_year:
                            year_samples.append(
                                {
                                    "comment_id": str(c.get("commentId", "")),
                                    "content": c.get("content", ""),
                                    "liked_count": c.get("likedCount", 0),
                                    "timestamp": c_time,
                                    "user_nickname": c.get("user", {}).get(
                                        "nickname", ""
                                    ),
                                    "sample_year": year,
                                    "sample_layer": "historical",
                                }
                            )

                # 更新cursor到最后一条评论的时间
                new_cursor = str(comments[-1].get("time", 0))
                if new_cursor == cursor:
                    break
                cursor = new_cursor

                # 延迟避免请求过快
                time.sleep(0.5)

            except Exception as e:
                print(f"[cursor采样] {year}年 请求异常: {e}")
                break

        year_distribution[year] = len(year_samples)
        all_samples.extend(year_samples)
        print(f"[cursor采样] {year}年: 采样{len(year_samples)}条")

    return {
        "song_id": song_id,
        "strategy": "cursor_stratified",
        "years_sampled": years,
        "samples_per_year": samples_per_year,
        "total_sampled": len(all_samples),
        "comments": all_samples,
        "year_distribution": year_distribution,
    }


def get_hot_comments_from_api(song_id: str) -> List[Dict]:
    """
    Layer 1: 获取热门评论（API固定返回15条）
    """
    url = f"http://music.163.com/api/v1/resource/comments/R_SO_4_{song_id}?limit=20&offset=0"
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
    }

    cookie = _load_cookie()
    if cookie:
        headers["Cookie"] = cookie

    try:
        resp = requests.get(url, headers=headers, timeout=10)
        data = resp.json()

        if data.get("code") != 200:
            return []

        hot_comments = data.get("hotComments", [])
        return [
            {
                "comment_id": str(c.get("commentId", "")),
                "content": c.get("content", ""),
                "liked_count": c.get("likedCount", 0),
                "timestamp": c.get("time", 0),
                "user_nickname": c.get("user", {}).get("nickname", ""),
                "sample_layer": "hot",
            }
            for c in hot_comments[:15]
        ]
    except Exception as e:
        print(f"[热评采样] 请求异常: {e}")
        return []


def get_recent_comments_from_api(song_id: str, limit: int = 100) -> List[Dict]:
    """
    Layer 2: 获取最新评论（offset翻页，最多~100条）
    """
    import time

    all_comments = []
    pages_needed = (limit + PAGE_SIZE - 1) // PAGE_SIZE

    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
    }

    cookie = _load_cookie()
    if cookie:
        headers["Cookie"] = cookie

    for page in range(1, pages_needed + 1):
        offset = (page - 1) * PAGE_SIZE
        url = f"http://music.163.com/api/v1/resource/comments/R_SO_4_{song_id}?limit={PAGE_SIZE}&offset={offset}"

        try:
            resp = requests.get(url, headers=headers, timeout=10)
            data = resp.json()

            if data.get("code") != 200:
                break

            comments = data.get("comments", [])
            if not comments:
                break

            for c in comments:
                all_comments.append(
                    {
                        "comment_id": str(c.get("commentId", "")),
                        "content": c.get("content", ""),
                        "liked_count": c.get("likedCount", 0),
                        "timestamp": c.get("time", 0),
                        "user_nickname": c.get("user", {}).get("nickname", ""),
                        "sample_layer": "recent",
                    }
                )

            time.sleep(0.3)

        except Exception as e:
            print(f"[最新评论] 第{page}页请求异常: {e}")
            break

    return all_comments[:limit]


def full_stratified_sample(
    song_id: str, analysis_type: str = "sentiment"
) -> Dict[str, Any]:
    """
    完整的分层采样（组合 Layer 1 + 2 + 3）

    根据分析类型自动调整采样量：
    - sentiment (情感分析): 热评15 + 最新100 + 历史300 = ~400
    - timeline (时间线分析): 热评15 + 最新50 + 历史550 = ~600
    - comparison (PK对比): 热评15 + 最新50 + 历史200 = ~250

    Args:
        song_id: 歌曲ID
        analysis_type: 分析类型 ("sentiment", "timeline", "comparison")

    Returns:
        {
            "song_id": "408332757",
            "analysis_type": "sentiment",
            "sampling_config": {...},
            "hot_comments": [...],
            "recent_comments": [...],
            "historical_comments": [...],
            "all_comments": [...],  # 合并去重后
            "stats": {
                "hot_count": 15,
                "recent_count": 100,
                "historical_count": 300,
                "total_unique": 400,
                "years_covered": 11
            }
        }
    """
    # 根据分析类型确定采样配置
    SAMPLING_CONFIGS = {
        "sentiment": {
            "hot": 15,
            "recent": 100,
            "historical_per_year": 30,  # 300/10年
            "historical_years": 10,
        },
        "timeline": {
            "hot": 15,
            "recent": 50,
            "historical_per_year": 50,  # 550/11年
            "historical_years": 11,
        },
        "comparison": {
            "hot": 15,
            "recent": 50,
            "historical_per_year": 20,  # 200/10年
            "historical_years": 10,
        },
    }

    config = SAMPLING_CONFIGS.get(analysis_type, SAMPLING_CONFIGS["sentiment"])

    print(f"[分层采样] 开始采样 song_id={song_id}, 类型={analysis_type}")
    print(
        f"[分层采样] 配置: 热评{config['hot']} + 最新{config['recent']} + 历史{config['historical_per_year']}条/年×{config['historical_years']}年"
    )

    # Layer 1: 热门评论
    hot_comments = get_hot_comments_from_api(song_id)
    print(f"[分层采样] Layer 1 热评: {len(hot_comments)}条")

    # Layer 2: 最新评论
    recent_comments = get_recent_comments_from_api(song_id, limit=config["recent"])
    print(f"[分层采样] Layer 2 最新: {len(recent_comments)}条")

    # Layer 3: 历史分层采样
    current_year = datetime.now().year
    years = list(range(current_year, current_year - config["historical_years"], -1))
    historical_result = stratified_sample_by_cursor(
        song_id, years=years, samples_per_year=config["historical_per_year"]
    )
    historical_comments = historical_result.get("comments", [])
    print(f"[分层采样] Layer 3 历史: {len(historical_comments)}条")

    # 合并去重
    all_comments = []
    seen_ids = set()

    for c in hot_comments + recent_comments + historical_comments:
        cid = c.get("comment_id")
        if cid and cid not in seen_ids:
            seen_ids.add(cid)
            all_comments.append(c)

    # 统计年份覆盖
    years_covered = set()
    for c in all_comments:
        ts = c.get("timestamp")
        if ts:
            years_covered.add(datetime.fromtimestamp(ts / 1000).year)

    result = {
        "song_id": song_id,
        "analysis_type": analysis_type,
        "sampling_config": config,
        "hot_comments": hot_comments,
        "recent_comments": recent_comments,
        "historical_comments": historical_comments,
        "all_comments": all_comments,
        "stats": {
            "hot_count": len(hot_comments),
            "recent_count": len(recent_comments),
            "historical_count": len(historical_comments),
            "total_unique": len(all_comments),
            "years_covered": len(years_covered),
            "year_list": sorted(years_covered, reverse=True),
        },
    }

    print(
        f"[分层采样] 完成! 总计{len(all_comments)}条唯一评论，覆盖{len(years_covered)}年"
    )

    return result
