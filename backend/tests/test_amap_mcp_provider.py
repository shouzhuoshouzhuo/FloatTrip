"""高德 MCP provider 单元测试。

功能：
    验证高德 MCP 天气工具调用格式和返回结构解析，避免行程详情天气能力
    因工具名或 MCP content 包装变化而不可用。
"""

from __future__ import annotations

import unittest
from unittest.mock import MagicMock, patch

from backend.app.providers import amap_mcp


class AMapMcpProviderTest(unittest.TestCase):
    """功能：覆盖高德 MCP 天气调用和解析行为。"""

    def test_query_weather_calls_amap_maps_weather_with_city(self) -> None:
        """功能：验证天气查询会调用高德 MCP 官方天气工具名。

        参数：
            无。
        返回值：
            无返回值；通过 mock 断言验证工具名和 city 参数。
        """
        mock_client = MagicMock()
        with patch("backend.app.providers.amap_mcp.httpx.Client") as client_factory, patch(
            "backend.app.providers.amap_mcp.rpc",
            side_effect=[
                {"sessionId": "session-1"},
                {"tools": [{"name": "amap_maps_weather"}]},
                {
                    "content": [
                        {
                            "type": "text",
                            "text": '{"forecasts":[{"casts":[{"date":"2026-05-24","dayweather":"晴"}]}]}',
                        }
                    ]
                },
            ],
        ) as rpc_mock:
            client_factory.return_value.__enter__.return_value = mock_client

            casts = amap_mcp.query_weather(city="南京", mcp_url="https://mcp.example.test/mcp")

        self.assertEqual("晴", casts[0]["dayweather"])
        self.assertEqual(
            {
                "name": "amap_maps_weather",
                "arguments": {"city": "南京"},
            },
            rpc_mock.call_args_list[2].args[3],
        )

    def test_extract_weather_casts_reads_direct_forecasts_payload(self) -> None:
        """功能：验证可从高德 forecasts[].casts 结构提取天气列表。

        参数：
            无。
        返回值：
            无返回值；通过断言验证解析结果。
        """
        casts = amap_mcp.extract_weather_casts(
            {
                "forecasts": [
                    {
                        "city": "南京市",
                        "casts": [
                            {
                                "date": "2026-05-24",
                                "dayweather": "多云",
                                "daytemp": "27",
                            }
                        ],
                    }
                ]
            }
        )

        self.assertEqual("多云", casts[0]["dayweather"])


if __name__ == "__main__":
    unittest.main()
