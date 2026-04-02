"""
Workflow错误处理模块

统一管理所有工具的workflow相关错误，确保AI能理解正确的调用顺序。
"""

from typing import Dict, Any


def workflow_error(error_type: str, current_tool: str) -> Dict[str, Any]:
    """
    生成标准化的workflow错误响应

    Args:
        error_type: 错误类型 ('song_not_found', 'no_comments', 'invalid_workflow')
        current_tool: 当前调用的工具名称

    Returns:
        标准化的错误响应字典
    """

    workflows = {
        "song_not_found": {
            "message": "歌曲不存在于数据库",
            "required_workflow": [
                "Step 1: ncm-analysis search <keyword>",
                "Step 2: ncm-analysis select <session_id> <number>",
                "Step 3: ncm-analysis add <song_id>",
                f"Step 4: 重试当前命令",
            ],
            "why": f"{current_tool} 需要歌曲已存在于数据库中",
            "example": "ncm-analysis search 晴天 → select → add → 分析",
            "critical": True,
        },
        "no_comments": {
            "message": "数据库中没有评论数据",
            "required_workflow": [
                "ncm-analysis sample <song_id> --level standard",
                f"然后重试当前命令",
            ],
            "why": f"{current_tool} 需要至少有一些评论数据才能分析",
            "critical": True,
        },
        "invalid_workflow": {
            "message": "工具调用顺序不正确",
            "required_workflow": ["请确保满足所有前置条件后再调用"],
            "why": "某些工具之间存在依赖关系，需要按正确顺序调用",
            "critical": True,
        },
    }

    if error_type not in workflows:
        return {
            "status": "workflow_error",
            "error_type": "unknown",
            "message": f"未知的workflow错误类型: {error_type}",
            "current_tool": current_tool,
        }

    error_info = workflows[error_type]

    return {
        "status": "workflow_error",
        "error_type": error_type,
        "current_tool": current_tool,
        **error_info,
    }
