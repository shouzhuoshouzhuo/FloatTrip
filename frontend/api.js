// api.js — 后端 API 客户端 + 数据适配器

/* ── Auth ─────────────────────────────────────────── */
function getAuth() {
  try { return JSON.parse(localStorage.getItem("auth")); } catch { return null; }
}
function setAuth(token, username) {
  localStorage.setItem("auth", JSON.stringify({ token, username }));
}
function clearAuth() {
  localStorage.removeItem("auth");
  window.dispatchEvent(new CustomEvent("auth:expired"));
}
function authHeaders() {
  const a = getAuth();
  return a ? { "Authorization": "Bearer " + a.token } : {};
}

async function readJsonResponse(response, fallbackMessage = "请求失败") {
  const text = await response.text();
  if (!text) return null;
  try {
    return JSON.parse(text);
  } catch {
    const looksLikeHtml = /^\s*(?:<!doctype|<html)/i.test(text);
    throw new Error(
      looksLikeHtml
        ? "当前页面连接到的是静态预览，无法使用登录和规划功能。请通过完整应用地址重新打开。"
        : fallbackMessage
    );
  }
}

async function loginApi(username, password) {
  let r;
  try {
    r = await fetch("/api/auth/login", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ username, password }),
    });
  } catch {
    throw new Error("暂时无法连接到登录服务，请确认完整应用已经启动。");
  }
  const d = await readJsonResponse(r, "登录服务返回了无法识别的响应");
  if (!r.ok) throw new Error(d.detail || "登录失败");
  return d;
}

async function registerApi(username, password) {
  let r;
  try {
    r = await fetch("/api/auth/register", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ username, password }),
    });
  } catch {
    throw new Error("暂时无法连接到注册服务，请确认完整应用已经启动。");
  }
  const d = await readJsonResponse(r, "注册服务返回了无法识别的响应");
  if (!r.ok) throw new Error(d.detail || "注册失败");
  return d;
}

async function checkAuth() {
  const a = getAuth();
  if (!a) return null;
  try {
    const r = await fetch("/api/profile", { headers: authHeaders() });
    if (r.ok) return await r.json();
    if (r.status === 401) clearAuth();
    return null;
  } catch { return null; }
}

/* ── Planning SSE ─────────────────────────────────── */
async function streamPlan(body, callbacks, url = "/api/plan/stream") {
  const { onStage, onResult, onMissingFields, onWarning, onError, onAbort } = callbacks;
  const ctrl = new AbortController();
  if (onAbort) onAbort(() => ctrl.abort());

  try {
    const r = await fetch(url, {
      method: "POST",
      headers: { "Content-Type": "application/json", ...authHeaders() },
      body: JSON.stringify(body),
      signal: ctrl.signal,
    });
    if (!r.ok) {
      const d = await r.json().catch(() => ({}));
      const detail = d.detail;
      const msg = typeof detail === "string" ? detail : (Array.isArray(detail) ? detail.map(e => e.msg).join("; ") : "请求失败");
      onError && onError(msg);
      return;
    }

    const reader = r.body.getReader();
    const dec = new TextDecoder();
    let buf = "";

    while (true) {
      const { done, value } = await reader.read();
      if (done) break;
      buf += dec.decode(value, { stream: true });
      const parts = buf.split("\n\n");
      buf = parts.pop();
      for (const part of parts) {
        const line = part.replace(/^data: /, "").trim();
        if (!line) continue;
        try {
          const ev = JSON.parse(line);
          if (ev.type === "stage") {
            onStage && onStage(ev);
          } else if (ev.type === "result") {
            if (ev.success === false && ev.missing_fields?.length) {
              onMissingFields && onMissingFields(ev);
            } else {
              onResult && onResult(ev);
            }
          } else if (ev.type === "modification_warning") {
            onWarning && onWarning(ev);
          } else if (ev.type === "error") {
            onError && onError(ev.message || "规划出错");
          }
        } catch {}
      }
    }
  } catch (e) {
    if (e.name !== "AbortError") onError && onError(e.message || "网络错误");
  }
}

async function confirmModification(pending_id, parent_plan_id, callbacks) {
  return streamPlan(
    { pending_id, parent_plan_id },
    callbacks,
    "/api/plan/confirm_modification"
  );
}

