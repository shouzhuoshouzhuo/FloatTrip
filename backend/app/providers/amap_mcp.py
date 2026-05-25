"""高德 MCP provider。

功能：
    通过高德 Streamable HTTP MCP 服务调用天气、周边搜索等工具，为行程详情
    Agent 提供城市天气和附近 POI 候选。该模块只封装 MCP 调用和字段归一化，
    不负责日程编排决策。
"""

from __future__ import annotations

import json
import os
import uuid
from typing import Any

import httpx

from backend.app.providers import amap


def require_amap_mcp_url() -> str:
    """功能：读取高德 MCP Streamable HTTP 地址。

    参数：
        无。
    返回值：
        返回 AMAP_MCP_URL 字符串。
    """
    amap.load_local_env()
    url = os.getenv("AMAP_MCP_URL", "").strip()
    if not url:
        raise RuntimeError("缺少 AMAP_MCP_URL。请配置高德 MCP 地址后重试。")
    return url


def search_nearby_pois(
    *,
    keywords: str,
    location: dict[str, float],
    radius: int = 1500,
    limit: int = 6,
    mcp_url: str | None = None,
) -> list[dict[str, Any]]:
    """功能：通过高德 MCP 按关键词、中心点和半径搜索周边 POI。

    参数：
        keywords：搜索关键词，例如“饭店”“餐厅”。
        location：中心点坐标，格式为 {"lng": 经度, "lat": 纬度}。
        radius：搜索半径，单位米。
        limit：最多返回的 POI 数量。
        mcp_url：高德 MCP Streamable HTTP 地址；不传则读取 AMAP_MCP_URL。
    返回值：
        返回归一化后的 POI 字典列表。
    """
    url = mcp_url or require_amap_mcp_url()
    arguments = {
        "keywords": keywords,
        "location": f"{location['lng']},{location['lat']}",
        "radius": radius,
    }
    raw_result = call_first_matching_tool(
        url,
        arguments,
        tool_name_keywords=("around", "nearby", "周边", "search", "poi"),
    )
    pois = extract_pois(raw_result)
    return [normalize_mcp_poi(poi) for poi in pois[:limit] if isinstance(poi, dict)]


def query_weather(*, city: str, mcp_url: str | None = None) -> list[dict[str, Any]]:
    """功能：通过高德 MCP 天气工具查询城市天气预报。

    参数：
        city：城市名称，例如“南京”。
        mcp_url：高德 MCP Streamable HTTP 地址；不传则读取 AMAP_MCP_URL。
    返回值：
        返回高德天气 casts 列表；没有可识别天气时返回空列表。
    """
    url = mcp_url or require_amap_mcp_url()
    raw_result = call_tool(
        url,
        tool_name="amap_maps_weather",
        arguments={"city": city},
        fallback_keywords=("weather", "天气"),
    )
    return extract_weather_casts(raw_result)


def call_tool(
    mcp_url: str,
    *,
    tool_name: str,
    arguments: dict[str, Any],
    fallback_keywords: tuple[str, ...] = (),
) -> Any:
    """功能：初始化 MCP 会话并调用指定工具。

    参数：
        mcp_url：高德 MCP Streamable HTTP 地址。
        tool_name：优先调用的工具名称。
        arguments：传给工具的参数。
        fallback_keywords：指定工具不存在时用于匹配替代工具的关键词。
    返回值：
        返回 MCP tools/call 的 result 字段。
    """
    with httpx.Client(timeout=20) as client:
        initialize_result = rpc(client, mcp_url, "initialize", {"protocolVersion": "2024-11-05"})
        session_id = initialize_result.get("sessionId") if isinstance(initialize_result, dict) else None
        tools_result = rpc(client, mcp_url, "tools/list", {}, session_id=session_id)
        tools = tools_result.get("tools", []) if isinstance(tools_result, dict) else []
        available_names = {
            str(tool.get("name") or "")
            for tool in tools
            if isinstance(tool, dict) and tool.get("name")
        }
        resolved_tool_name = tool_name if tool_name in available_names else None
        if not resolved_tool_name and fallback_keywords:
            resolved_tool_name = choose_tool_name(tools, fallback_keywords)
        if not resolved_tool_name:
            raise RuntimeError(f"高德 MCP 未返回可用工具：{tool_name}")
        return rpc(
            client,
            mcp_url,
            "tools/call",
            {"name": resolved_tool_name, "arguments": arguments},
            session_id=session_id,
        )


