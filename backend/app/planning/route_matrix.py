"""预留给后续高德公交或驾车通行时间矩阵的边界。"""

from __future__ import annotations


class RouteMatrixNotImplementedError(NotImplementedError):
    """第一版占位路线矩阵被调用时抛出的异常。"""


def build_route_matrix(*_args, **_kwargs):
    """生成景点两两之间通行时间矩阵的占位函数。"""
    raise RouteMatrixNotImplementedError(
        "路线矩阵生成将在下一轮规划能力中实现"
    )
