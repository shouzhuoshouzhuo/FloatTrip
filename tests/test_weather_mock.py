r"""雨天 mock 测试（无侵入式）。

用法：
    cd /Users/chj/Desktop/new tripagent
    python -m tests.test_weather_mock

通过 unittest.mock.patch 在运行时替换 fetch_forecast，
不修改任何生产代码。验证天气信息能正确流入规划流水线。
"""
from __future__ import annotations

import sys
from datetime import date, timedelta
from pathlib import Path
from unittest.mock import patch

# 确保能导入 app 模块
sys.path.insert(0, str(Path(__file__).parent.parent))


def _rainy_forecast(city: str, api_key: str) -> list[dict]:
    """Mock：第 2 天为中雨，其余晴天。"""
    today = date.today()
    return [
        {
            "date":          (today + timedelta(i)).isoformat(),
            "day_weather":   "中雨" if i == 1 else "晴",
            "night_weather": "小雨" if i == 1 else "晴",
            "day_temp":      "24"  if i == 1 else "32",
            "night_temp":    "18"  if i == 1 else "22",
            "is_bad":        i == 1,
        }
        for i in range(4)
    ]


def run_test():
    start = (date.today() + timedelta(1)).isoformat()
    end   = (date.today() + timedelta(3)).isoformat()
    query = f"去南京3日游，{start}出发，{end}结束，喜欢历史古迹"

    with patch("app.providers.weather.amap.fetch_forecast", side_effect=_rainy_forecast):
        from app.planning.graph import run
        state = run(query)

    print("=" * 60)
    print("天气预报：")
    for w in state.weather_forecast:
        flag = " ⚠️ 雨天" if w["is_bad"] else ""
        print(f"  {w['date']}: {w['day_weather']}/{w['night_weather']} {w['day_temp']}°C{flag}")

    print("\n天气备注：", state.weather_note or "无")
    print("\n逐天景点安排：")
    if state.final_plan:
        for d in state.final_plan["days"]:
            spots = [s["name"] for s in d["timeline"] if s["type"] == "attraction"]
            print(f"  Day{d['day']} ({d['date']}): {spots}")
    else:
        print("  （规划失败，missing_fields =", state.missing_fields, "）")

    print("\nroute_issues：", state.final_plan.get("route_issues") if state.final_plan else [])
    print("approved：",     state.final_plan.get("approved")     if state.final_plan else None)
    print("=" * 60)

    # 基本断言
    assert len(state.weather_forecast) >= 1, "天气预报应有数据"
    assert state.weather_forecast[0]["is_bad"] is True, "第 1 天应为雨天"
    print("✅ 测试通过")


if __name__ == "__main__":
    run_test()
