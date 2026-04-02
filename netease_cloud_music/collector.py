import sys
import builtins as _builtins

import time
import random
import requests
from utils import create_weapi_params
from db_utils import save_comments
from database import init_db
import os


def _safe_print(*args, **kwargs):
    """避免污染 STDIO 协议输出：默认将 print 输出到 stderr。"""
    if "file" not in kwargs:
        kwargs["file"] = sys.stderr
    return _builtins.print(*args, **kwargs)


# 仅影响本模块内的 print() 调用
print = _safe_print


# ============================================================
# 配置 & 熔断机制 (Circuit Breaker) - Andrej Philosophy
# ============================================================
PAGE_SIZE = 20
MAX_PAGES = 20000  # 最大页数限制 (20000页 * 20条 = 40万评论)
SLEEP_MIN = 0.5
SLEEP_MAX = 1.5

# 熔断配置
MAX_CONSECUTIVE_ERRORS = 5  # 连续错误N次后熔断
MAX_RUNTIME_SECONDS = 7200  # 最大运行时间2小时 (防止无限循环)
CHECKPOINT_INTERVAL = 100  # 每100页输出一次检查点


def load_cookie():
    """从 cookie.txt 加载 Cookie"""
    try:
        cookie_path = os.path.join(os.path.dirname(__file__), "cookie.txt")
        if os.path.exists(cookie_path):
            with open(cookie_path, "r", encoding="utf-8") as f:
                content = f.read().strip()
                # 忽略注释行
                if content and not content.startswith("#"):
                    return content
    except Exception as e:
        print(f"[警告] 读取 Cookie 失败: {e}")
    return None


def crawl_all_comments_task(song_id: str, db_path: str, detect_deletions: bool = False):
    """
    后台任务：爬取指定歌曲的全部评论（使用更稳健的 V1 GET 接口）

    Args:
        song_id: 歌曲ID
        db_path: 数据库路径(SQLAlchemy URL格式)
        detect_deletions: 是否检测删除(默认False)
            - True: 爬取完成后检测并标记删除的评论(保留数据用于研究)
            - False: 仅添加/更新评论
    """
    print(f"\n[后台任务] 开始全量抓取歌曲 {song_id} 的评论...")
    if detect_deletions:
        print("[删除检测] 已启用 - 将检测并保留被平台删除的评论")

    user_cookie = load_cookie()
    session = init_db(db_path)

    page = 1
    total_comments = 0
    all_seen_comments = []  # 用于删除检测

    # ===== 熔断机制变量 =====
    start_time = time.time()
    consecutive_errors = 0

    try:
        while page <= MAX_PAGES:
            # ===== 熔断检查1: 运行时间 =====
            elapsed_seconds = time.time() - start_time
            if elapsed_seconds > MAX_RUNTIME_SECONDS:
                print(
                    f"\n[熔断] 已运行 {elapsed_seconds / 60:.1f} 分钟，超过最大时间限制 {MAX_RUNTIME_SECONDS / 60:.0f} 分钟"
                )
                print(f"[熔断] 已保存 {total_comments} 条评论，任务中断")
                break

            # ===== 检查点输出 =====
            if page % CHECKPOINT_INTERVAL == 0:
                print(
                    f"\n[检查点] 第 {page} 页 | 已爬取 {total_comments} 条 | 运行 {elapsed_seconds / 60:.1f} 分钟"
                )
            limit = PAGE_SIZE
            offset = (page - 1) * limit

            # 使用 V1 GET 接口
            url = f"http://music.163.com/api/v1/resource/comments/R_SO_4_{song_id}?limit={limit}&offset={offset}"

            headers = {
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
            }
            if user_cookie:
                headers["Cookie"] = user_cookie

            # 发送请求
            try:
                resp = requests.get(url, headers=headers, timeout=10)
                res_data = resp.json()

                if res_data.get("code") != 200:
                    print(f"[错误] API 返回非 200: {res_data.get('code')}")
                    break

                # V1 接口的结构稍有不同，直接在根部
                comments = res_data.get("comments", [])

                if not comments:
                    print(f"[任务结束] 第 {page} 页无更多评论。")
                    break

                # 收集所有评论用于删除检测
                if detect_deletions:
                    all_seen_comments.extend(comments)

                # 入库 (非最后一页不检测删除)
                save_comments(session, song_id, comments, detect_deletions=False)
                count = len(comments)
                total_comments += count

                # ===== 成功时重置连续错误计数 =====
                consecutive_errors = 0

                print(
                    f"[进度] song_id:{song_id} -- 第 {page} 页抓取完成，本页 {count} 条，累计 {total_comments} 条。"
                )

                # 检查是否还有更多
                has_more = res_data.get("more", False)
                if not has_more:
                    print("[任务结束] 已到达最后一页。")
                    break

            except Exception as e:
                consecutive_errors += 1
                print(
                    f"[异常] 请求第 {page} 页失败 ({consecutive_errors}/{MAX_CONSECUTIVE_ERRORS}): {e}"
                )

                # ===== 熔断检查2: 连续错误 =====
                if consecutive_errors >= MAX_CONSECUTIVE_ERRORS:
                    print(f"\n[熔断] 连续 {consecutive_errors} 次请求失败，任务中断")
                    print(f"[熔断] 已保存 {total_comments} 条评论")
                    break

                # 等待后重试
                time.sleep(5)
                continue  # 重试当前页，不跳过

            # 翻页
            page += 1

            # 翻页休眠
            sleep_time = random.uniform(SLEEP_MIN + 0.5, SLEEP_MAX + 1.0)
            time.sleep(sleep_time)

        # 爬取完成后,统一检测删除
        if detect_deletions and all_seen_comments:
            print(f"\n[删除检测] 开始检测删除的评论...")
            save_comments(session, song_id, all_seen_comments, detect_deletions=True)

    except Exception as e:
        print(f"[致命错误] 爬虫任务崩溃: {e}")
    finally:
        session.close()
        print(f"[后台任务] 歌曲 {song_id} 抓取结束。总计入库: {total_comments} 条。")


if __name__ == "__main__":
    # 测试代码
    # 注意：需要确保数据库文件路径正确
    db_file = os.path.join(os.path.dirname(__file__), "../data/music_data_v2.db")
    db_uri = f"sqlite:///{db_file}"
    crawl_all_comments_task("1481047138", db_uri)
