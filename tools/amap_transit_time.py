#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
输入两个地点名称，调用高德地图 API 返回公交通行时间。

默认会自动读取：
/Users/chj/Desktop/旅游规划agent/.env.local

并使用其中的：
AMAP_API_KEY=你的高德Key

用法：
    python3 amap_transit_time.py 常州 "青果巷" "中华恐龙园"

也可以手动指定 env 文件：
    python3 amap_transit_time.py 常州 "青果巷" "中华恐龙园" --env-file "/Users/chj/Desktop/旅游规划agent/.env.local"
"""

import argparse
import os
import sys
from pathlib import Path
from typing import Any, Dict

import requests
from dotenv import load_dotenv


DEFAULT_ENV_FILE = "/Users/chj/Desktop/旅游规划agent/.env.local"

GEOCODE_URL = "https://restapi.amap.com/v3/geocode/geo"
TRANSIT_URL = "https://restapi.amap.com/v3/direction/transit/integrated"


class AMapError(RuntimeError):
    pass


def load_project_env(env_file: str = DEFAULT_ENV_FILE) -> None:
    """
    加载项目 .env.local。
    不覆盖系统里已经存在的环境变量。
    """
    env_path = Path(env_file).expanduser()

    if env_path.exists():
        load_dotenv(dotenv_path=env_path, override=False)
    else:
        # 不直接报错，允许用户通过系统环境变量 AMAP_API_KEY 传入
        pass


def get_amap_key() -> str:
    """
    优先读取你的项目变量 AMAP_API_KEY。
    兼容旧变量名 AMAP_KEY。
    """
    key = os.getenv("AMAP_API_KEY") or os.getenv("AMAP_KEY")

    if not key:
        raise AMapError(
            "没有找到高德 API Key。\n"
            "请确认 .env.local 中存在：AMAP_API_KEY=你的高德Key\n"
            f"默认读取路径：{DEFAULT_ENV_FILE}"
        )

    return key


def amap_get(url: str, params: Dict[str, Any]) -> Dict[str, Any]:
    try:
        resp = requests.get(url, params=params, timeout=12)
        resp.raise_for_status()
    except requests.RequestException as exc:
        raise AMapError(f"HTTP 请求失败: {exc}") from exc

    try:
        data = resp.json()
    except ValueError as exc:
        raise AMapError(f"响应不是合法 JSON: {resp.text[:300]}") from exc

    if data.get("status") != "1":
        raise AMapError(
            f"高德 API 返回失败: info={data.get('info')}, "
            f"infocode={data.get('infocode')}, response={data}"
        )

    return data


def geocode(address: str, city: str, key: str) -> Dict[str, str]:
    """
    地点名称 -> 高德经纬度。

    返回：
        {
            "address": "青果巷",
            "formatted_address": "...",
            "location": "119.xxx,31.xxx",
            "city": "常州市",
            "district": "天宁区"
        }
    """
    params = {
        "key": key,
        "address": address,
        "city": city,
        "output": "json",
    }

    data = amap_get(GEOCODE_URL, params)
    geocodes = data.get("geocodes", [])

    if not geocodes:
        raise AMapError(f"没有找到地点坐标: address={address}, city={city}")

    item = geocodes[0]
    location = item.get("location")

    if not location:
        raise AMapError(f"地点没有返回 location: {address}, response={item}")

    return {
        "address": address,
        "formatted_address": item.get("formatted_address", ""),
        "location": location,
        "city": item.get("city", ""),
        "district": item.get("district", ""),
    }


def get_transit_time(
    origin_location: str,
    destination_location: str,
    city: str,
    key: str,
    strategy: int = 0,
) -> Dict[str, Any]:
    """
    调用高德公交路径规划 API。

    strategy 常用值：
        0：最快捷模式
        1：最经济模式
        2：最少换乘模式
        3：最少步行模式
        5：不乘地铁模式

    高德返回 duration 单位是秒。
    """
    params = {
        "key": key,
        "origin": origin_location,
        "destination": destination_location,
        "city": city,
        "strategy": strategy,
        "output": "json",
    }

    data = amap_get(TRANSIT_URL, params)

    transits = data.get("route", {}).get("transits", [])

    valid_transits = []
    for transit in transits:
        duration = transit.get("duration")
        if duration is not None and str(duration).isdigit():
            valid_transits.append(transit)

    if not valid_transits:
        raise AMapError(f"没有找到可用公交路线: response={data}")

    best = min(valid_transits, key=lambda x: int(x["duration"]))

    duration_sec = int(best["duration"])
    duration_min = round(duration_sec / 60, 1)

    distance_m = best.get("distance")
    walking_distance_m = best.get("walking_distance")

    return {
        "duration_sec": duration_sec,
        "duration_min": duration_min,
        "distance_km": round(int(distance_m) / 1000, 2)
        if str(distance_m).isdigit()
        else None,
        "walking_distance_km": round(int(walking_distance_m) / 1000, 2)
        if str(walking_distance_m).isdigit()
        else None,
        "cost": best.get("cost"),
        "segments_count": len(best.get("segments", [])),
        "raw_best_transit": best,
    }


def summarize_transit_plan(best_transit: Dict[str, Any]) -> str:
    """
    从高德返回的 segments 中提取公交/地铁换乘摘要。
    """
    segments = best_transit.get("segments", [])
    parts = []

    for segment in segments:
        bus = segment.get("bus", {})
        buslines = bus.get("buslines", [])

        if not buslines:
            continue

        line = buslines[0]
        name = line.get("name", "")
        departure_stop = line.get("departure_stop", {}).get("name", "")
        arrival_stop = line.get("arrival_stop", {}).get("name", "")

        if name:
            parts.append(f"{name}: {departure_stop} -> {arrival_stop}")

    return "；".join(parts) if parts else "未解析到公交/地铁线路明细"


def query_transit_time(
    city: str,
    origin: str,
    destination: str,
    strategy: int = 0,
    env_file: str = DEFAULT_ENV_FILE,
) -> Dict[str, Any]:
    """
    给项目内部调用的主函数。
    输入城市、起点、终点，返回结构化通行结果。
    """
    load_project_env(env_file)
    key = get_amap_key()

    origin_geo = geocode(origin, city, key)
    dest_geo = geocode(destination, city, key)

    result = get_transit_time(
        origin_location=origin_geo["location"],
        destination_location=dest_geo["location"],
        city=city,
        key=key,
        strategy=strategy,
    )

    summary = summarize_transit_plan(result["raw_best_transit"])

    return {
        "city": city,
        "origin": {
            "name": origin,
            "formatted_address": origin_geo["formatted_address"],
            "location": origin_geo["location"],
            "district": origin_geo["district"],
        },
        "destination": {
            "name": destination,
            "formatted_address": dest_geo["formatted_address"],
            "location": dest_geo["location"],
            "district": dest_geo["district"],
        },
        "transit": {
            "duration_sec": result["duration_sec"],
            "duration_min": result["duration_min"],
            "distance_km": result["distance_km"],
            "walking_distance_km": result["walking_distance_km"],
            "cost": result["cost"],
            "segments_count": result["segments_count"],
            "summary": summary,
        },
    }


def main() -> int:
    parser = argparse.ArgumentParser(
        description="输入两个地点名称，返回高德公交通行时间"
    )
    parser.add_argument("city", help="城市名，例如：常州、南京、上海")
    parser.add_argument("origin", help="起点，例如：青果巷")
    parser.add_argument("destination", help="终点，例如：中华恐龙园")
    parser.add_argument(
        "--env-file",
        default=DEFAULT_ENV_FILE,
        help=f"环境变量文件路径，默认：{DEFAULT_ENV_FILE}",
    )
    parser.add_argument(
        "--strategy",
        type=int,
        default=0,
        help="公交策略：0最快捷，1最经济，2最少换乘，3最少步行，5不乘地铁",
    )

    args = parser.parse_args()

    try:
        data = query_transit_time(
            city=args.city,
            origin=args.origin,
            destination=args.destination,
            strategy=args.strategy,
            env_file=args.env_file,
        )

        print("起点：", data["origin"]["formatted_address"] or args.origin)
        print("起点坐标：", data["origin"]["location"])
        print("终点：", data["destination"]["formatted_address"] or args.destination)
        print("终点坐标：", data["destination"]["location"])
        print()
        print(f"公交预计耗时：{data['transit']['duration_min']} 分钟")
        print(f"路线距离：{data['transit']['distance_km']} km")
        print(f"步行距离：{data['transit']['walking_distance_km']} km")

        if data["transit"]["cost"]:
            print(f"预计费用：{data['transit']['cost']} 元")

        print("换乘摘要：", data["transit"]["summary"])

        return 0

    except AMapError as exc:
        print(f"错误：{exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())