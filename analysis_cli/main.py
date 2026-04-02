#!/usr/bin/env python3
"""
NetEase Music Analysis CLI
直接调用 netease_analysis/tools/ 模块，输出 JSON 供 Claude 解析。

用法:
    ncm-analysis search "晴天"
    ncm-analysis select <session_id> 1
    ncm-analysis add <song_id>
    ncm-analysis sample <song_id> [--level quick|standard|deep]
    ncm-analysis overview <song_id>
    ncm-analysis signals <song_id>
    ncm-analysis samples <song_id>
    ncm-analysis search-comments <song_id> <keyword> [--limit N] [--min-likes N]
    ncm-analysis raw <song_id> [--year N] [--min-likes N] [--limit N]
"""

import sys
import json
import os
import warnings
from pathlib import Path

# 压制第三方库的 UserWarning（如 jieba 的 pkg_resources 弃用警告），保持 stdout 干净
warnings.filterwarnings("ignore", category=UserWarning)
warnings.filterwarnings("ignore", category=DeprecationWarning)

import click

# 将项目根目录加入 sys.path，确保 netease_analysis 包可导入
_project_root = str(Path(__file__).parent.parent)
if _project_root not in sys.path:
    sys.path.insert(0, _project_root)

# 压制 jieba/snownlp 的初始化日志，保持 stdout 干净
import logging
logging.getLogger("jieba").setLevel(logging.ERROR)
logging.getLogger("snownlp").setLevel(logging.ERROR)
logging.getLogger("netease_analysis").setLevel(logging.ERROR)
logging.getLogger("netease_cloud_music").setLevel(logging.ERROR)


def _out(data: dict):
    """输出 JSON 到 stdout。"""
    click.echo(json.dumps(data, ensure_ascii=False, indent=2))


def _err(msg: str, **kwargs):
    """输出错误 JSON 到 stdout（保持格式一致，Claude 可解析）。"""
    _out({"status": "error", "message": msg, **kwargs})


@click.group()
@click.version_option(package_name="netease-music-analysis", prog_name="analysis")
def cli():
    """网易云音乐评论分析 CLI。输出均为 JSON 格式。"""
    pass


# ============================================================
# 工具 1: 搜索歌曲
# ============================================================

@cli.command()
@click.argument("keyword")
@click.option("--limit", default=10, type=int, help="返回结果数量 (1-30)")
@click.option("--offset", default=0, type=int, help="分页偏移，取下一页时用 10、20...")
def search(keyword, limit, offset):
    """搜索网易云音乐歌曲，返回候选列表和 session_id。"""
    try:
        from netease_analysis.tools.search import search_songs, format_search_results
        results = search_songs(keyword, limit=limit, offset=offset)
        _out(format_search_results(results, keyword))
    except Exception as e:
        _err(str(e))


# ============================================================
# 工具 2: 确认选择
# ============================================================

@cli.command()
@click.argument("session_id")
@click.argument("choice_number", type=int)
def select(session_id, choice_number):
    """确认歌曲选择，返回 song_id。"""
    try:
        from netease_analysis.tools.search import confirm_song_selection
        _out(confirm_song_selection(session_id, choice_number))
    except Exception as e:
        _err(str(e))


# ============================================================
# 工具 3: 入库
# ============================================================

@cli.command()
@click.argument("song_id")
def add(song_id):
    """将歌曲入库（元数据 + 热评 + 最新评论）。"""
    try:
        from netease_analysis.tools.data_collection import add_song_basic
        _out(add_song_basic(None, song_id=str(song_id)))
    except Exception as e:
        _err(str(e))


# ============================================================
# 工具 4: 采样
# ============================================================

@cli.command()
@click.argument("song_id")
@click.option(
    "--level",
    default="standard",
    type=click.Choice(["quick", "standard", "deep"]),
    help="采样级别: quick=200条 / standard=600条(推荐) / deep=1000条",
)
def sample(song_id, level):
    """采样评论（三级：quick/standard/deep）。"""
    try:
        from netease_analysis.tools.sampling import sample_comments
        from netease_analysis.tools.pagination_sampling import get_real_comments_count_from_api

        api_result = get_real_comments_count_from_api(song_id)
        api_total = api_result.get("total_comments", 0) if api_result else 0

        if api_total == 0:
            _err("无法获取 API 评论总数", song_id=song_id)
            return

        _out(sample_comments(song_id=song_id, api_total=api_total, level=level, save_to_db=True))
    except Exception as e:
        _err(str(e), song_id=song_id)


# ============================================================
# 工具 5: Layer 0 数据概览
# ============================================================

@cli.command()
@click.argument("song_id")
def overview(song_id):
    """【Layer 0】数据概览：评论量、覆盖率、时间跨度。"""
    try:
        from netease_analysis.tools.layered_analysis import get_analysis_overview
        _out(get_analysis_overview(song_id))
    except Exception as e:
        _err(str(e), song_id=song_id)


# ============================================================
# 工具 6: Layer 1 六维度信号
# ============================================================

@cli.command()
@click.argument("song_id")
def signals(song_id):
    """【Layer 1】六维度量化信号（情感/内容/时间/结构/社交/语言）。"""
    try:
        from netease_analysis.tools.layered_analysis import get_analysis_signals
        _out(get_analysis_signals(song_id))
    except Exception as e:
        _err(str(e), song_id=song_id)


# ============================================================
# 工具 7: Layer 2 验证样本
# ============================================================

@cli.command()
@click.argument("song_id")
def samples(song_id):
    """【Layer 2】验证样本（锚点样本 + 对比样本）。"""
    try:
        from netease_analysis.tools.layered_analysis import get_analysis_samples
        _out(get_analysis_samples(song_id))
    except Exception as e:
        _err(str(e), song_id=song_id)


# ============================================================
# 工具 8: Layer 2.5 关键词检索
# ============================================================

@cli.command("search-comments")
@click.argument("song_id")
@click.argument("keyword")
@click.option("--limit", default=20, type=int)
@click.option("--min-likes", default=0, type=int)
def search_comments(song_id, keyword, limit, min_likes):
    """【Layer 2.5】DB 内关键词检索，验证关键词真实性。"""
    try:
        from netease_analysis.tools.layered_analysis import search_comments_by_keyword
        _out(search_comments_by_keyword(song_id, keyword=keyword, limit=limit, min_likes=min_likes))
    except Exception as e:
        _err(str(e), song_id=song_id)


# ============================================================
# 工具 9: Layer 3 原始评论
# ============================================================

@cli.command()
@click.argument("song_id")
@click.option("--year", default=None, type=int, help="筛选年份")
@click.option("--min-likes", default=0, type=int)
@click.option("--limit", default=20, type=int)
def raw(song_id, year, min_likes, limit):
    """【Layer 3】原始评论，按年份/点赞数筛选。"""
    try:
        from netease_analysis.tools.layered_analysis import get_raw_comments
        _out(get_raw_comments(song_id, year=year, min_likes=min_likes, limit=limit))
    except Exception as e:
        _err(str(e), song_id=song_id)


if __name__ == "__main__":
    cli()