/* ── Conversations / Agent Runtime ────────────────── */
async function apiJson(url, options = {}) {
  const r = await fetch(url, {
    ...options,
    headers: {
      ...(options.body ? { "Content-Type": "application/json" } : {}),
      ...authHeaders(),
      ...(options.headers || {}),
    },
  });
  const data = await readJsonResponse(r);
  if (!r.ok) throw new Error(
    typeof data?.detail === "string" ? data.detail : "请求失败"
  );
  return data;
}

function listConversations() {
  return apiJson("/api/conversations");
}
function createConversation(title = "") {
  return apiJson("/api/conversations", {
    method: "POST", body: JSON.stringify({ title }),
  });
}
function getConversationMessages(id, afterSequence = 0) {
  return apiJson(`/api/conversations/${id}/messages?after_sequence=${afterSequence}`);
}
function submitConversationMessage(id, content, context = {}) {
  return apiJson(`/api/conversations/${id}/messages`, {
    method: "POST",
    body: JSON.stringify({ content, ...context }),
  });
}
function getActivePlanningBrief(conversationId) {
  return apiJson(`/api/conversations/${conversationId}/planning-brief`);
}
function updatePlanningBrief(id, patch) {
  return apiJson(`/api/planning-briefs/${id}`, {
    method: "PATCH", body: JSON.stringify(patch),
  });
}
function submitPlanningBrief(id) {
  return apiJson(`/api/planning-briefs/${id}/submit`, { method: "POST" });
}
function discardPlanningBrief(id) {
  return apiJson(`/api/planning-briefs/${id}/discard`, { method: "POST" });
}
function listRuns(conversationId, activeOnly = false) {
  const query = new URLSearchParams();
  if (conversationId) query.set("conversation_id", conversationId);
  if (activeOnly) query.set("active_only", "true");
  return apiJson(`/api/runs?${query}`);
}
function createRuntimeRun(kind, conversationId, request, relatedItineraryId = null) {
  return apiJson("/api/runs", {
    method: "POST",
    body: JSON.stringify({
      kind,
      conversation_id: conversationId,
      request,
      related_itinerary_id: relatedItineraryId,
    }),
  });
}
function getRun(id) {
  return apiJson(`/api/runs/${id}`);
}
function getRunEvents(id, afterSequence = 0) {
  return apiJson(`/api/runs/${id}/events?after_seq=${afterSequence}`);
}
function cancelRuntimeRun(id) {
  return apiJson(`/api/runs/${id}/cancel`, { method: "POST" });
}
function retryRuntimeRun(id) {
  return apiJson(`/api/runs/${id}/retry`, { method: "POST" });
}
function resumeRuntimeRun(id, interactionId, value) {
  return apiJson(`/api/runs/${id}/resume`, {
    method: "POST",
    body: JSON.stringify({ interaction_id: interactionId, value }),
  });
}

async function streamRuntimeRun(runId, afterSeq, callbacks = {}) {
  const ctrl = new AbortController();
  callbacks.onAbort?.(() => ctrl.abort());
  try {
    const r = await fetch(`/api/runs/${runId}/stream?after_seq=${afterSeq || 0}`, {
      headers: authHeaders(),
      signal: ctrl.signal,
    });
    if (!r.ok) throw new Error("订阅任务失败");
    const reader = r.body.getReader();
    const decoder = new TextDecoder();
    let buffer = "";
    while (true) {
      const { value, done } = await reader.read();
      if (done) break;
      buffer += decoder.decode(value, { stream: true });
      const frames = buffer.split("\n\n");
      buffer = frames.pop();
      for (const frame of frames) {
        let kind = "custom";
        let sequence = null;
        let payload = {};
        for (const line of frame.split("\n")) {
          if (line.startsWith("event:")) kind = line.slice(6).trim();
          else if (line.startsWith("id:")) sequence = Number(line.slice(3).trim());
          else if (line.startsWith("data:")) {
            try { payload = JSON.parse(line.slice(5).trim()); } catch {}
          }
        }
        callbacks.onEvent?.({ kind, sequence, payload });
      }
    }
    callbacks.onClose?.();
  } catch (error) {
    if (error.name !== "AbortError") callbacks.onError?.(error);
  }
  return () => ctrl.abort();
}

/* ── History ──────────────────────────────────────── */
async function getHistory() {
  const r = await fetch("/api/history", { headers: authHeaders() });
  if (!r.ok) return [];
  return r.json();
}

async function getHistoryItem(id) {
  const r = await fetch("/api/history/" + id, { headers: authHeaders() });
  if (!r.ok) return null;
  return r.json();
}

