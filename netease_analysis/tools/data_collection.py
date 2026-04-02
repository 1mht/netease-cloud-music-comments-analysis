"""
数据收集工具模块
封装歌曲添加、评论爬取等功能
"""

import sys
import os
import requests
import time
import builtins as _builtins


def _safe_print(*args, **kwargs):
    """避免污染 STDIO 协议输出：默认将 print 输出到 stderr。"""
    if "file" not in kwargs:
        kwargs["file"] = sys.stderr
    return _builtins.print(*args, **kwargs)


# 仅影响本模块内的 print() 调用
print = _safe_print


# 添加 netease_cloud_music 到 Python 路径
current_dir = os.path.dirname(os.path.abspath(__file__))
project_root = os.path.dirname(os.path.dirname(current_dir))
netease_path = os.path.join(project_root, "netease_cloud_music")
if netease_path not in sys.path:
    sys.path.insert(0, netease_path)

from database import init_db, Song, Comment, Album, Artist
from db_utils import save_song_info, save_comments, update_lyric
from get_song_lyric import get_lyric
from get_song_id import get_song_detail_by_id
from collector import crawl_all_comments_task


# 创建一个辅助函数
def get_session():
    """获取数据库session"""
    db_path = os.path.join(
        os.path.dirname(os.path.dirname(os.path.dirname(__file__))),
        "data",
        "music_data_v2.db",
    )
    return init_db(f"sqlite:///{db_path}")


def add_song_basic(
    song_data: dict = None, db_path: str = None, song_id: str = None
) -> dict:
    """添加歌曲基础数据到数据库（Level 2: 元数据 + 热门评论 + 最新评论）

    Args:
        song_data: 从 search_songs() 返回的歌曲对象
        db_path: 数据库路径（可选，默认使用配置）

    Returns:
        {
            "status": "success" | "error",
            "song_id": "185811",
            "song_name": "晴天",
            "data_collected": {
                "metadata": True,
                "lyric": True,
                "hot_comments": 50,
                "recent_comments": 20,
                "total_comments": 70
            },
            "message": "..."
        }

    执行内容：
        1. 保存歌曲元数据（ID、名称、歌手、专辑）
        2. 获取并保存歌词
        3. 获取并保存热门评论（前50条）
        4. 获取并保存最新评论（前20条）

    时间：约10-30秒
    """
    session = get_session()
    if not song_data and song_id:
        song_data = get_song_detail_by_id(song_id)
        if not song_data:
            return {
                "status": "error",
                "message": f"Failed to fetch song detail for song_id: {song_id}",
            }

    if not song_data:
        return {"status": "error", "message": "song_data or song_id is required"}

    if not song_id:
        song_id = song_data.get("id")

    if not song_id:
        return {"status": "error", "message": "歌曲数据缺少ID字段"}

    try:
        # 1. 保存歌曲基本信息（元数据 + 艺术家 + 专辑）
        save_song_info(session, song_data)
        print(f"[OK] 保存歌曲元数据: {song_data.get('name')}")

        # 2. 获取并保存歌词
        lyric_saved = False
        try:
            lyric = get_lyric(song_id)
            if lyric:
                update_lyric(session, song_id, lyric)
                lyric_saved = True
                print(f"[OK] 保存歌词")
        except Exception as e:
            print(f"[WARNING]  获取歌词失败: {e}")

        # 3. 获取热门评论（前50条，按点赞数排序）
        hot_comments_count = 0
        api_total_comments = 0
        try:
            url = f"http://music.163.com/api/v1/resource/comments/R_SO_4_{song_id}?limit=50&offset=0"
            headers = {
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
            }
            response = requests.get(url, headers=headers, timeout=10)

            if response.status_code == 200:
                data = response.json()
                api_total_comments = data.get("total", 0)
                hot_comments = data.get("comments", [])
                if hot_comments:
                    save_comments(session, song_id, hot_comments)
                    hot_comments_count = len(hot_comments)
                    print(f"[OK] 保存热门评论: {hot_comments_count} 条")
        except Exception as e:
            print(f"[WARNING]  获取热门评论失败: {e}")

        # 4. 获取最新评论（前20条，按时间排序）
        # 注意：网易云API的sortType参数可能不稳定，这里简单获取最新的offset=50的评论
        recent_comments_count = 0
        try:
            url = f"http://music.163.com/api/v1/resource/comments/R_SO_4_{song_id}?limit=20&offset=50"
            response = requests.get(url, headers=headers, timeout=10)

            if response.status_code == 200:
                data = response.json()
                recent_comments = data.get("comments", [])
                if recent_comments:
                    save_comments(session, song_id, recent_comments)
                    recent_comments_count = len(recent_comments)
                    print(f"[OK] 保存最新评论: {recent_comments_count} 条")
        except Exception as e:
            print(f"[WARNING]  获取最新评论失败: {e}")

        # 提交事务
        session.commit()

        total_comments = hot_comments_count + recent_comments_count

        return {
            "status": "success",
            "song_id": song_id,
            "song_name": song_data.get("name"),
            "api_total_comments": api_total_comments,
            "data_collected": {
                "metadata": True,
                "lyric": lyric_saved,
                "hot_comments": hot_comments_count,
                "recent_comments": recent_comments_count,
                "total_comments": total_comments,
            },
        }

    except Exception as e:
        session.rollback()
        return {"status": "error", "message": f"添加歌曲失败: {str(e)}"}
    finally:
        session.close()


