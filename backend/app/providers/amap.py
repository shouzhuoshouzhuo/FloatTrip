"""高德地点能力的公共工具，供命令行脚本和后端服务复用。"""

from __future__ import annotations

import json
import os
import re
import time
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any


USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "FloatTripAmapProvider/0.1"
)
LOCAL_ENV_FILE = Path(__file__).resolve().parents[3] / ".env.local"
AMAP_TEXT_SEARCH_URL = "https://restapi.amap.com/v3/place/text"

ATTRACTION_TYPE_KEYWORDS = (
    "风景名胜",
    "公园广场",
    "博物馆",
    "展览馆",
    "美术馆",
    "科技馆",
    "纪念馆",
    "寺庙",
    "道观",
    "教堂",
    "文化宫",
    "文物古迹",
    "动物园",
    "植物园",
    "水族馆",
    "海洋馆",
    "游乐场",
    "主题乐园",
    "度假区",
    "自然地名",
)

BLOCKED_TYPE_KEYWORDS = (
    "住宿服务",
    "餐饮服务",
    "购物服务",
    "生活服务",
    "公司企业",
    "商务住宅",
    "金融保险",
    "汽车服务",
    "汽车维修",
    "摩托车服务",
    "医疗保健",
    "政府机构",
    "科教文化服务;学校",
    "交通设施服务",
    "道路附属设施",
)


def load_local_env() -> None:
    """读取项目根目录的本地环境变量文件，并且不覆盖已有环境变量。"""
    if not LOCAL_ENV_FILE.exists():
        return
    for line in LOCAL_ENV_FILE.read_text(encoding="utf-8").splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#") or "=" not in stripped:
            continue
        key, value = stripped.split("=", 1)
        key = key.strip()
        value = value.strip().strip("\"'")
        if key and key not in os.environ:
            os.environ[key] = value


def require_amap_key() -> str:
    """读取高德网络服务密钥，没有配置时抛出明确错误。"""
    api_key = os.getenv("AMAP_API_KEY", "").strip()
    if not api_key:
        raise RuntimeError("缺少 AMAP_API_KEY。请在环境变量或 .env.local 中配置高德 Web服务 Key 后重试。")
    return api_key


def http_get_json(url: str, timeout: int = 15) -> dict[str, Any]:
    """发起高德网络请求并解析结构化响应，失败时自动重试。"""
    request = urllib.request.Request(
        url,
        headers={
            "User-Agent": USER_AGENT,
            "Accept": "application/json,*/*;q=0.8",
            "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.7",
        },
    )
    last_error: Exception | None = None
    for attempt in range(3):
        try:
            with urllib.request.urlopen(request, timeout=timeout) as response:
                charset = response.headers.get_content_charset() or "utf-8"
                return json.loads(response.read().decode(charset, errors="replace"))
        except Exception as exc:
            last_error = exc
            time.sleep(0.8 * (attempt + 1))
    raise RuntimeError(f"请求失败：{redact_url(url)}；原因：{last_error}")


def redact_url(url: str) -> str:
    """隐藏网址中的密钥字段，避免错误信息泄露凭据。"""
    parsed = urllib.parse.urlparse(url)
    query = urllib.parse.parse_qs(parsed.query, keep_blank_values=True)
    for secret_key in ("key", "api_key", "access_token", "token"):
        if secret_key in query:
            query[secret_key] = ["<redacted>"]
    redacted_query = urllib.parse.urlencode(query, doseq=True)
    return urllib.parse.urlunparse(parsed._replace(query=redacted_query))


def search_amap_pois(keyword: str, admin_region: str, api_key: str, offset: int) -> list[dict[str, Any]]:
    """调用高德关键字地点搜索，返回指定行政区内的候选地点列表。"""
    params = {
        "key": api_key,
        "keywords": keyword,
        "city": admin_region,
        "citylimit": "true",
        "offset": str(offset),
        "page": "1",
        "extensions": "all",
        "output": "json",
    }
    url = f"{AMAP_TEXT_SEARCH_URL}?{urllib.parse.urlencode(params)}"
    data = http_get_json(url)
    if data.get("status") != "1":
        info = data.get("info") or "未知错误"
        raise RuntimeError(f"高德 POI 搜索失败：{info}")
    pois = data.get("pois", [])
    return pois if isinstance(pois, list) else []


