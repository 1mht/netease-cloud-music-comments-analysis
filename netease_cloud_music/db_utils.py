import sys
import builtins as _builtins

from sqlalchemy.orm import Session
from database import Song, Artist, Album, Comment


def _safe_print(*args, **kwargs):
    """避免污染 STDIO 协议输出：默认将 print 输出到 stderr。"""
    if "file" not in kwargs:
        kwargs["file"] = sys.stderr
    return _builtins.print(*args, **kwargs)


# 仅影响本模块内的 print() 调用
print = _safe_print


def get_or_create(session, model, defaults=None, **kwargs):
    """
    获取现有记录或创建新记录（通用函数）
    """
    instance = session.query(model).filter_by(**kwargs).first()
    if instance:
        return instance, False
    else:
        params = dict((k, v) for k, v in kwargs.items())
        params.update(defaults or {})
        instance = model(**params)
        session.add(instance)
        return instance, True


def save_song_info(session: Session, song_data: dict):
    """
    保存歌曲的基本信息（包括歌手和专辑）
    :param song_data: 搜索接口返回的歌曲字典
    :return: Song 对象
    """
    # 1. 处理专辑
    album_data = song_data.get("album_obj", {})  # 假设我们预处理过，或者从原始数据提取
    # 如果数据来自 search_songs 的简化结构，我们需要适配一下
    # search_songs 返回: {'id', 'name', 'artists':['name'], 'album', 'album_id', ...}
    # 但为了入库，我们需要更原始的 ID。
    # 这里的逻辑需要根据 search_songs 的实际返回结构来调整。
    # 让我们假设传入的是经过 search_songs 处理后的 clean dict。

    album_id = str(song_data.get("album_id"))
    album_name = song_data.get("album")
    publish_time = song_data.get("publish_time")
    pic_url = song_data.get("album_pic_url")  # 获取图片URL

    album = None
    if album_id and album_name:
        album, created = get_or_create(
            session,
            Album,
            id=album_id,
            defaults={
                "name": album_name,
                "publish_time": publish_time,
                "pic_url": pic_url,  # 保存图片URL
            },
        )
        # 如果专辑已存在但没有图片，且这次有图片，则更新
        if not created and pic_url and not album.pic_url:
            album.pic_url = pic_url
            session.add(album)
            session.commit()

    # 2. 处理歌手
    # 注意：search_songs 目前只返回了歌手名字列表，没有ID。
    # 为了更好的数据库关联，我们需要修改 search_songs 让它返回歌手 ID。
    # 暂时我们先假设传入的数据里有 artist_details 列表 [{'id':..., 'name':...}]
    # 如果没有，我们可能只能创建临时 ID 或通过名字查找（不推荐）。
    # *关键修正*：我需要回头微调 get_song_id.py 让它返回 artist id。

    artist_objs = []
    # 兼容处理：如果只有 artists 名字列表 (当前 get_song_id 的实现)
    # 我们可能无法完美去重，但为了演示，先尝试用名字作为唯一标识（这在生产环境不好，但目前可行）
    # 或者，更好的做法是修改 search_songs 返回完整 artist info。

    if "artists_details" in song_data:
        for art in song_data["artists_details"]:
            artist_instance, _ = get_or_create(
                session, Artist, id=str(art["id"]), defaults={"name": art["name"]}
            )
            artist_objs.append(artist_instance)

    # 3. 保存歌曲
    song_id = str(song_data["id"])
    song, created = get_or_create(
        session,
        Song,
        id=song_id,
        defaults={
            "name": song_data["name"],
            "duration_ms": song_data.get("duration_ms"),
            "album": album,
        },
    )

    # 更新关联
    if created or not song.artists:
        song.artists = artist_objs

    session.commit()
    return song


def save_comments(
    session: Session, song_id: str, comments_list: list, detect_deletions: bool = False
):
    """
    批量保存评论 (支持更新点赞数和删除检测)

    Args:
        session: 数据库会话
        song_id: 歌曲ID
        comments_list: 评论列表
        detect_deletions: 是否检测删除(默认False)
            - True: 将数据库中有但API中没有的评论标记为删除
            - False: 仅添加/更新,不检测删除
    """
    import time

    song = session.query(Song).filter_by(id=song_id).first()
    if not song:
        print(f"警告: 尝试给不存在的歌曲(ID:{song_id})添加评论")
        return

    current_timestamp = int(time.time() * 1000)  # 当前时间戳(ms)
    seen_comment_ids = set()

    # 保存/更新评论
    for c_data in comments_list:
        comment_id = str(c_data["commentId"])
        seen_comment_ids.add(comment_id)

        # 检查是否存在
        exists = session.query(Comment).filter_by(comment_id=comment_id).first()

        if exists:
            # 如果存在,更新动态数据
            exists.liked_count = c_data["likedCount"]
            exists.last_seen_at = current_timestamp

            # 如果之前被标记为删除,现在恢复
            if exists.is_deleted:
                exists.is_deleted = False
                exists.deleted_at = None
                print(f"[恢复] 评论 {comment_id[:8]}... 已恢复(之前被标记删除)")
        else:
            # 如果不存在,创建新记录
            new_comment = Comment(
                comment_id=comment_id,
                content=c_data["content"],
                liked_count=c_data["likedCount"],
                time_str=c_data.get("timeStr"),
                timestamp=c_data.get("time"),
                user_nickname=c_data["user"]["nickname"],
                user_avatar=c_data["user"]["avatarUrl"],
                song=song,
                is_deleted=False,
                last_seen_at=current_timestamp,
            )
            session.add(new_comment)

    # 删除检测
    if detect_deletions:
        all_db_comments = (
            session.query(Comment)
            .filter_by(
                song_id=song_id,
                is_deleted=False,  # 只检查未删除的评论
            )
            .all()
        )

        deleted_count = 0
        for db_comment in all_db_comments:
            if db_comment.comment_id not in seen_comment_ids:
                # 在API中已不存在 -> 软删除
                db_comment.is_deleted = True
                db_comment.deleted_at = current_timestamp
                deleted_count += 1
                print(f"[删除检测] 评论 {db_comment.comment_id[:8]}... 已被平台删除")

        if deleted_count > 0:
            print(f"[删除检测] 共检测到 {deleted_count} 条被删除的评论")

    session.commit()


def update_lyric(session: Session, song_id: str, lyric_text: str):
    """
    更新歌词
    """
    song = session.query(Song).filter_by(id=song_id).first()
    if song:
        song.lyric = lyric_text
        session.commit()
