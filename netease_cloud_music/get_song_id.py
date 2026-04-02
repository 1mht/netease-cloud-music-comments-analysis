import sys
import builtins as _builtins

import requests
import json
import re
import os


def _safe_print(*args, **kwargs):
    """默认将 print 输出到 stderr，避免污染 MCP STDIO。"""
    if "file" not in kwargs:
        kwargs["file"] = sys.stderr
    return _builtins.print(*args, **kwargs)


# 仅影响本模块内的 print() 调用
print = _safe_print


try:
    from .utils import create_weapi_params
except (ImportError, ValueError):
    from utils import create_weapi_params


def _load_cookie():
    """从 cookie.txt 加载 Cookie"""
    try:
        cookie_path = os.path.join(os.path.dirname(__file__), "cookie.txt")
        if os.path.exists(cookie_path):
            with open(cookie_path, "r", encoding="utf-8") as f:
                content = f.read().strip()
                if content and not content.startswith("#"):
                    return content
    except Exception as e:
        print(f"读取 Cookie 失败: {e}")
    return None


def get_song_detail_by_id(song_id):
    """通过 song_id 获取歌曲详细信息（用于直接入库）"""
    if not song_id:
        return None

    song_id = str(song_id)
    url = "http://music.163.com/api/song/detail/"
    params = {"id": song_id, "ids": f"[{song_id}]"}
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    }
    cookie = _load_cookie()
    if cookie:
        headers["Cookie"] = cookie

    try:
        response = requests.get(url, params=params, headers=headers)
        data = response.json()
        if data.get("code") != 200 or "songs" not in data or not data["songs"]:
            return None

        item = data["songs"][0]
        artists_details = [
            {"id": str(a.get("id")), "name": a.get("name")}
            for a in item.get("artists", [])
        ]
        artists_names = [a["name"] for a in artists_details]
        return {
            "id": str(item.get("id")),
            "name": item.get("name"),
            "artists": artists_names,
            "artists_details": artists_details,
            "album": item.get("album", {}).get("name"),
            "album_id": item.get("album", {}).get("id"),
            "album_pic_url": item.get("album", {}).get("picUrl"),
            "duration_ms": item.get("duration"),
            "publish_time": item.get("album", {}).get("publishTime"),
        }
    except Exception as e:
        print(f"获取歌曲详情失败: {e}")
        return None


def _preprocess_query(query):
    """
    智能预处理用户查询，将自然语言转换为搜索引擎更友好的关键词组合
    例如: "dirty artists have EsDeeKid" -> "dirty EsDeeKid"
    """
    # 模式 1: "SongName artists have ArtistName"
    # 模式 2: "SongName by ArtistName"
    # 模式 3: "SongName - ArtistName"

    # 移除常见的连接词，替换为空格
    patterns = [
        r"\s+artists?\s+have\s+",  # artists have
        r"\s+artist\s+",  # artist
        r"\s+by\s+",  # by
        r"\s*-\s*",  # -
    ]

    processed_query = query
    for pattern in patterns:
        processed_query = re.sub(pattern, " ", processed_query, flags=re.IGNORECASE)

    # 去除多余空格
    processed_query = re.sub(r"\s+", " ", processed_query).strip()

    if processed_query != query:
        print(f"检测到自然语言输入，已优化搜索关键词: '{query}' -> '{processed_query}'")

    return processed_query


def search_songs(keyword, limit=10, offset=0):
    """
    搜索歌曲并返回详细信息列表
    :param keyword: 搜索关键词
    :param limit: 返回数量限制
    :param offset: 分页偏移量
    """
    # 预处理查询
    optimized_keyword = _preprocess_query(keyword)

    # 使用较简单的搜索接口，兼容性更好
    url = "http://music.163.com/api/search/get"

    params = {"s": optimized_keyword, "type": 1, "limit": limit, "offset": offset}

    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    }

    try:
        response = requests.get(url, params=params, headers=headers)
        data = response.json()

        if (
            data.get("code") != 200
            or "result" not in data
            or "songs" not in data["result"]
        ):
            # 尝试返回空列表而不是报错
            return []

        # --- 增强逻辑：使用 song/detail 接口批量获取详情（包含封面图） ---
        search_songs_list = data["result"]["songs"]
        try:
            song_ids = [str(s["id"]) for s in search_songs_list]
            if song_ids:
                # 构造 ids 参数: ids=[1,2,3]
                ids_param = f"[{','.join(song_ids)}]"
                detail_url = "http://music.163.com/api/song/detail/"
                detail_params = {
                    "id": song_ids[0],
                    "ids": ids_param,
                }  # id 参数随便传一个，ids 才是关键

                detail_resp = requests.get(
                    detail_url, params=detail_params, headers=headers
                )
                detail_data = detail_resp.json()

                if detail_data.get("code") == 200 and "songs" in detail_data:
                    # 使用详情接口的数据替换搜索结果，因为详情接口更全
                    # 为了保持顺序，我们需要建立一个 id -> song 的映射
                    detail_map = {str(s["id"]): s for s in detail_data["songs"]}

                    # 重新构建 search_songs_list，优先使用 detail 数据
                    enhanced_list = []
                    for original_song in search_songs_list:
                        sid = str(original_song["id"])
                        if sid in detail_map:
                            enhanced_list.append(detail_map[sid])
                        else:
                            enhanced_list.append(original_song)
                    search_songs_list = enhanced_list
        except Exception as e:
            print(f"获取歌曲详情失败，降级使用搜索结果: {e}")

        # --- 结束增强逻辑 ---

        songs = []
        for item in search_songs_list:
            # 提取元数据
            # 这里的字段名与 weapi 略有不同

            # 提取详细的歌手信息
            artists_details = [
                {"id": str(a.get("id")), "name": a.get("name")}
                for a in item.get("artists", [])
            ]
            artists_names = [a["name"] for a in artists_details]

            song_info = {
                "id": str(item.get("id")),
                "name": item.get("name"),
                "artists": artists_names,  # 保持列表兼容显示
                "artists_details": artists_details,  # 新增详细信息用于数据库
                "album": item.get("album", {}).get("name"),
                "album_id": item.get("album", {}).get("id"),
                "album_pic_url": item.get("album", {}).get(
                    "picUrl"
                ),  # 详情接口里肯定有这个
                "duration_ms": item.get("duration"),
                "publish_time": item.get("album", {}).get("publishTime"),
            }
            songs.append(song_info)
        return songs
    except Exception as e:
        print(f"搜索出错: {e}")
        return []