def crawl_all_comments(
    song_id: str,
    confirm: bool = True,
    db_path: str = "data/music_data_v2.db",
    detect_deletions: bool = False,
) -> dict:
    """抓取歌曲的全部评论（Level 3: 深度数据收集，带预估耗时和用户交互）

    ⚠️ DEPRECATED in v0.6.5 - 此工具已弃用但保留

    弃用原因：
    1. 底层代码缺陷：collector.py:153 缺少 return 语句，可能导致 TypeError
    2. 性能问题：50,000条评论需要6小时，用户体验极差
    3. 统计学冗余：根据中心极限定理，1000-2000条采样即可达到95%置信度

    推荐替代方案：
    使用 get_comments_by_pages_tool 进行多轮采样：
    1. get_comments_metadata_tool(song_id) → 获取总数和采样建议
    2. get_comments_by_pages_tool(song_id, pages=[...]) → 均匀采样
    3. 优势：5分钟完成 vs 6小时，统计可靠性相同

    详见：docs/工具弃用说明_v0.6.5.md

    Args:
        song_id: 歌曲ID
        confirm: 是否需要用户确认（默认True，返回预估信息；False则直接开始爬取）
        db_path: 数据库路径
        detect_deletions: 是否检测删除的评论（默认False）
            - True: 爬取后检测并保留被平台删除的评论(用于舆论审查研究)
            - False: 仅添加/更新评论

    Returns:
        当 confirm=True 时（第一次调用）:
        {
            "status": "pending_confirmation",
            "song_id": "185811",
            "song_name": "晴天",
            "api_total_comments": 307950,
            "database_comments": 70,
            "missing_comments": 307880,
            "estimated_time_minutes": 384,
            "estimated_time_readable": "约 6 小时 24 分钟",
            "message": "将要爬取约 307880 条新评论（总计 307950 条），预计耗时 384 分钟（约 6 小时 24 分钟）。",
            "next_step": "如需开始爬取，请调用 crawl_all_comments_for_song(song_id='{song_id}', confirm=False)"
        }

        当 confirm=False 时（确认后开始爬取）:
        {
            "status": "completed" | "error",
            "song_id": "185811",
            "song_name": "晴天",
            "previous_count": 70,
            "total_count": 105342,
            "new_comments": 105272,
            "message": "抓取完成！新增 105272 条评论，总计 105342 条。"
        }

    设计理念：
        - confirm=True: 先预估耗时，返回确认信息，用户可决定是否继续
        - confirm=False: 直接开始爬取（用户已确认）
        - 显示进度（由 crawl_all_comments_task 打印）

    示例对话：
        用户: "我想爬取《孤勇者》的全部评论"
        → 调用 crawl_all_comments(song_id, confirm=True)
        → 返回: "这首歌有 30 万条评论，完整爬取需要约 6 小时。是否继续？"
        用户: "是的，开始吧"
        → 调用 crawl_all_comments(song_id, confirm=False)
        → 开始爬取，实时显示进度
    """
    # 导入放在顶部可能导致循环依赖，所以在函数内导入
    import sys

    current_dir = os.path.dirname(os.path.abspath(__file__))
    if current_dir not in sys.path:
        sys.path.insert(0, current_dir)
    from pagination_sampling import get_real_comments_count_from_api

    session = get_session()

    try:
        # 检查歌曲是否存在
        song = session.query(Song).filter_by(id=song_id).first()

        if not song:
            return {
                "status": "error",
                "message": "歌曲不存在于数据库，请先使用 add_song_basic() 添加歌曲基础信息",
            }

        # 获取当前数据库评论数
        current_count = session.query(Comment).filter_by(song_id=song_id).count()

        # 如果需要用户确认，先获取真实评论总数并返回预估信息
        if confirm:
            # 从API获取真实评论总数
            api_info = get_real_comments_count_from_api(song_id)

            if "error" in api_info:
                session.close()
                return {
                    "status": "error",
                    "message": f"无法获取真实评论数: {api_info.get('error')}",
                }

            # 显式处理None（网易云API可能返回total=None）
            api_total = api_info.get("api_total_comments") or 0
            missing_comments = max(0, api_total - current_count)

            # 预估爬取耗时
            # 假设：每页20条评论，每页耗时1.5秒
            PAGE_SIZE = 20
            pages_to_crawl = (missing_comments + PAGE_SIZE - 1) // PAGE_SIZE
            seconds_per_page = 1.5
            total_seconds = pages_to_crawl * seconds_per_page
            estimated_minutes = int(total_seconds / 60)

            # 转换为可读时间
            hours = estimated_minutes // 60
            minutes = estimated_minutes % 60
            if hours > 0:
                time_readable = f"约 {hours} 小时 {minutes} 分钟"
            else:
                time_readable = f"约 {minutes} 分钟"

            session.close()

            # 如果已经爬取完毕
            if missing_comments <= 0:
                return {
                    "status": "already_complete",
                    "song_id": song_id,
                    "song_name": song.name,
                    "database_comments": current_count,
                    "api_total_comments": api_total,
                    "message": f"数据库已包含全部 {current_count} 条评论，无需重复爬取。",
                }

            return {
                "status": "pending_confirmation",
                "song_id": song_id,
                "song_name": song.name,
                "api_total_comments": api_total,
                "database_comments": current_count,
                "missing_comments": missing_comments,
                "estimated_time_minutes": estimated_minutes,
                "estimated_time_readable": time_readable,
                "message": f"将要爬取约 {missing_comments} 条新评论（总计 {api_total} 条），预计耗时 {estimated_minutes} 分钟（{time_readable}）。",
                "suggestion": "爬取过程中会实时显示进度（已爬取XX页/总XX页）。",
                "next_step": f"如需开始爬取，请调用 crawl_all_comments_for_song(song_id='{song_id}', confirm=False)",
            }

        # confirm=False，开始爬取
        session.close()

        print(f"\n[START] 开始抓取歌曲 {song.name} 的全部评论...")
        print(f"   当前数据库已有: {current_count} 条评论")

        # 修复：确保 db_path 是 SQLAlchemy URL 格式
        if not db_path.startswith("sqlite:///"):
            # 如果是相对路径，转换为绝对路径
            if not os.path.isabs(db_path):
                db_path = os.path.join(
                    os.path.dirname(os.path.dirname(os.path.dirname(__file__))), db_path
                )
            db_path = f"sqlite:///{db_path}"

        # 执行完整爬取
        total_comments = crawl_all_comments_task(
            song_id, db_path, detect_deletions=detect_deletions
        )

        return {
            "status": "completed",
            "song_id": song_id,
            "song_name": song.name,
            "previous_count": current_count,
            "total_count": total_comments,
            "new_comments": total_comments - current_count,
            "message": f"抓取完成！新增 {total_comments - current_count} 条评论，总计 {total_comments} 条。",
        }

    except Exception as e:
        return {"status": "error", "message": f"抓取评论失败: {str(e)}"}


