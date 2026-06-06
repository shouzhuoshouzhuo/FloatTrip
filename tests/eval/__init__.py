"""Planner⇄Reviewer 评估框架。

隔离 planner/reviewer 两个 Agent：冻结高德景点池 + 天气为 fixture，
真实调用 LLM 跑 planner⇄reviewer 循环，用代码打分器 + LLM 评委衡量质量。

运行：
    python -m tests.eval.run_eval --k 5
"""
