"""一次性脚本：跑真实高德景点搜索，把候选池冻结成 fixture 骨架。

天气因真实预报仅 ~4 天，需手工编辑 weather_forecast 构造场景；
每个 POI 的 `indoor` 真值标签也需手工标注（高德无此字段，天气合规打分依赖它）。

用法：
    python -m tests.eval.capture_pool --dest 南京 --days 3 \
        --start 2026-06-10 --pref 历史古迹 --habit "不喜欢早起" \
        --id nanjing-3d-history --tier capability
"""

from __future__ import annotations

import argparse
import json
from datetime import date, timedelta
from pathlib import Path

from app.planning.helpers import amap_key, fetch_city_spots, filter_by_rating

FIXTURES_DIR = Path(__file__).resolve().parent / "fixtures"


def main() -> None:
    ap = argparse.ArgumentParser(description="冻结高德景点池为 fixture 骨架")
    ap.add_argument("--dest", required=True)
    ap.add_argument("--days", type=int, default=3)
    ap.add_argument("--start", type=str, default="2026-06-10", help="开始日期 YYYY-MM-DD")
    ap.add_argument("--pref", type=str, default="")
    ap.add_argument("--habit", type=str, default="")
    ap.add_argument("--food", type=str, default="")
    ap.add_argument("--max-per-day", type=int, default=3)
    ap.add_argument("--min-rating", type=float, default=4.5)
    ap.add_argument("--max-spots", type=int, default=30)
    ap.add_argument("--id", type=str, default=None)
    ap.add_argument("--tier", type=str, default="capability", choices=["regression", "capability"])
    args = ap.parse_args()

    key = amap_key()
    spots = fetch_city_spots(args.dest, key, max_spots=args.max_spots)
    kept, _ = filter_by_rating(spots, args.min_rating)
    print(f"抓取 {len(spots)} 个，rating≥{args.min_rating} 保留 {len(kept)} 个")

    # 给每个 POI 补一个 indoor 占位（需人工把露天景点改成 false）
    for s in kept:
        s.setdefault("indoor", None)

    start = date.fromisoformat(args.start)
    end = start + timedelta(days=args.days - 1)
    # 天气占位：默认全晴，请按场景手工改 is_bad / day_weather
    weather = []
    cur = start
    while cur <= end:
        weather.append({
            "date": cur.isoformat(), "day_weather": "晴", "night_weather": "晴",
            "day_temp": "30", "night_temp": "22", "is_bad": False,
        })
        cur += timedelta(days=1)

    cid = args.id or f"{args.dest}-{args.days}d"
    fixture = {
        "id": cid,
        "tier": args.tier,
        "destination": args.dest,
        "travel_start_date": start.isoformat(),
        "travel_end_date": end.isoformat(),
        "days": args.days,
        "attraction_preference": args.pref or None,
        "habit_preference": args.habit or None,
        "food_preference": args.food or None,
        "max_per_day": args.max_per_day,
        "min_rating": args.min_rating,
        "max_review_rounds": 3,
        "pois": kept,
        "weather_forecast": weather,
        "expectations": {"outdoor_on_bad_day_max": 0},
    }
    FIXTURES_DIR.mkdir(exist_ok=True)
    out = FIXTURES_DIR / f"{cid}.json"
    out.write_text(json.dumps(fixture, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"已写入 {out}")
    print("⚠ 请手工：① 标注每个 POI 的 indoor（露天=false，室内=true）；"
          "② 按场景修改 weather_forecast 的 is_bad/day_weather。")


if __name__ == "__main__":
    main()
