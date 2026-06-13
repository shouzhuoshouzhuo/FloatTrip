"""启动入口。

用法：
    python run.py
    → http://localhost:8765
"""

import logging
import uvicorn

# 配置日志：INFO 级别保留主要流程信息；
# app.planning.helpers 的 WARNING 日志（LLM 重试/耗时）会直接打印到控制台，
# 无需额外配置即可看到结构化输出失败重试情况。
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    datefmt="%H:%M:%S",
)
# 对规划核心模块开启 DEBUG，输出 LLM 调用耗时和 time_check 推理过程
logging.getLogger("app.planning.helpers").setLevel(logging.DEBUG)
logging.getLogger("app.planning.nodes").setLevel(logging.DEBUG)

if __name__ == "__main__":
    print("✈️  旅游规划助手启动中…")
    print("   访问：http://localhost:8765")
    uvicorn.run("app.main:app", host="0.0.0.0", port=8765, reload=False)
