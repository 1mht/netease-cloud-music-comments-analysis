"""
搜索工具模块
封装网易云音乐搜索功能
"""

import sys
import os
import uuid
import json
import time
from typing import Dict, List, Optional
from pathlib import Path

# 添加 netease_cloud_music 到 Python 路径
current_dir = os.path.dirname(os.path.abspath(__file__))
project_root = os.path.dirname(os.path.dirname(current_dir))
netease_path = os.path.join(project_root, "netease_cloud_music")
if netease_path not in sys.path:
    sys.path.insert(0, netease_path)

from get_song_id import search_songs as netease_search_songs

# Session 持久化文件（跨进程共享）
_SESSION_FILE = Path.home() / ".ncm-analysis-sessions.json"
_SESSION_TTL = 3600  # 1小时过期


def _load_sessions() -> Dict:
    if not _SESSION_FILE.exists():
        return {}
    try:
        data = json.loads(_SESSION_FILE.read_text(encoding="utf-8"))
        # 清理过期 session
        now = time.time()
        return {k: v for k, v in data.items() if now - v.get("timestamp", 0) < _SESSION_TTL}
    except Exception:
        return {}


def _save_sessions(sessions: Dict):
    _SESSION_FILE.write_text(json.dumps(sessions, ensure_ascii=False), encoding="utf-8")


def search_songs(keyword: str, limit: int = 10, offset: int = 0):
    """搜索网易云音乐

    Args:
        keyword: 搜索关键词，支持"歌名 歌手"格式
        limit: 返回结果数量，默认10
        offset: 分页偏移量，默认0

    Returns:
        搜索结果列表 (list)，如果没有结果返回空列表 []

    Examples:
        >>> search_songs("晴天 周杰伦", limit=5)
        [
            {
                'id': '185811',
                'name': '晴天',
                'artists': ['周杰伦'],
                'artists_details': [{'id': '6452', 'name': '周杰伦'}],
                'album': '叶惠美',
                'album_id': 18903,
                'album_pic_url': 'https://...',
                'duration_ms': 269000,
                'publish_time': 1059580800000
            },
            ...
        ]
    """
    try:
        results = netease_search_songs(keyword, limit=limit, offset=offset)
        return results if results else []
    except Exception as e:
        print(f"[搜索错误] {e}", file=sys.stderr)
        return []


def format_search_results(results, keyword):
    """格式化搜索结果为MCP返回格式（两步架构：不返回song_id）

    Args:
        results: search_songs() 的返回结果
        keyword: 搜索关键词

    Returns:
        格式化的字典，包含 session_id 和选项列表（不包含 song_id）
    """
    if not results:
        return {
            "status": "no_results",
            "keyword": keyword,
            "count": 0,
            "message": "未找到相关歌曲",
            "suggestion": "可以尝试：1) 简化关键词 2) 只搜歌名 3) 换个写法",
        }

    # 生成唯一 session_id
    session_id = f"search_{uuid.uuid4().hex[:12]}"

    # 保存搜索结果到持久化文件
    sessions = _load_sessions()
    sessions[session_id] = {
        "results": results,
        "keyword": keyword,
        "timestamp": time.time(),
    }
    _save_sessions(sessions)

    # ===== Phase 2: 去中心化决策 - 提供元数据而非判断 =====
    # 不再做"原版/翻唱"判断，提供丰富信息让用户决定

    choices = []
    for i, song in enumerate(results, 1):
        artists = song.get("artists", ["未知"])
        artists_str = ", ".join(artists)
        album = song.get("album", "未知专辑")

        # 获取时长（转换为分:秒格式）
        duration_ms = song.get("duration_ms", 0)
        duration_str = (
            f"{duration_ms // 60000}:{duration_ms % 60000 // 1000:02d}"
            if duration_ms > 0
            else "未知"
        )

        # 新格式：提供充分信息，让用户判断
        # 格式：序号. 歌名 - 艺术家 | 专辑:xxx | 时长:x:xx
        choice_text = (
            f"{i}. {song.get('name')} - {artists_str} | "
            f"专辑:{album} | 时长:{duration_str}"
        )
        choices.append(choice_text)

    return {
        "status": "pending_selection",
        "session_id": session_id,
        "keyword": keyword,
        "count": len(results),
        "choices": choices,
    }


def confirm_song_selection(session_id: str, choice_number: int) -> dict:
    """确认用户选择的歌曲（两步架构第二步）

    Args:
        session_id: 搜索会话ID（由 search_songs_tool 返回）
        choice_number: 用户选择的序号（1-based）

    Returns:
        选中的歌曲信息，包含 song_id
    """
    # 从持久化文件读取 session
    sessions = _load_sessions()
    if session_id not in sessions:
        return {
            "status": "error",
            "message": f"无效的 session_id: {session_id}（已过期或不存在）",
            "suggestion": "请重新调用 ncm-analysis search 进行搜索",
        }

    session = sessions[session_id]
    results = session["results"]

    # 验证选择范围
    if choice_number < 1 or choice_number > len(results):
        return {
            "status": "error",
            "message": f"选择超出范围，有效范围：1-{len(results)}",
            "suggestion": f"请重新选择 1-{len(results)} 之间的数字",
        }

    # 获取选中的歌曲（转为0-based索引）
    selected_song = results[choice_number - 1]

    # 清理已使用的 session
    del sessions[session_id]
    _save_sessions(sessions)

    # v0.6.6: 添加next_step引导AI完成后续workflow
    song_id = selected_song["id"]
    song_name = selected_song["name"]
    artists_str = ", ".join(selected_song.get("artists", ["未知"]))

    return {
        "status": "confirmed",
        "song_id": song_id,
        "song_name": song_name,
        "artists": selected_song.get("artists", ["未知"]),
        "album": selected_song.get("album", "未知专辑"),
    }