def call_first_matching_tool(
    mcp_url: str,
    arguments: dict[str, Any],
    *,
    tool_name_keywords: tuple[str, ...],
) -> Any:
    """功能：初始化 MCP 会话，查找匹配工具并调用。

    参数：
        mcp_url：高德 MCP Streamable HTTP 地址。
        arguments：传给工具的参数。
        tool_name_keywords：用于匹配工具名称或描述的关键词。
    返回值：
        返回 MCP tools/call 的 result 字段。
    """
    with httpx.Client(timeout=20) as client:
        initialize_result = rpc(client, mcp_url, "initialize", {"protocolVersion": "2024-11-05"})
        session_id = initialize_result.get("sessionId") if isinstance(initialize_result, dict) else None
        tools_result = rpc(client, mcp_url, "tools/list", {}, session_id=session_id)
        tools = tools_result.get("tools", []) if isinstance(tools_result, dict) else []
        tool_name = choose_tool_name(tools, tool_name_keywords)
        if not tool_name:
            raise RuntimeError("高德 MCP 未返回可用于周边搜索的工具")
        return rpc(
            client,
            mcp_url,
            "tools/call",
            {"name": tool_name, "arguments": arguments},
            session_id=session_id,
        )


def rpc(
    client: httpx.Client,
    mcp_url: str,
    method: str,
    params: dict[str, Any],
    *,
    session_id: str | None = None,
) -> Any:
    """功能：发送 JSON-RPC 请求到 Streamable HTTP MCP 服务。

    参数：
        client：httpx 同步客户端。
        mcp_url：MCP 服务地址。
        method：JSON-RPC 方法名。
        params：方法参数。
        session_id：MCP 会话 ID，可为空。
    返回值：
        返回 JSON-RPC result 字段。
    """
    headers = {
        "Accept": "application/json, text/event-stream",
        "Content-Type": "application/json",
    }
    if session_id:
        headers["Mcp-Session-Id"] = session_id
    response = client.post(
        mcp_url,
        headers=headers,
        json={
            "jsonrpc": "2.0",
            "id": str(uuid.uuid4()),
            "method": method,
            "params": params,
        },
    )
    response.raise_for_status()
    data = parse_rpc_response(response)
    if data.get("error"):
        raise RuntimeError(f"高德 MCP 调用失败：{data['error']}")
    return data.get("result")


def parse_rpc_response(response: httpx.Response) -> dict[str, Any]:
    """功能：兼容解析 MCP JSON 响应和 text/event-stream 响应。

    参数：
        response：高德 MCP HTTP 响应对象。
    返回值：
        返回 JSON-RPC 响应字典；无法解析时抛出运行时错误。
    """
    content_type = response.headers.get("content-type", "")
    if "text/event-stream" not in content_type:
        data = response.json()
        return data if isinstance(data, dict) else {}

    for line in response.text.splitlines():
        if not line.startswith("data:"):
            continue
        payload = line.removeprefix("data:").strip()
        if not payload or payload == "[DONE]":
            continue
        try:
            data = json.loads(payload)
        except json.JSONDecodeError as exc:
            raise RuntimeError(f"高德 MCP event-stream 响应解析失败：{exc}") from exc
        return data if isinstance(data, dict) else {}
    raise RuntimeError("高德 MCP event-stream 响应为空")


def choose_tool_name(tools: list[Any], keywords: tuple[str, ...]) -> str | None:
    """功能：从 MCP tools/list 结果中选择周边搜索工具名。

    参数：
        tools：MCP 工具定义列表。
        keywords：匹配工具名和描述的关键词。
    返回值：
        返回工具名；没有匹配时返回 None。
    """
    for tool in tools:
        if not isinstance(tool, dict):
            continue
        name = str(tool.get("name") or "")
        description = str(tool.get("description") or "")
        haystack = f"{name} {description}".lower()
        if any(keyword.lower() in haystack for keyword in keywords):
            return name
    return str(tools[0].get("name")) if tools and isinstance(tools[0], dict) else None


