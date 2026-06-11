"""行程手动编辑 API 测试：search_city_pois / poi 搜索代理 / PUT timeline 保存。"""

from __future__ import annotations

import urllib.parse
import uuid

import pytest
from fastapi.testclient import TestClient


# ─── search_city_pois ────────────────────────────────────────

class TestSearchCityPois:
    def test_传入类型与关键词并解析结果(self, monkeypatch):
        from app.providers.amap import poi as poi_mod

        captured = {}

        def fake_get(url):
            captured["url"] = url
            return {"status": "1", "pois": [{"name": "颐和路", "location": "118.77,32.06"}]}

        monkeypatch.setattr(poi_mod, "http_get_json", fake_get)
        out = poi_mod.search_city_pois("南京", "k", keywords="颐和路", types="风景名胜", offset=8)
        assert out == [{"name": "颐和路", "location": "118.77,32.06"}]

        # 用 parse_qs 解析 URL query string
        parsed_url = urllib.parse.urlparse(captured["url"])
        query_params = urllib.parse.parse_qs(parsed_url.query)
        assert query_params["keywords"] == ["颐和路"]
        assert query_params["types"] == ["风景名胜"]
        assert query_params["citylimit"] == ["true"]
        assert query_params["offset"] == ["8"]

    def test_接口失败抛RuntimeError(self, monkeypatch):
        from app.providers.amap import poi as poi_mod

        monkeypatch.setattr(poi_mod, "http_get_json", lambda url: {"status": "0", "info": "INVALID_KEY"})
        with pytest.raises(RuntimeError, match="INVALID_KEY"):
            poi_mod.search_city_pois("南京", "k", keywords="x", types="餐饮服务")