/* ── Profile ──────────────────────────────────────── */
async function getProfile() {
  const r = await fetch("/api/profile", { headers: authHeaders() });
  if (!r.ok) return null;
  return r.json();
}

async function saveProfile(data) {
  const r = await fetch("/api/profile", {
    method: "PUT",
    headers: { "Content-Type": "application/json", ...authHeaders() },
    body: JSON.stringify(data),
  });
  if (!r.ok) throw new Error("保存失败");
  return r.json();
}

/* ── Config / Amap ────────────────────────────────── */
let _amapConfig = null;
let _amapPromise = null;

async function getConfig() {
  if (_amapConfig) return _amapConfig;
  try {
    _amapConfig = await fetch("/api/config").then(r => r.json());
  } catch {
    _amapConfig = { amap_js_key: "", amap_js_security_code: "" };
  }
  return _amapConfig;
}

function ensureAMap() {
  if (_amapPromise) return _amapPromise;
  _amapPromise = (async () => {
    const cfg = await getConfig();
    if (!cfg.amap_js_key) throw new Error("未配置 AMAP_JS_KEY");
    if (cfg.amap_js_security_code)
      window._AMapSecurityConfig = { securityJsCode: cfg.amap_js_security_code };
    if (!window.AMapLoader) {
      await new Promise((res, rej) => {
        const s = document.createElement("script");
        s.src = "https://webapi.amap.com/loader.js";
        s.onload = res; s.onerror = rej;
        document.head.appendChild(s);
      });
    }
    return window.AMapLoader.load({
      key: cfg.amap_js_key, version: "2.0",
      plugins: ["AMap.Driving", "AMap.Walking", "AMap.InfoWindow"],
    });
  })();
  return _amapPromise;
}

// 一个地图容器对应一个 Map 实例（切换天数时复用，避免重复创建）
const _amapByContainer = new WeakMap();

function cssColor(name, fallback) {
  // AMap 折线/标记不认 CSS 变量，取计算后的真实色值
  const v = getComputedStyle(document.documentElement).getPropertyValue(name).trim();
  return v || fallback;
}

// 驾车路线规划：成功则在地图上画出真实道路路线，失败画虚线直连兜底。
// seq 防竞态：切换天数后旧 search 的迟到回调直接丢弃，避免旧路线画到新地图上。
function drawRealRoute(AMap, inst, path) {
  const seq = inst.seq;
  const accent = cssColor("--accent", "#b5491f");
  const fallbackLine = () => {
    inst.map.add(new AMap.Polyline({
      path, strokeColor: accent, strokeWeight: 3.5,
      strokeOpacity: 0.8, strokeStyle: "dashed", strokeDasharray: [6, 6], lineJoin: "round",
    }));
  };
  if (!inst.driving) {
    try {
      inst.driving = new AMap.Driving({
        map: inst.map, hideMarkers: true, autoFitView: false,
        policy: AMap.DrivingPolicy ? AMap.DrivingPolicy.LEAST_TIME : undefined,
      });
    } catch { fallbackLine(); return; }
  }
  inst.driving.search(
    path[0], path[path.length - 1],
    { waypoints: path.slice(1, -1) },
    (status) => {
      if (seq !== inst.seq) { if (inst.driving) inst.driving.clear(); return; }
      if (status !== "complete") fallbackLine();
      inst.map.setFitView(null, false, [48, 48, 48, 48]);
    },
  );
}

