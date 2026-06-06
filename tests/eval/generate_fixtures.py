"""一次性 fixture 生成脚本：真实调高德 API 获取景点池，生成 30 个评估用例。

天气场景 / indoor 标注 / 负样本筛选由脚本决定（见各处注释说明理由）。

运行：
    python -m tests.eval.generate_fixtures
"""

from __future__ import annotations

import json
import re
import sys
from datetime import date, timedelta
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent.parent.parent
FIXTURES_DIR = Path(__file__).resolve().parent / "fixtures"
sys.path.insert(0, str(ROOT))

from app.core.env import load_local_env
from app.planning.helpers import amap_key, fetch_city_spots, filter_by_rating

load_local_env()


# ── Indoor 标注 ──────────────────────────────────────────────────
# 基于景点名称关键词判定：匹配任意关键词 → indoor=True，否则 False（露天）。
# "博物" 覆盖"博物馆""博物院"等所有变体；"地下"覆盖地下洞穴类；
# 剩余公园/山岳/古镇/海滩等一律视为露天。
INDOOR_KW = [
    "博物", "纪念馆", "展览馆", "美术馆", "科技馆", "图书馆",
    "水族馆", "影院", "剧院", "文化馆", "体验馆", "陈列馆",
    "展示馆", "总统府", "演艺厅", "音乐厅", "地下",
    # 演艺类室内场馆（如"千古情"系列实景演出，均为室内剧场）
    "千古情", "剧场", "大剧院", "演艺",
]


def label_indoor(name: str) -> bool:
    return any(kw in name for kw in INDOOR_KW)


# ── 开放时长解析（用于 tight_hours 筛选）───────────────────────
_TIME_RE = re.compile(r"(\d{1,2})[:：](\d{2})\s*[-~—至]\s*(\d{1,2})[:：](\d{2})")


def open_duration_hours(open_time: str) -> float | None:
    m = _TIME_RE.search(open_time or "")
    if not m:
        return None
    start = int(m.group(1)) * 60 + int(m.group(2))
    end = int(m.group(3)) * 60 + int(m.group(4))
    # 避免"00:00-24:00"全天开放被误判为0小时（差值=0或负时视为24h）
    diff = end - start
    if diff <= 0:
        diff += 24 * 60
    return diff / 60


# ── 天气构造 ──────────────────────────────────────────────────────
# 所有天气数据均为手工构造：真实高德天气预报仅约 4 天且随时间变化、无法复现，
# 不适合锁定进 fixture；因此天气是人工决策维度。
def make_weather(start_str: str, days: int, scenario: str,
                 day_temp: str = "28", night_temp: str = "20") -> list[dict]:
    """
    scenario:
      sunny      — 全程晴
      single_rain — 第 2 天中雨（1天行程不适用，直接退化为sunny）
      all_rain   — 全程中雨
      beyond     — 返回空列表（超出预报范围场景）
    """
    if scenario == "beyond":
        return []
    start = date.fromisoformat(start_str)
    result = []
    for i in range(days):
        d = (start + timedelta(days=i)).isoformat()
        dt, nt = day_temp, night_temp
        if scenario == "sunny":
            entry = dict(date=d, day_weather="晴", night_weather="晴",
                         day_temp=dt, night_temp=nt, is_bad=False)
        elif scenario == "single_rain":
            if i == 1:  # 第2天（索引1）为雨天，1天行程仅1天故退化为晴
                entry = dict(date=d, day_weather="中雨", night_weather="小雨",
                             day_temp=str(int(dt) - 6), night_temp=str(int(nt) - 3),
                             is_bad=True)
            else:
                entry = dict(date=d, day_weather="晴", night_weather="晴",
                             day_temp=dt, night_temp=nt, is_bad=False)
        elif scenario == "all_rain":
            entry = dict(date=d, day_weather="中雨", night_weather="小雨",
                         day_temp=str(int(dt) - 8), night_temp=str(int(nt) - 4),
                         is_bad=True)
        else:
            raise ValueError(f"Unknown weather scenario: {scenario}")
        result.append(entry)
    return result


