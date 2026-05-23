"""预留给后续暴力枚举或局部优化求解的每日路线优化边界。"""

from __future__ import annotations


class RouteOptimizerNotImplementedError(NotImplementedError):
    """第一版占位路线优化器被调用时抛出的异常。"""


def optimize_daily_route(*_args, **_kwargs):
    """优化某一天景点访问顺序的占位函数。"""
    raise RouteOptimizerNotImplementedError(
        "每日路线优化将在下一轮规划能力中实现"
    )