def get_song_details(
    song_id: str, include_comments: bool = True, limit: int = 100
) -> dict:
    """获取数据库中歌曲的完整信息

    Args:
        song_id: 歌曲ID
        include_comments: 是否包含评论内容
        limit: 返回的评论数量限制

    Returns:
        {
            "id": "185811",
            "name": "晴天",
            "artists": ["周杰伦"],
            "album": "叶惠美",
            "lyric": "...",
            "statistics": {
                "total_comments": 105342,
                "data_completeness": "full"  // "basic" | "full"
            },
            "top_comments": [...],  // 如果 include_comments=True
            "recent_comments": [...]  // 如果 include_comments=True
        }
    """
    session = get_session()

    try:
        song = session.query(Song).filter_by(id=song_id).first()

        if not song:
            return {"status": "error", "message": "歌曲不存在于数据库"}

        # 基本信息
        result = {
            "id": song.id,
            "name": song.name,
            "artists": [artist.name for artist in song.artists],
            "album": song.album.name if song.album else None,
            "lyric": song.lyric if song.lyric else None,
            "duration_ms": song.duration_ms,
        }

        # 统计信息
        total_comments = session.query(Comment).filter_by(song_id=song_id).count()
        data_completeness = "full" if total_comments > 1000 else "basic"

        result["statistics"] = {
            "total_comments": total_comments,
            "data_completeness": data_completeness,
        }

        # 评论内容
        if include_comments:
            # 热门评论（按点赞数排序）
            top_comments = (
                session.query(Comment)
                .filter_by(song_id=song_id)
                .order_by(Comment.liked_count.desc())
                .limit(min(50, limit))
                .all()
            )

            result["top_comments"] = [
                {
                    "content": c.content,
                    "liked_count": c.liked_count,
                    "user": c.user_nickname,
                    "timestamp": c.timestamp,
                }
                for c in top_comments
            ]

            # 最新评论（按时间排序）
            recent_comments = (
                session.query(Comment)
                .filter_by(song_id=song_id)
                .order_by(Comment.timestamp.desc())
                .limit(min(20, limit))
                .all()
            )

            result["recent_comments"] = [
                {
                    "content": c.content,
                    "liked_count": c.liked_count,
                    "user": c.user_nickname,
                    "timestamp": c.timestamp,
                }
                for c in recent_comments
            ]

        return result

    except Exception as e:
        return {"status": "error", "message": f"获取歌曲详情失败: {str(e)}"}
    finally:
        session.close()


def list_songs_in_database() -> list:
    """列出数据库中所有歌曲

    Returns:
        [
            {
                "id": "185811",
                "name": "晴天",
                "artists": ["周杰伦"],
                "album": "叶惠美",
                "comment_count": 105342
            },
            ...
        ]
    """
    session = get_session()

    try:
        songs = session.query(Song).all()

        results = []
        for song in songs:
            comment_count = session.query(Comment).filter_by(song_id=song.id).count()

            results.append(
                {
                    "id": song.id,
                    "name": song.name,
                    "artists": [artist.name for artist in song.artists],
                    "album": song.album.name if song.album else None,
                    "comment_count": comment_count,
                    "has_lyric": bool(song.lyric),
                }
            )

        return results

    except Exception as e:
        print(f"[错误] 列出歌曲失败: {e}")
        return []
    finally:
        session.close()