# ── POI 筛选模式 ────────────────────────────────────────────────
def apply_pool_mode(pois: list[dict], mode: str) -> list[dict]:
    """
    full        — 保留全部评分达标景点
    top_N       — 只取评分最高的 N 个（负样本：小景点池）
    outdoor_only — 只保留露天景点（负样本：雨天+全露天）
    tight_hours  — 优先保留开放时长 ≤ 9h 的景点（负样本：开放时间偏紧）
                   南京实测：约 8 个 POI 符合，足够构成困难但非不可能的调度
    """
    if mode == "full":
        return pois
    if mode.startswith("top_"):
        n = int(mode.split("_")[1])
        return sorted(pois, key=lambda p: p.get("rating", 0), reverse=True)[:n]
    if mode == "outdoor_only":
        out = [p for p in pois if not p["indoor"]]
        return out if len(out) >= 3 else pois   # 防止过滤后太少
    if mode == "tight_hours":
        # 开放时长 ≤ 9h 的景点：这些景点通常 08:30/09:00 开、17:00/17:30 关，
        # 窗口紧，planner 稍不注意就会违反 G2（开放时间冲突）
        tight = [p for p in pois
                 if (h := open_duration_hours(p.get("open_time", ""))) is not None
                 and h <= 9.0]
        # 不够则补一些普通 POI（仍保证负样本有至少 2/3 是短窗口）
        if len(tight) < 4:
            extra = [p for p in pois if p not in tight]
            tight = tight + extra[:4 - len(tight)]
        return tight
    return pois