def choose_attraction_poi(
    candidate_name: str,
    pois: list[dict[str, Any]],
    admin_region: str,
) -> dict[str, Any] | None:
    """从高德返回的多个地点中选择最像真实景点的一个。"""
    best_poi: dict[str, Any] | None = None
    best_score = -1
    for poi in pois:
        if not isinstance(poi, dict):
            continue
        poi_type = str(poi.get("type", ""))
        poi_name = str(poi.get("name", ""))
        if not is_attraction_type(poi_type) or not is_in_admin_region(poi, admin_region):
            continue
        score = match_score(candidate_name, poi_name, poi_type)
        if score > best_score:
            best_score = score
            best_poi = poi
    return best_poi


def is_in_admin_region(poi: dict[str, Any], admin_region: str) -> bool:
    """判断地点是否属于用户指定的行政区名称或行政区编码。"""
    region = admin_region.strip()
    if not region:
        return False

    adcode = str(poi.get("adcode", "")).strip()
    if re.fullmatch(r"\d{6}", region):
        return adcode_matches_region(adcode, region)

    expected_name = normalize_region_name(region)
    poi_region_names = (
        poi.get("pname", ""),
        poi.get("cityname", ""),
        poi.get("adname", ""),
    )
    return any(
        normalize_region_name(str(name)) == expected_name
        for name in poi_region_names
        if name
    )


def adcode_matches_region(poi_adcode: str, region_adcode: str) -> bool:
    """按省、市、区县三级行政区编码前缀规则判断行政区是否匹配。"""
    if not re.fullmatch(r"\d{6}", poi_adcode):
        return False
    if region_adcode.endswith("0000"):
        return poi_adcode[:2] == region_adcode[:2]
    if region_adcode.endswith("00"):
        return poi_adcode[:4] == region_adcode[:4]
    return poi_adcode == region_adcode


def normalize_region_name(region: str) -> str:
    """去掉常见行政区后缀，提升城市名和区县名匹配稳定性。"""
    normalized = region.strip()
    for suffix in ("特别行政区", "自治州", "自治区", "省", "市", "区", "县"):
        if normalized.endswith(suffix):
            return normalized[: -len(suffix)]
    return normalized


def is_attraction_type(poi_type: str) -> bool:
    """判断高德地点类型是否属于可游玩的景点范围。"""
    if not poi_type:
        return False
    if any(blocked in poi_type for blocked in BLOCKED_TYPE_KEYWORDS):
        return False
    return any(keyword in poi_type for keyword in ATTRACTION_TYPE_KEYWORDS)


def match_score(candidate_name: str, poi_name: str, poi_type: str) -> int:
    """根据名称相似度和地点类型为候选匹配打分。"""
    score = 0
    if candidate_name == poi_name:
        score += 100
    elif candidate_name in poi_name or poi_name in candidate_name:
        score += 70
    else:
        score += common_char_score(candidate_name, poi_name)

    if "风景名胜" in poi_type:
        score += 20
    if any(keyword in poi_type for keyword in ("博物馆", "纪念馆", "公园广场", "文物古迹")):
        score += 12
    return score


def common_char_score(left: str, right: str) -> int:
    """用有意义字符的交集比例估算两个中文名称的相似度。"""
    left_chars = {char for char in left if is_meaningful_char(char)}
    right_chars = {char for char in right if is_meaningful_char(char)}
    if not left_chars or not right_chars:
        return 0
    return int(40 * len(left_chars & right_chars) / len(left_chars | right_chars))


def is_meaningful_char(char: str) -> bool:
    """判断字符是否适合参与景点名称相似度计算。"""
    return bool(re.match(r"[\u4e00-\u9fa5A-Za-z0-9]", char))


def parse_location(value: Any) -> dict[str, float] | None:
    """把高德返回的经纬度字符串解析成结构化坐标。"""
    if not isinstance(value, str) or "," not in value:
        return None
    lng_text, lat_text = value.split(",", 1)
    try:
        return {"lng": float(lng_text), "lat": float(lat_text)}
    except ValueError:
        return None


def normalize_poi(poi: dict[str, Any]) -> dict[str, Any]:
    """把高德原始地点字段整理成项目内部统一结构。"""
    normalized = {
        "provider": "amap",
        "id": str(poi.get("id", "")),
        "name": str(poi.get("name", "")),
        "type": str(poi.get("type", "")),
        "adcode": str(poi.get("adcode", "")),
        "province": str(poi.get("pname", "")),
        "city": str(poi.get("cityname", "")),
        "district": str(poi.get("adname", "")),
        "address": normalize_address(poi.get("address")),
        "location": parse_location(poi.get("location")),
    }
    return {key: value for key, value in normalized.items() if value not in ("", None, [])}


def normalize_address(value: Any) -> str:
    """把高德可能返回的字符串或数组地址统一成字符串。"""
    if isinstance(value, list):
        return " ".join(str(item) for item in value if item)
    return str(value or "")