def extract_pois(raw_result: Any) -> list[Any]:
    """功能：从 MCP 返回结构中提取 POI 列表。

    参数：
        raw_result：MCP tools/call result 字段。
    返回值：
        返回 POI 原始列表；无法识别时返回空列表。
    """
    if isinstance(raw_result, dict):
        if isinstance(raw_result.get("pois"), list):
            return raw_result["pois"]
        content = raw_result.get("content")
        if isinstance(content, list):
            for item in content:
                if isinstance(item, dict) and isinstance(item.get("pois"), list):
                    return item["pois"]
                if isinstance(item, dict) and isinstance(item.get("json"), dict):
                    pois = item["json"].get("pois")
                    if isinstance(pois, list):
                        return pois
    return raw_result if isinstance(raw_result, list) else []


def extract_weather_casts(raw_result: Any) -> list[dict[str, Any]]:
    """功能：从 MCP 天气工具返回结构中提取 casts 列表。

    参数：
        raw_result：MCP tools/call result 字段。
    返回值：
        返回天气预报 casts 列表；无法识别时返回空列表。
    """
    payload = unwrap_json_payload(raw_result)
    casts = find_weather_casts(payload)
    return [cast for cast in casts if isinstance(cast, dict)]


def unwrap_json_payload(value: Any) -> Any:
    """功能：兼容 MCP content/text/json 包装，提取可能的 JSON 结构。

    参数：
        value：任意 MCP 返回值。
    返回值：
        返回解包后的 JSON 结构；无法解包时返回原值。
    """
    if isinstance(value, dict):
        if isinstance(value.get("json"), (dict, list)):
            return value["json"]
        content = value.get("content")
        if isinstance(content, list):
            unwrapped_items = [unwrap_json_payload(item) for item in content]
            for item in unwrapped_items:
                if find_weather_casts(item):
                    return item
            return unwrapped_items
        text = value.get("text")
        if isinstance(text, str):
            parsed = parse_json_text(text)
            return parsed if parsed is not None else value
    if isinstance(value, str):
        parsed = parse_json_text(value)
        return parsed if parsed is not None else value
    if isinstance(value, list):
        return [unwrap_json_payload(item) for item in value]
    return value


def parse_json_text(text: str) -> Any:
    """功能：把 MCP 文本内容中可能存在的 JSON 解析出来。

    参数：
        text：MCP 文本内容。
    返回值：
        返回解析后的 JSON；不是 JSON 时返回 None。
    """
    stripped = text.strip()
    candidates = [stripped]
    if "{" in stripped and "}" in stripped:
        candidates.append(stripped[stripped.find("{") : stripped.rfind("}") + 1])
    for candidate in candidates:
        try:
            return json.loads(candidate)
        except json.JSONDecodeError:
            continue
    return None


def find_weather_casts(value: Any) -> list[Any]:
    """功能：递归查找高德天气 forecasts[].casts 或直接 casts 字段。

    参数：
        value：任意 JSON 结构。
    返回值：
        返回 casts 原始列表；未找到时返回空列表。
    """
    if isinstance(value, dict):
        casts = value.get("casts")
        if isinstance(casts, list):
            return casts
        forecasts = value.get("forecasts")
        if isinstance(forecasts, list):
            for forecast in forecasts:
                found = find_weather_casts(forecast)
                if found:
                    return found
        for child in value.values():
            found = find_weather_casts(child)
            if found:
                return found
    if isinstance(value, list):
        if value and all(isinstance(item, dict) and "date" in item for item in value):
            return value
        for item in value:
            found = find_weather_casts(item)
            if found:
                return found
    return []


def normalize_mcp_poi(poi: dict[str, Any]) -> dict[str, Any]:
    """功能：把高德 MCP POI 字段整理成 FloatTrip 内部结构。

    参数：
        poi：高德 MCP 返回的原始 POI 字典。
    返回值：
        返回归一化后的 POI 字典。
    """
    return {
        "provider": "amap_mcp",
        "id": str(poi.get("id") or poi.get("poiid") or ""),
        "name": str(poi.get("name") or ""),
        "type": str(poi.get("type") or ""),
        "address": amap.normalize_address(poi.get("address")),
        "distance_meters": int_or_none(poi.get("distance")),
        "location": amap.parse_location(str(poi.get("location") or "")),
        "raw": poi,
    }


def int_or_none(value: Any) -> int | None:
    """功能：把高德距离字段转换成整数。

    参数：
        value：任意距离值。
    返回值：
        可转换时返回整数，否则返回 None。
    """
    try:
        return int(float(str(value)))
    except (TypeError, ValueError):
        return None