# ── 30 个 Fixture 规格 ─────────────────────────────────────────
# 覆盖矩阵：目的地（南京/上海/丽江/三亚/景德镇）× 天数（1/3/5）×
#           天气（晴/单日雨/全雨/超范围）× 偏好（历史/自然/夜景/慢节奏）×
#           负样本（小景点池/全露天雨天/开放时间偏紧）
SPECS: list[dict[str, Any]] = [

    # ════════════════════ 南京（8例）════════════════════
    dict(id="nanjing-3d-sunny-history",
         tier="regression", destination="南京", days=3, start="2026-08-01",
         pref="历史古迹、博物馆", habit="不喜欢早起，慢节奏，每天景点别太多",
         weather="sunny", pool="full", day_temp="31", night_temp="23",
         span_km=18, outdoor_max=0,
         query="南京3天历史古迹游，喜欢博物馆，不喜欢早起"),

    dict(id="nanjing-3d-singlerain-history",
         tier="capability", destination="南京", days=3, start="2026-08-10",
         pref="历史古迹、博物馆", habit="正常作息",
         weather="single_rain", pool="full", day_temp="31", night_temp="23",
         span_km=18, outdoor_max=0,
         query="南京3天历史游，第2天有雨，雨天尽量安排室内博物馆"),

    # 负样本：全程雨 + 候选池只含露天景点
    # 考验 planner 面对"无合适室内景点可选"时的权衡，以及 reviewer 是否误放行
    dict(id="nanjing-2d-allrain-outdoor-negative",
         tier="capability", destination="南京", days=2, start="2026-08-20",
         pref="自然风光、户外", habit="正常作息",
         weather="all_rain", pool="outdoor_only", day_temp="25", night_temp="19",
         span_km=20, outdoor_max=1,  # 雨天露天上限放宽到1（别无选择时的现实妥协）
         query="南京2天户外自然游，全程大雨（负样本：景点池全是露天，考验天气权衡）"),

    dict(id="nanjing-1d-sunny-nightlife",
         tier="capability", destination="南京", days=1, start="2026-08-05",
         pref="夜景、夜市、城市光影", habit="喜欢夜间游览，下午才出发",
         weather="sunny", pool="full", day_temp="32", night_temp="25",
         span_km=15, outdoor_max=0,
         query="南京1天夜景游，下午出发，重点体验夜间景点"),

    dict(id="nanjing-5d-sunny-slowpace",
         tier="regression", destination="南京", days=5, start="2026-08-15",
         pref="历史古迹、博物馆、园林", habit="慢节奏，不喜欢早起，睡到自然醒",
         weather="sunny", pool="full", day_temp="31", night_temp="23",
         span_km=18, outdoor_max=0,
         query="南京5天慢节奏深度游，历史古迹为主，每天不要排太满"),

    # 超预报范围：weather_forecast 为空，考验 planner 是否能按晴天策略合理规划
    dict(id="nanjing-3d-beyond-forecast",
         tier="capability", destination="南京", days=3, start="2026-11-01",
         pref="历史古迹", habit="正常作息",
         weather="beyond", pool="full", day_temp="16", night_temp="9",
         span_km=18, outdoor_max=0,
         query="南京3天游，出行日期超出天气预报范围"),

    # 负样本：开放时间偏紧（pool 优先选 ≤9h 短窗口景点）
    # 典型短窗口：红山动物园08:30-16:30、南京平山森林公园09:00-16:30等
    # planner 容易安排超出窗口（尤其是慢节奏习惯+短窗口的冲突）
    dict(id="nanjing-3d-tighthours-negative",
         tier="capability", destination="南京", days=3, start="2026-08-25",
         pref="历史古迹、自然景观", habit="不喜欢早起",  # 晚起+短窗口→G2压力大
         weather="sunny", pool="tight_hours", day_temp="31", night_temp="23",
         span_km=18, outdoor_max=0,
         query="南京3天游（负样本：景点池以开放时间短的景点为主，考验时刻表合理性）"),

    dict(id="nanjing-5d-allrain-history",
         tier="capability", destination="南京", days=5, start="2026-07-20",
         pref="历史古迹、博物馆", habit="不喜欢早起",
         weather="all_rain", pool="full", day_temp="26", night_temp="20",
         span_km=18, outdoor_max=0,
         query="南京5天全程雨，历史古迹游，尽量室内"),

    # ════════════════════ 上海（7例）════════════════════
    dict(id="shanghai-1d-sunny-nightlife",
         tier="capability", destination="上海", days=1, start="2026-08-06",
         pref="夜景、外滩、都市光影", habit="下午出发，喜欢夜间游览",
         weather="sunny", pool="full", day_temp="33", night_temp="26",
         span_km=22, outdoor_max=0,
         query="上海1天夜景游，下午出发逛外滩夜景"),

    dict(id="shanghai-3d-sunny-history",
         tier="regression", destination="上海", days=3, start="2026-08-10",
         pref="历史建筑、近代史、外滩", habit="正常作息",
         weather="sunny", pool="full", day_temp="33", night_temp="26",
         span_km=22, outdoor_max=0,
         query="上海3天近代历史游，外滩老城厢为主"),

    dict(id="shanghai-3d-allrain-history",
         tier="capability", destination="上海", days=3, start="2026-08-15",
         pref="历史建筑、博物馆、艺术", habit="不喜欢淋雨",
         weather="all_rain", pool="full", day_temp="27", night_temp="22",
         span_km=22, outdoor_max=0,
         query="上海3天全程雨，尽量安排室内博物馆和艺术展"),

    dict(id="shanghai-5d-sunny-nature",
         tier="capability", destination="上海", days=5, start="2026-09-01",
         pref="公园、自然湿地、休闲绿地", habit="喜欢慢慢逛，不要太赶",
         weather="sunny", pool="full", day_temp="29", night_temp="22",
         span_km=22, outdoor_max=0,
         query="上海5天自然公园游，慢节奏，逛公园湿地"),

    dict(id="shanghai-3d-singlerain-slowpace",
         tier="capability", destination="上海", days=3, start="2026-09-10",
         pref="艺术、文化、创意园区", habit="慢节奏，不要太赶，喜欢坐下来感受",
         weather="single_rain", pool="full", day_temp="28", night_temp="21",
         span_km=22, outdoor_max=0,
         query="上海3天艺术文化慢节奏游，第2天有雨"),

    dict(id="shanghai-3d-beyond-forecast",
         tier="capability", destination="上海", days=3, start="2026-11-15",
         pref="历史建筑、博物馆", habit="正常作息",
         weather="beyond", pool="full", day_temp="14", night_temp="7",
         span_km=22, outdoor_max=0,
         query="上海3天游，日期超出天气预报范围"),

    # 负样本：景点池极小（只取评分最高的5个）
    # 3天 × max_per_day=3 理论需要9个景点，池里只有5个 → planner 必须重复或缩排
    dict(id="shanghai-3d-smallpool-negative",
         tier="capability", destination="上海", days=3, start="2026-08-20",
         pref="历史建筑、近代史", habit="正常作息",
         weather="sunny", pool="top_5", day_temp="33", night_temp="26",
         span_km=22, outdoor_max=0,
         query="上海3天游（负样本：候选景点池极小，只有5个景点，考验规划弹性）"),

    # ════════════════════ 丽江（6例）════════════════════
    # 丽江景点分散（古城/玉龙雪山/束河等），span_km 放宽到25
    dict(id="lijiang-3d-sunny-nature",
         tier="capability", destination="丽江", days=3, start="2026-09-05",
         pref="自然风光、雪山、古镇", habit="正常作息",
         weather="sunny", pool="full", day_temp="22", night_temp="12",
         span_km=28, outdoor_max=0,
         query="丽江3天自然风光游，玉龙雪山加古城"),

    dict(id="lijiang-3d-singlerain-nature",
         tier="capability", destination="丽江", days=3, start="2026-09-12",
         pref="自然风光、纳西文化", habit="正常作息",
         weather="single_rain", pool="full", day_temp="22", night_temp="12",
         span_km=28, outdoor_max=0,
         query="丽江3天游，第2天有雨，雨天安排纳西室内文化体验"),

    dict(id="lijiang-5d-sunny-slowpace",
         tier="capability", destination="丽江", days=5, start="2026-09-20",
         pref="古镇文化、纳西民族风情、手工艺", habit="慢节奏，睡到自然醒，不早起",
         weather="sunny", pool="full", day_temp="21", night_temp="11",
         span_km=28, outdoor_max=0,
         query="丽江5天慢节奏深度游，感受纳西文化，不早起"),

    dict(id="lijiang-3d-allrain-history",
         tier="capability", destination="丽江", days=3, start="2026-09-15",
         pref="纳西文化、历史古迹", habit="正常作息",
         weather="all_rain", pool="full", day_temp="18", night_temp="10",
         span_km=28, outdoor_max=0,
         query="丽江3天全程雨，以室内纳西文化体验和博物馆为主"),

    dict(id="lijiang-1d-sunny-nightlife",
         tier="capability", destination="丽江", days=1, start="2026-09-08",
         pref="古镇夜景、酒吧街、纳西夜市", habit="下午抵达，重点体验夜晚古镇",
         weather="sunny", pool="full", day_temp="22", night_temp="13",
         span_km=20, outdoor_max=0,
         query="丽江1天夜景游，下午到，晚上逛酒吧街和四方街夜景"),

    # 负样本：景点池极小
    dict(id="lijiang-3d-smallpool-negative",
         tier="capability", destination="丽江", days=3, start="2026-09-25",
         pref="自然风光、古镇", habit="正常作息",
         weather="sunny", pool="top_5", day_temp="20", night_temp="10",
         span_km=28, outdoor_max=0,
         query="丽江3天游（负样本：候选景点池极小，只有5个景点）"),

    # ════════════════════ 三亚（5例）════════════════════
    # 三亚景点距离跨度大（市区到天涯海角约40km），span_km设宽
    dict(id="sanya-3d-sunny-nature",
         tier="capability", destination="三亚", days=3, start="2026-12-05",
         pref="海滨自然、热带风光、沙滩", habit="正常作息",
         weather="sunny", pool="full", day_temp="28", night_temp="22",
         span_km=30, outdoor_max=0,
         query="三亚3天海滨自然游，亚龙湾加天涯海角"),

    dict(id="sanya-5d-sunny-slowpace",
         tier="capability", destination="三亚", days=5, start="2026-12-10",
         pref="海滨度假、热带植物、休闲", habit="慢节奏，每天景点别太多，不早起",
         weather="sunny", pool="full", day_temp="29", night_temp="23",
         span_km=30, outdoor_max=0,
         query="三亚5天慢节奏海滨度假，不早起，每天2个景点就够"),

    # 负样本：全程雨 + 候选池只含露天景点（三亚海滩景区多数露天）
    # 考验 planner 在"无室内可选"时如何权衡；outdoor_max=1 表示雨天最多允许1个露天
    dict(id="sanya-3d-allrain-outdoor-negative",
         tier="capability", destination="三亚", days=3, start="2026-10-15",
         pref="海滨自然", habit="正常作息",
         weather="all_rain", pool="outdoor_only", day_temp="25", night_temp="21",
         span_km=30, outdoor_max=1,
         query="三亚3天全程雨（负样本：景点池全是海滩露天景区，考验天气权衡能力）"),

    dict(id="sanya-1d-sunny-nightlife",
         tier="capability", destination="三亚", days=1, start="2026-12-03",
         pref="夜市、海鲜大排档、海滨夜景", habit="下午出发，重点逛夜市吃海鲜",
         weather="sunny", pool="full", day_temp="28", night_temp="23",
         span_km=20, outdoor_max=0,
         query="三亚1天夜景美食游，傍晚出发，吃海鲜逛夜市"),

    dict(id="sanya-3d-singlerain-nature",
         tier="capability", destination="三亚", days=3, start="2026-12-18",
         pref="热带自然、红树林、海洋", habit="正常作息",
         weather="single_rain", pool="full", day_temp="27", night_temp="21",
         span_km=30, outdoor_max=0,
         query="三亚3天自然游，第2天有雨，雨天安排水族馆等室内活动"),

    # ════════════════════ 景德镇（4例）════════════════════
    # 景德镇为小城市，实际 POI 池仅14个（API实测），天然适合 smallpool 负样本
    dict(id="jingdezhen-3d-sunny-history",
         tier="capability", destination="景德镇", days=3, start="2026-10-05",
         pref="陶瓷文化、历史窑址", habit="正常作息",
         weather="sunny", pool="full", day_temp="22", night_temp="14",
         span_km=12, outdoor_max=0,
         query="景德镇3天陶瓷文化历史游，古窑和博物馆为主"),

    dict(id="jingdezhen-1d-sunny-history",
         tier="regression", destination="景德镇", days=1, start="2026-10-03",
         pref="陶瓷文化、历史", habit="正常作息",
         weather="sunny", pool="full", day_temp="22", night_temp="14",
         span_km=12, outdoor_max=0,
         query="景德镇1天陶瓷历史精华游"),

    dict(id="jingdezhen-3d-singlerain-history",
         tier="capability", destination="景德镇", days=3, start="2026-10-12",
         pref="陶瓷文化、非遗体验", habit="正常作息",
         weather="single_rain", pool="full", day_temp="20", night_temp="12",
         span_km=12, outdoor_max=0,
         query="景德镇3天陶瓷游，第2天有雨，雨天优先室内窑址博物馆"),

    # 负样本：景点池极小（只取最高分的4个）
    # 景德镇本身14个 POI，再缩到4个 → 3天×3=9 个名额只有4个候选
    dict(id="jingdezhen-3d-smallpool-negative",
         tier="capability", destination="景德镇", days=3, start="2026-10-20",
         pref="陶瓷文化", habit="正常作息",
         weather="sunny", pool="top_4", day_temp="20", night_temp="12",
         span_km=12, outdoor_max=0,
         query="景德镇3天游（负样本：候选景点池极小仅4个景点，考验规划弹性）"),
]

