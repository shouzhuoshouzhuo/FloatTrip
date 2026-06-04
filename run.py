"""启动入口。

用法：
    python run.py
    → http://localhost:8765
"""

import uvicorn

if __name__ == "__main__":
    print("✈️  旅游规划助手启动中…")
    print("   访问：http://localhost:8765")
    uvicorn.run("app.main:app", host="0.0.0.0", port=8765, reload=False)