def interactive_select_song(initial_keyword):
    """
    交互式搜索并选择歌曲，支持翻页和重新搜索
    """
    keyword = initial_keyword
    page = 1
    page_size = 10

    while True:
        offset = (page - 1) * page_size
        print(f"\n正在搜索: '{keyword}' (第 {page} 页)...")
        songs = search_songs(keyword, limit=page_size, offset=offset)

        if not songs and page == 1:
            print("未找到相关歌曲。")
            # 给用户重新搜索的机会
            command = input("\n输入 's 新关键词' 重新搜索，或 'q' 退出: ").strip()
            if command.lower() == "q":
                return None
            elif command.lower().startswith("s "):
                keyword = command[2:].strip()
                page = 1
                continue
            else:
                return None

        if not songs:
            print("没有更多结果了。")
            page -= 1  # 回到上一页
            if page < 1:
                page = 1
            continue

        print(f"\n找到以下歌曲 (第 {page} 页):")
        print(f"{'序号':<4} | {'歌曲名称':<25} | {'歌手':<20} | {'专辑':<20}")
        print("-" * 80)

        for i, song in enumerate(songs):
            # 全局序号: (页码-1)*页大小 + 当前索引 + 1
            global_idx = (page - 1) * page_size + i + 1

            artists_str = ", ".join(song["artists"])
            name = (
                (song["name"][:22] + "..") if len(song["name"]) > 24 else song["name"]
            )
            artists = (
                (artists_str[:18] + "..") if len(artists_str) > 18 else artists_str
            )
            album = (
                (song["album"][:18] + "..")
                if song["album"] and len(song["album"]) > 18
                else (song["album"] or "未知")
            )

            print(f"{global_idx:<4} | {name:<25} | {artists:<20} | {album:<20}")

        print("\n操作指南:")
        print("  [数字] 选择歌曲")
        print("  [n]    下一页")
        print("  [p]    上一页")
        print("  [s 词] 搜新词 (如: s 偏偏喜欢你)")
        print("  [q]    退出")

        choice = input("请输入指令: ").strip()

        if choice.lower() == "q":
            return None
        elif choice.lower() == "n":
            page += 1
        elif choice.lower() == "p":
            if page > 1:
                page -= 1
            else:
                print("已经是第一页了。")
        elif choice.lower().startswith("s "):
            new_query = choice[2:].strip()
            if new_query:
                keyword = new_query
                page = 1
            else:
                print("请输入要搜索的关键词。")
        elif choice.isdigit():
            idx = int(choice)
            # 计算当前页内的相对索引
            start_idx = (page - 1) * page_size + 1
            end_idx = start_idx + len(songs) - 1

            if start_idx <= idx <= end_idx:
                relative_idx = idx - start_idx
                return songs[relative_idx]
            else:
                print(f"请输入当前列表范围内的数字 ({start_idx}-{end_idx})。")
        else:
            print("无效指令，请重试。")


def search_song_id(song_name):
    """
    保持原有的接口兼容性，但内部逻辑升级
    """
    songs = search_songs(song_name, limit=1)
    if songs:
        return songs[0]["id"]
    return None


if __name__ == "__main__":
    import sys

    # 如果通过命令行传入参数
    query = " ".join(sys.argv[1:]) if len(sys.argv) > 1 else "偏偏喜欢你"
    selected = interactive_select_song(query)
    if selected:
        print(f"\n您选择了: {selected['name']} (ID: {selected['id']})")
        print(f"完整元数据: {json.dumps(selected, indent=2, ensure_ascii=False)}")