assert len(SPECS) == 30, f"预期30个规格，实际{len(SPECS)}个"


# ── 构造单个 fixture ─────────────────────────────────────────────
def build_fixture(spec: dict[str, Any], raw_pois: list[dict]) -> dict:
    # 1. 打 indoor 标签
    labeled = [{**p, "indoor": label_indoor(p["name"])} for p in raw_pois]
    # 2. 按模式筛选
    pool = apply_pool_mode(labeled, spec["pool"])
    # 3. 计算日期
    start_str = spec["start"]
    end_str = (date.fromisoformat(start_str) + timedelta(days=spec["days"] - 1)).isoformat()
    # 4. 构造天气
    weather = make_weather(start_str, spec["days"], spec["weather"],
                           spec["day_temp"], spec["night_temp"])
    weather_note = ("旅游日期超出天气预报范围，建议出行前关注天气预报"
                    if spec["weather"] == "beyond" else None)
    fx: dict[str, Any] = {
        "id":                   spec["id"],
        "tier":                 spec["tier"],
        "destination":          spec["destination"],
        "query":                spec.get("query", ""),
        "travel_start_date":    start_str,
        "travel_end_date":      end_str,
        "days":                 spec["days"],
        "attraction_preference": spec["pref"],
        "habit_preference":     spec["habit"],
        "max_per_day":          spec.get("max_per_day", 3),
        "min_rating":           spec.get("min_rating", 4.5),
        "max_review_rounds":    spec.get("max_review_rounds", 3),
        "pois":                 pool,
        "weather_forecast":     weather,
        "expectations": {
            "max_day_span_km":        spec["span_km"],
            "outdoor_on_bad_day_max": spec["outdoor_max"],
        },
    }
    if weather_note:
        fx["weather_note"] = weather_note
    return fx


