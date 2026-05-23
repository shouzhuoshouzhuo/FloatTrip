# FloatTrip Frontend

独立前端工程，默认通过 `http://127.0.0.1:8020/api/planner/generate` 对接后端完整规划链路。

## 本地启动

```bash
npm install
npm run dev
```

页面地址：

```text
http://127.0.0.1:8088
```

如需地图渲染，把 `amap-config.example.js` 复制为 `amap-config.local.js` 并填入高德 JS Key。
即使没有 JS Key，页面也会真实请求后端并展示 JSON 返回的调研摘要、路线顺序、时长、距离和 path 状态。