function _esc(s) {
  return String(s == null ? "" : s).replace(/[&<>"]/g, c => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c]));
}

// 标记点击弹窗：图片 + 名称 + 评分/价格/时段 + 地址 + 推荐理由
function markerInfoHtml(pt) {
  const it = pt.info || {};
  const isMeal = pt.kind === "meal";
  const parts = [`<div style="width:252px;color:#2a221a;line-height:1.5">`];
  if (it.photo) {
    parts.push(`<div style="width:100%;height:120px;border-radius:8px;background:url('${_esc(it.photo)}') center/cover;margin-bottom:8px"></div>`);
  }
  parts.push(`<div style="font-size:14.5px;font-weight:800;margin-bottom:5px">${_esc(pt.name)}</div>`);
  const meta = [];
  if (isMeal) meta.push(`🍽 ${it.type === "lunch" ? "午餐" : "晚餐"}`);
  if (it.rating) meta.push(`⭐ ${_esc(it.rating)}`);
  if (isMeal && it.cost) meta.push(`💰 ¥${_esc(it.cost)}/人`);
  if (!isMeal && it.start && it.end) meta.push(`🕒 ${_esc(it.start)}–${_esc(it.end)}`);
  if (meta.length) parts.push(`<div style="font-size:12.5px;color:#6b5e4e;margin-bottom:4px">${meta.join("&nbsp;&nbsp;")}</div>`);
  if (!isMeal && it.open) parts.push(`<div style="font-size:12px;color:#6b5e4e;margin-bottom:4px">开放时间：${_esc(it.open)}</div>`);
  if (it.addr) parts.push(`<div style="font-size:12px;color:#6b5e4e;margin-bottom:6px">📍 ${_esc(it.addr)}</div>`);
  if (it.reason) {
    parts.push(`<div style="font-size:12px;line-height:1.7;background:#f4efe3;border-radius:8px;padding:8px 10px;color:#4a4036">${_esc(it.reason)}</div>`);
  }
  parts.push(`</div>`);
  return parts.join("");
}

async function initAmapForDay(container, points) {
  // container: DOM element; points: [{lat, lng, kind, label, name, info}]
  let AMap;
  try { AMap = await ensureAMap(); } catch { return false; }
  const pts = (points || []).filter(p => p.lat && p.lng);
  if (!pts.length || !container || !container.isConnected) return false;

  try {
    let inst = _amapByContainer.get(container);
    if (!inst) {
      inst = {
        map: new AMap.Map(container, { zoom: 13, viewMode: "2D" }),
        infoWindow: new AMap.InfoWindow({ offset: new AMap.Pixel(0, -34), autoMove: true }),
        driving: null,
        seq: 0,
      };
      _amapByContainer.set(container, inst);
    }
    inst.seq += 1;
    const { map, infoWindow } = inst;
    if (inst.driving) inst.driving.clear();
    map.clearMap();
    infoWindow.close();

    const accent = cssColor("--accent", "#b5491f");
    const second = cssColor("--second", "#3f5d3a");
    const path = [];
    let spotNo = 0;  // 景点单独编号，餐厅不占号
    pts.forEach((pt, i) => {
      const pos = [pt.lng, pt.lat];
      const isMeal = pt.kind === "meal";
      if (!isMeal) path.push(pos);  // 路线只连景点
      const content = `<div style="width:28px;height:28px;display:grid;place-items:center;
        border-radius:${isMeal ? "7px" : "50%"};
        background:${isMeal ? second : accent};
        color:#fdfaf2;font-size:${isMeal ? "14px" : "12.5px"};font-weight:800;border:2px solid #fff;
        box-shadow:0 2px 8px rgba(0,0,0,.3);${isMeal ? "transform:rotate(45deg);" : ""}">
        <span style="${isMeal ? "transform:rotate(-45deg);" : ""}">${isMeal ? "🍜" : ++spotNo}</span></div>`;
      const marker = new AMap.Marker({ position: pos, content, offset: new AMap.Pixel(-14, -14), zIndex: 100 + i });
      marker.on("click", () => {
        infoWindow.setContent(markerInfoHtml(pt));
        infoWindow.open(map, pos);
      });
      map.add(marker);
    });

    map.setFitView(null, false, [48, 48, 48, 48]);
    if (path.length >= 2) drawRealRoute(AMap, inst, path);
    return true;
  } catch { return false; }
}

function destroyAmap(container) {
  const inst = container && _amapByContainer.get(container);
  if (!inst) return;
  try { inst.map.destroy(); } catch {}
  _amapByContainer.delete(container);
}

/* ── Route ops ────────────────────────────────────── */
async function optimizeDay(plan_id, day) {
  const r = await fetch("/api/plan/optimize_day", {
    method: "POST",
    headers: { "Content-Type": "application/json", ...authHeaders() },
    body: JSON.stringify({ plan_id, day }),
  });
  if (!r.ok) { const d = await r.json().catch(() => ({})); throw new Error(d.detail || "优化失败"); }
  return r.json();
}

async function revertDay(plan_id, day, original_timeline) {
  const r = await fetch("/api/plan/revert_day", {
    method: "POST",
    headers: { "Content-Type": "application/json", ...authHeaders() },
    body: JSON.stringify({ plan_id, day, original_timeline }),
  });
  if (!r.ok) { const d = await r.json().catch(() => ({})); throw new Error(d.detail || "回退失败"); }
  return r.json();
}

/* ── 手动编辑 ─────────────────────────────────────── */
async function searchPoi(city, kw, kind = "attraction") {
  const qs = new URLSearchParams({ city, kw, kind });
  const r = await fetch(`/api/poi/search?${qs}`, { headers: authHeaders() });
  if (!r.ok) { const d = await r.json().catch(() => ({})); throw new Error(d.detail || "搜索失败"); }
  return (await r.json()).results || [];
}

async function saveTimeline(plan_id, days) {
  const r = await fetch(`/api/plan/${encodeURIComponent(plan_id)}/timeline`, {
    method: "PUT",
    headers: { "Content-Type": "application/json", ...authHeaders() },
    body: JSON.stringify({ days }),
  });
  if (!r.ok) { const d = await r.json().catch(() => ({})); throw new Error(d.detail || "保存失败"); }
  return r.json();
}

async function searchNearby(lat, lng, type, radius = 1500) {
  const qs = new URLSearchParams({ lat, lng, type, radius });
  const r = await fetch(`/api/poi/nearby?${qs}`, { headers: authHeaders() });
  if (!r.ok) { const d = await r.json().catch(() => ({})); throw new Error(d.detail || "搜索失败"); }
  return (await r.json()).results || [];
}

async function savePlanMetadata(plan_id, data) {
  const r = await fetch(`/api/plan/${encodeURIComponent(plan_id)}/metadata`, {
    method: "PUT",
    headers: { "Content-Type": "application/json", ...authHeaders() },
    body: JSON.stringify(data),
  });
  if (!r.ok) { const d = await r.json().catch(() => ({})); throw new Error(d.detail || "保存失败"); }
  return r.json();
}

async function drawNavPairRoute(container, from, to) {
  let AMap;
  try { AMap = await ensureAMap(); } catch { return false; }
  const inst = _amapByContainer.get(container);
  if (!inst) return false;
  inst.seq += 1;
  const seq = inst.seq;
  if (inst.driving) inst.driving.clear();
  // 清除上一次的步行折线
  if (inst.walkPolyline) { inst.map.remove(inst.walkPolyline); inst.walkPolyline = null; }

  const origin = [from.lng, from.lat];
  const dest = [to.lng, to.lat];
  const accent = cssColor("--accent", "#b5491f");

  const drawLine = (coords) => {
    if (seq !== inst.seq) return;
    if (inst.walkPolyline) { inst.map.remove(inst.walkPolyline); inst.walkPolyline = null; }
    const path = coords.length >= 2 ? coords : [origin, dest];
    const isFallback = coords.length < 2;
    inst.walkPolyline = new AMap.Polyline({
      path,
      strokeColor: accent,
      strokeWeight: isFallback ? 3 : 4,
      strokeOpacity: 0.9,
      strokeStyle: isFallback ? "dashed" : "solid",
      strokeDasharray: isFallback ? [6, 6] : undefined,
      lineJoin: "round", lineCap: "round",
    });
    inst.map.add(inst.walkPolyline);
    inst.map.setFitView(null, false, [48, 48, 48, 48]);
  };

  // 调用后端步行路线接口（高德 REST API，不依赖 JS SDK 权限）
  try {
    const params = new URLSearchParams({
      origin_lng: from.lng, origin_lat: from.lat,
      dest_lng: to.lng, dest_lat: to.lat,
    });
    const r = await fetch(`/api/route/walking?${params}`, { headers: authHeaders() });
    if (seq !== inst.seq) return true;
    if (r.ok) {
      const { coords } = await r.json();
      drawLine(coords || []);
    } else {
      drawLine([]);
    }
  } catch {
    if (seq === inst.seq) drawLine([]);
  }
  return true;
}

async function restoreFullRoute(container, mapPoints) {
  let AMap;
  try { AMap = await ensureAMap(); } catch { return false; }
  const inst = _amapByContainer.get(container);
  if (!inst) return false;
  inst.seq += 1;
  if (inst.driving) inst.driving.clear();
  if (inst.walking) inst.walking.clear();
  if (inst.walkPolyline) { inst.map.remove(inst.walkPolyline); inst.walkPolyline = null; }
  const path = (mapPoints || [])
    .filter(p => p.kind !== "meal" && p.lat && p.lng)
    .map(p => [p.lng, p.lat]);
  if (path.length >= 2) drawRealRoute(AMap, inst, path);
  return true;
}

/* ── Plan data adapter ────────────────────────────── */
const WEATHER_ICON_MAP = {
  "晴": "☀️", "少云": "🌤", "晴间多云": "⛅", "多云": "☁️",
  "阴": "🌫", "有风": "💨", "平静": "🌬",
  "浮尘": "😶‍🌫️", "扬沙": "🌬", "强风": "💨", "飓风": "🌀",
  "雷阵雨": "⛈", "雷阵雨并伴有冰雹": "⛈", "小雨": "🌦",
  "中雨": "🌧", "大雨": "🌧", "暴雨": "⛈", "大暴雨": "⛈",
  "特大暴雨": "⛈", "阵雨": "🌦", "冻雨": "🌧", "小雪": "🌨",
  "中雪": "❄️", "大雪": "❄️", "暴雪": "❄️", "阵雪": "🌨",
  "雨夹雪": "🌨", "霾": "😶‍🌫️", "雾": "🌫",
};

function weatherIcon(text) {
  if (!text) return "🌤";
  for (const [k, v] of Object.entries(WEATHER_ICON_MAP)) {
    if (text.includes(k)) return v;
  }
  return "🌤";
}

// 将后端 weather_forecast 数组转为设计所需格式
function adaptWeather(forecast, startDate, daysCount) {
  if (!forecast || !forecast.length) return [];
  const weekdays = ["日", "一", "二", "三", "四", "五", "六"];
  return forecast.slice(0, daysCount).map((w, i) => {
    let dayLabel = `Day ${i + 1}`;
    if (startDate) {
      const d = new Date(startDate);
      d.setDate(d.getDate() + i);
      dayLabel = `${d.getMonth() + 1}.${String(d.getDate()).padStart(2, "0")} 周${weekdays[d.getDay()]}`;
    }
    const text = w.day_weather || w.dayweather || w.weather || "晴";
    const hi = w.day_temp || w.daytemp || w.temperature || "—";
    const lo = w.night_temp || w.nighttemp || "—";
    return { day: `Day ${i + 1} · ${dayLabel.split(" ")[1] || ""}`, icon: weatherIcon(text), text, hi, lo };
  });
}

// 把后端 location {lat, lng} 批量映射到 SVG 坐标 (0–100)
function projectPoints(timeline) {
  const locs = timeline.filter(it => it.location?.lat && it.location?.lng);
  if (!locs.length) return {};
  const lats = locs.map(it => it.location.lat);
  const lngs = locs.map(it => it.location.lng);
  const minLat = Math.min(...lats), maxLat = Math.max(...lats);
  const minLng = Math.min(...lngs), maxLng = Math.max(...lngs);
  const rangeX = maxLng - minLng || 0.01;
  const rangeY = maxLat - minLat || 0.01;
  const map = {};
  locs.forEach(it => {
    const name = it.name;
    map[name] = {
      x: 10 + ((it.location.lng - minLng) / rangeX) * 80,
      y: 85 - ((it.location.lat - minLat) / rangeY) * 70,
      lat: it.location.lat,
      lng: it.location.lng,
      kind: it.type === "attraction" ? "attraction" : "meal",
      label: name.length > 6 ? name.slice(0, 6) + "…" : name,
    };
  });
  return map;
}

// 将后端 final_plan 转换为 UI 所需格式
function adaptPlan(backendPlan, username) {
  const dest = backendPlan.destination || "旅行";
  const prefs = backendPlan.preferences || {};
  // preferences 字段可能是字符串（"历史、古迹"）或数组，统一转数组
  // 同时过滤掉 LLM 偶尔吐出的占位垃圾值（"null"/"无" 等），避免污染标题与 badge
  const JUNK_PREF = new Set(["null", "undefined", "none", "无", "暂无", "没有", "不限"]);
  const toArr = (v) => !v ? [] : (Array.isArray(v) ? v : String(v).split(/[，、,]+/))
    .map(s => String(s).trim())
    .filter(s => s && !JUNK_PREF.has(s.toLowerCase()));
  const badges = [
    ...toArr(prefs.attraction).slice(0, 2),
    ...toArr(prefs.food).slice(0, 1),
    ...toArr(prefs.habit).slice(0, 1),
  ].filter(Boolean);

  // 封面图
  const encDest = encodeURIComponent(dest);
  const coverImg = `https://picsum.photos/seed/${encDest}/1200/500`;

  // 天气
  const weather = adaptWeather(
    backendPlan.weather_forecast,
    backendPlan.start_date,
    backendPlan.days_count
  );

  // 标题
  const dateRange = (() => {
    if (backendPlan.start_date && backendPlan.end_date) {
      const s = backendPlan.start_date.replace(/-/g, ".").slice(5);
      const e = backendPlan.end_date.replace(/-/g, ".").slice(5);
      const year = backendPlan.start_date.slice(0, 4);
      return `${year}.${s} — ${e}`;
    }
    return "";
  })();
  const title = backendPlan.days_count
    ? `${dest} · ${backendPlan.days_count}日游`
    : `${dest} · 行程`;

  // 各天
  const weekdays = ["日", "一", "二", "三", "四", "五", "六"];
  const days = (backendPlan.days || []).map((d, i) => {
    const timeline = d.timeline || [];
    const projMap = projectPoints(timeline);

    const items = timeline.map(it => {
      const base = {
        dist: it.dist_from_prev_km != null ? it.dist_from_prev_km : null,
      };
      if (it.type === "attraction") {
        return {
          ...base,
          type: "attraction",
          name: it.name,
          start: it.start_time,
          end: it.end_time,
          period: it.period,
          rating: it.rating,
          open: it.open_time,
          photo: it.photo || null,
          note: it.tip || null,  // spot_tips Agent 生成的游玩注意事项
          location: it.location || null,
          address: it.address || null,
          tel: it.tel || null,
          cost: it.cost || null,
        };
      } else {
        // lunch / dinner
        return {
          ...base,
          type: it.type,
          name: it.name,
          rating: it.rating,
          cost: it.cost,
          addr: it.address,
          reason: it.reason,
          no_restaurant: it.no_restaurant || !it.name,
          photo: it.photo || null,
          location: it.location || null,
          tel: it.tel || null,
          open: it.open_time || null,
          category: it.category || null,
        };
      }
    });

    // 地图点（info 供高德地图标记弹窗展示详情）
    const mapPoints = timeline
      .filter(it => it.name && projMap[it.name])
      .map(it => ({
        ...projMap[it.name],
        name: it.name,
        info: {
          type: it.type,
          rating: it.rating,
          open: it.open_time,
          start: it.start_time,
          end: it.end_time,
          cost: it.cost,
          addr: it.address,
          reason: it.reason,
          photo: it.photo || null,
        },
      }));

    let dateLabel = d.date || `Day ${i + 1}`;
    if (backendPlan.start_date) {
      const dt = new Date(backendPlan.start_date);
      dt.setDate(dt.getDate() + i);
      dateLabel = `${dt.getMonth() + 1 < 10 ? "0" : ""}${dt.getMonth() + 1}.${String(dt.getDate()).padStart(2, "0")} 周${weekdays[dt.getDay()]}`;
    }

    const dayThemes = backendPlan.day_themes || {};
    return {
      date: dateLabel,
      theme: dayThemes[String(d.day || i + 1)] || d.theme || `Day ${i + 1}`,
      items,
      mapPoints,
    };
  });

  // 途途小贴士：天气说明 + 全部出行提醒（reviewer issues）合并为一组提示
  const tips = [
    ...(backendPlan.weather_note ? [backendPlan.weather_note] : []),
    ...(backendPlan.route_issues || []),
  ];

  return {
    _raw: backendPlan,  // 原始 plan：路线优化/回退时按天替换 timeline 后重新 adapt
    plan_id: backendPlan.plan_id,
    title,
    destination: dest,
    date_range: dateRange,
    badges,
    cover_seed: encDest,
    cover_img: coverImg,
    weather,
    days,
    tips,
    logs: backendPlan.history || [],
    username: username || "旅行者",
    candidate_spots: backendPlan.candidate_spots || [],
    hotel: backendPlan.hotel || "",
    notes: backendPlan.notes || "",
  };
}

Object.assign(window, {
  getAuth, setAuth, clearAuth, authHeaders,
  loginApi, registerApi, checkAuth,
  streamPlan, confirmModification,
  getHistory, getHistoryItem,
  getProfile, saveProfile,
  getConfig, ensureAMap, initAmapForDay, destroyAmap,
  optimizeDay, revertDay,
  searchPoi, saveTimeline,
  searchNearby, savePlanMetadata,
  drawNavPairRoute, restoreFullRoute,
  adaptPlan,
});