# ── 主流程 ───────────────────────────────────────────────────────
def main() -> None:
    key = amap_key()
    FIXTURES_DIR.mkdir(exist_ok=True)

    # 1. 按城市抓景点（每城只调一次 API）
    cities = sorted({s["destination"] for s in SPECS})
    city_pois: dict[str, list[dict]] = {}
    print(f"🌐 正在调高德 API 抓取 {len(cities)} 个城市景点数据…\n")
    for city in cities:
        raw = fetch_city_spots(city, key, max_spots=30)
        kept, _ = filter_by_rating(raw, 4.5)
        city_pois[city] = kept
        indoor_n = sum(1 for p in kept if label_indoor(p["name"]))
        print(f"  {city}：原始 {len(raw)} 个 → 评分达标 {len(kept)} 个"
              f"（室内 {indoor_n} / 露天 {len(kept) - indoor_n}）")
    print()

    # 2. 生成所有 fixture
    print(f"📝 正在生成 {len(SPECS)} 个 fixture…\n")
    for spec in SPECS:
        raw_pois = city_pois[spec["destination"]]
        fx = build_fixture(spec, raw_pois)
        out = FIXTURES_DIR / f"{spec['id']}.json"
        out.write_text(json.dumps(fx, ensure_ascii=False, indent=2), encoding="utf-8")

        pool_n = len(fx["pois"])
        indoor_n = sum(1 for p in fx["pois"] if p.get("indoor"))
        weather_n = len(fx["weather_forecast"])
        bad_n = sum(1 for w in fx["weather_forecast"] if w.get("is_bad"))
        print(f"  ✓ {spec['id']}")
        print(f"      tier={spec['tier']}  days={spec['days']}  "
              f"pool={pool_n}个（室内{indoor_n}/露天{pool_n - indoor_n}）  "
              f"天气={weather_n}天（雨{bad_n}天）  模式={spec['pool']}")

    print(f"\n✅ 完成！共生成 {len(SPECS)} 个 fixture，写入 {FIXTURES_DIR}")
    print("\n三个负样本说明：")
    print("  outdoor_only：只保留 indoor=False 的景点，配合全雨天气 → 考验天气权衡")
    print("  top_4/top_5 ：只取评分最高的N个景点 → 候选池远小于 days×max_per_day")
    print("  tight_hours ：优先选开放时长≤9h景点 → 时刻表安排困难，G2易触发")


if __name__ == "__main__":
    main()
