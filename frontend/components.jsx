// components.jsx — 卡片 / 地图 / 旅程加载动画

/* ── 旅程加载动画 ─────────────────────────────── */
// 旅程站点：后端多个节点可映射到同一站（NODE_TO_STEP），
// planner⇄reviewer / planner⇄time_check 多轮循环时小人只前进不后退，
// 轮次细节由实时文案（stage label）展示。
const JOURNEY_STEPS = [
  { key: "intent",            label: "理解出行意图",       detail: "目的地 / 日期 / 偏好 · 查询天气预报" },
  { key: "query_rewrite",     label: "结合画像优化查询",   detail: "个性化改写中" },
  { key: "attraction_search", label: "景点 Agent 检索",    detail: "搜索景点池" },
  { key: "plan_review",       label: "规划 ⇄ 评审行程",    detail: "多轮打磨逐日时刻表" },
  { key: "time_check",        label: "核查开放时间",        detail: "逐景点核对营业时段" },
  { key: "meal",              label: "推荐沿线餐厅",        detail: "搜店 · 逐天挑选" },
  { key: "finalize",          label: "生成最终行程",         detail: "即将完成…" },
];
// 后端节点名 → 旅程站点 key
const NODE_TO_STEP = {
  intent:            "intent",
  query_rewrite:     "query_rewrite",
  attraction_search: "attraction_search",
  planner:           "plan_review",
  reviewer:          "plan_review",
  time_check:        "time_check",
  meal_search:       "meal",
  meal_recommend:    "meal",
  spot_tips:         "finalize",
  finalize:          "finalize",
};
Object.assign(window, { JOURNEY_STEPS, NODE_TO_STEP });

function JourneyLoading({ steps, activeNode, doneNodes }) {
  const pathRef = React.useRef(null);
  const [pos, setPos] = React.useState({ x: 60, y: 150 });
  const [waypoints, setWaypoints] = React.useState([]);
  const N = steps.length;

  const doneSet = new Set(doneNodes || []);
  const activeIdx = steps.findIndex(s => s.key === activeNode);
  const progressFrac = activeIdx < 0 ? 0 : (activeIdx + 0.5) / N;

  React.useEffect(() => {
    const p = pathRef.current;
    if (!p) return;
    const L = p.getTotalLength();
    const wps = steps.map((_, i) => {
      const pt = p.getPointAtLength((L * (i + 0.5)) / N);
      return { x: pt.x, y: pt.y };
    });
    setWaypoints(wps);
  }, [N]);

  React.useEffect(() => {
    const p = pathRef.current;
    if (!p) return;
    const L = p.getTotalLength();
    const pt = p.getPointAtLength(L * Math.min(progressFrac, 0.995));
    setPos({ x: pt.x, y: pt.y });
  }, [progressFrac]);

  return (
    <div className="journey-scene">
      <svg viewBox="0 0 880 220" preserveAspectRatio="xMidYMid meet">
        <path d="M0 168 L90 110 L150 150 L230 86 L320 158 L400 122 L470 160 L560 100 L650 150 L730 116 L810 156 L880 130 L880 220 L0 220 Z"
          fill="var(--bg-deep)" />
        <path d="M0 190 Q220 158 440 178 T880 168 L880 220 L0 220 Z" fill="var(--map-park)" opacity=".8" />
        <circle cx="790" cy="52" r="20" fill="var(--gold)" opacity=".75" />
        <g transform="translate(36, 132)">
          <line x1="0" y1="0" x2="0" y2="34" stroke="var(--ink-3)" strokeWidth="2.5" strokeLinecap="round" />
          <path d="M1 1 l22 6 -22 6 z" fill="var(--ink-3)" />
        </g>
        <g transform="translate(842, 118)">
          <line x1="0" y1="0" x2="0" y2="36" stroke="var(--accent)" strokeWidth="2.5" strokeLinecap="round" />
          <path d="M1 1 l24 7 -24 7 z" fill="var(--accent)" />
        </g>
        <path
          ref={pathRef}
          d="M40 168 C 160 130, 230 196, 350 168 S 560 118, 660 156 S 800 162, 842 152"
          fill="none" stroke="var(--ink-4)" strokeWidth="2.5"
          strokeDasharray="2 9" strokeLinecap="round" opacity=".8"
        />
        {waypoints.map((wp, i) => {
          const isDone = doneSet.has(steps[i].key);
          const isActive = steps[i].key === activeNode;
          const state = isDone ? "done" : isActive ? "active" : "todo";
          return (
            <g key={i} transform={`translate(${wp.x}, ${wp.y})`}>
              <circle r={state === "todo" ? 4.5 : 6.5}
                fill={state === "done" ? "var(--accent)" : "var(--card)"}
                stroke={state === "todo" ? "var(--ink-4)" : "var(--accent)"}
                strokeWidth="2.5"
                style={{ transition: "all .4s" }} />
              {state === "done" && (
                <path d="M-2.6 0 l1.8 2.2 3.4 -4.4" stroke="var(--accent-ink)" strokeWidth="1.8" fill="none" strokeLinecap="round" />
              )}
            </g>
          );
        })}
      </svg>
      <div
        style={{
          position: "absolute",
          left: `${(pos.x / 880) * 100}%`,
          top: `${(pos.y / 220) * 100}%`,
          transform: "translate(-50%, -94%)",
          transition: "left 1.1s cubic-bezier(.45,.05,.4,1), top 1.1s cubic-bezier(.45,.05,.4,1)",
          width: "8.5%",
          minWidth: 58,
        }}
      >
        <Mascot size={64} pose={doneNodes && doneNodes.length >= N - 1 ? "cheer" : "walk"} style={{ width: "100%", height: "auto" }} />
      </div>
    </div>
  );
}

/* ── 地图面板 ──────────────────────────────────── */
// SVG 示意地图：高德 JS 地图加载前的占位，以及未配置 AMAP_JS_KEY / 加载失败时的降级兜底
function DayMap({ mapPoints, dayKey }) {
  const pts = mapPoints || [];
  const poly = pts.map((p) => `${p.x},${p.y}`).join(" ");
  // 景点单独编号，餐厅不占号
  let spotNo = 0;
  const spotNums = pts.map(p => (p.kind === "meal" ? null : ++spotNo));

  return (
    <div className="map-canvas">
      <svg viewBox="0 0 100 100" preserveAspectRatio="xMidYMid slice" key={dayKey}>
        <g stroke="var(--line-2)" strokeWidth=".35">
          {[15, 30, 45, 60, 75, 90].map((v) => (
            <React.Fragment key={v}>
              <line x1={v + 4} y1="-5" x2={v - 8} y2="105" />
              <line x1="-5" y1={v} x2="105" y2={v - 6} />
            </React.Fragment>
          ))}
        </g>
        <path d="M-5 84 Q 24 72 46 84 T 105 80 L 105 105 L -5 105 Z" fill="var(--map-water)" />
        <path d="M58 -5 q 10 18 -2 32 q -8 11 2 22" fill="none" stroke="var(--map-water)" strokeWidth="5" strokeLinecap="round" opacity=".8" />
        <ellipse cx="22" cy="22" rx="16" ry="11" fill="var(--map-park)" />
        <ellipse cx="84" cy="38" rx="13" ry="9" fill="var(--map-park)" />
        <ellipse cx="44" cy="62" rx="9" ry="6" fill="var(--map-park)" opacity=".8" />
        {poly && (
          <polyline
            points={poly} fill="none"
            stroke="var(--accent)" strokeWidth=".9"
            strokeDasharray="2 1.9" strokeLinecap="round" strokeLinejoin="round"
            style={{ animation: "routeDash 30s linear infinite" }}
          />
        )}
        <style>{`@keyframes routeDash { to { stroke-dashoffset: -92; } }`}</style>
        {pts.map((p, i) => (
          <g key={`${dayKey}-${i}`} className="map-pin-pop" style={{ "--pin-delay": `${i * 0.12 + 0.1}s`, transformOrigin: `${p.x}px ${p.y}px` }}>
            {p.kind === "meal" ? (
              <g>
                <rect x={p.x - 2.6} y={p.y - 2.6} width="5.2" height="5.2" rx="1.2"
                  fill="var(--second)" transform={`rotate(45 ${p.x} ${p.y})`} />
                <circle cx={p.x} cy={p.y} r=".9" fill="var(--card)" />
              </g>
            ) : (
              <g>
                <circle cx={p.x} cy={p.y} r="3.4" fill="var(--accent)" />
                <text x={p.x} y={p.y + 1.6} textAnchor="middle" fontSize="4.2" fontWeight="800" fill="var(--accent-ink)" fontFamily="var(--font-body)">{spotNums[i]}</text>
              </g>
            )}
            <text className="map-pin-label" x={p.x} y={p.y - 5} textAnchor="middle" style={{ fontSize: "3.4px" }}>{p.label}</text>
          </g>
        ))}
      </svg>
    </div>
  );
}

function MapPanel({ day, dayIdx, navPair, onNavClear }) {
  const amapRef = React.useRef(null);
  // null=尝试加载中（显示 SVG 占位） true=高德地图就绪 false=降级 SVG
  const [amapReady, setAmapReady] = React.useState(null);
  const hasGeo = (day.mapPoints || []).some(p => p.lat && p.lng);

  // 点位签名：优化路线后同一天的点位顺序变化时也要重画地图
  const ptsSig = (day.mapPoints || []).map(p => p.name).join("|");

  React.useEffect(() => {
    if (!hasGeo) { setAmapReady(false); return; }
    let alive = true;
    initAmapForDay(amapRef.current, day.mapPoints).then(ok => { if (alive) setAmapReady(ok); });
    return () => { alive = false; };
  }, [dayIdx, hasGeo, ptsSig]);

  // 导航对 / 恢复全日路线
  React.useEffect(() => {
    if (amapReady !== true) return;
    if (navPair) {
      drawNavPairRoute(amapRef.current, navPair.from, navPair.to);
    } else {
      restoreFullRoute(amapRef.current, day.mapPoints);
    }
  }, [navPair, amapReady]); // eslint-disable-line

  // 组件卸载时销毁地图实例
  React.useEffect(() => () => destroyAmap(amapRef.current), []);

  return (
    <div className="map-frame">
      <div className="map-head">
        <span className="mh-title">Day {dayIdx + 1} 路线图</span>
        {navPair && onNavClear && (
          <button className="mh-nav-clear" onClick={onNavClear}>✕ 退出导航</button>
        )}
        {amapReady !== true && !navPair && <span className="mh-note">地点示意 · 相对位置</span>}
      </div>
      <div className="map-stage">
        <DayMap mapPoints={day.mapPoints} dayKey={dayIdx} />
        {hasGeo && (
          <div
            ref={amapRef}
            className="amap-host"
            style={{
              position: "absolute", inset: 0,
              opacity: amapReady === true ? 1 : 0,
              pointerEvents: amapReady === true ? "auto" : "none",
              transition: "opacity .4s ease",
            }}
          />
        )}
      </div>
      <div className="map-legend">
        <span><span className="legend-dot" style={{ background: "var(--accent)" }}></span>景点</span>
        <span><span className="legend-dot" style={{ background: "var(--second)", borderRadius: 2 }}></span>餐厅</span>
        {amapReady !== true && <span style={{ marginLeft: "auto" }}>虚线为景点游览顺序</span>}
      </div>
    </div>
  );
}

/* ── 时间轴卡片 ───────────────────────────────── */
function photoUrl(seed, w = 640, h = 440) {
  return `https://picsum.photos/seed/${encodeURIComponent(seed)}/${w}/${h}`;
}
Object.assign(window, { photoUrl });

function Thumb({ photo, seed, alt }) {
  const [err, setErr] = React.useState(false);
  const src = photo || (seed ? photoUrl(seed, 360, 280) : null);
  if (!src || err) return <div className="t-thumb ph" aria-label={alt}>◌</div>;
  return (
    <div className="t-thumb" style={{ backgroundImage: `url('${src}')` }} aria-label={alt}>
      <img src={src} alt="" style={{ display: "none" }} onError={() => setErr(true)} />
    </div>
  );
}

const PERIOD = {
  morning:   { label: "上午", cls: "morning" },
  afternoon: { label: "下午", cls: "afternoon" },
  evening:   { label: "夜间", cls: "evening" },
};

// 站点间通行标注：≤3km 按步行（约 4km/h）估时，更远建议乘车
function walkNote(dist) {
  if (dist == null || !(dist > 0)) return null;
  const d = Number(dist);
  if (d <= 3) return `步行 ${d} km · 约 ${Math.max(1, Math.round(d * 15))} 分钟`;
  return `相距 ${d} km · 建议乘车`;
}

function WalkIcon() {
  return (
    <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
      <path d="M13 4a2 2 0 1 0 0-.1M7 21l3-4.5L8 12l2.5-3 2.5 2 3 1" />
    </svg>
  );
}

function AttractionCard({ item, onNearby }) {
  const p = PERIOD[item.period] || PERIOD.morning;
  return (
    <div className="tl-node">
      <div className="t-card">
        <Thumb photo={item.photo} seed={item.seed} alt={item.name} />
        <div className="t-body">
          <div className="t-title">
            {item.name}
            <span className={`period-tag ${p.cls}`}>{p.label}</span>
          </div>
          <div className="t-meta">
            {item.start && <span>{item.start}{item.end ? ` – ${item.end}` : ""}</span>}
            {item.rating != null && <span className="star">★ {Number(item.rating).toFixed(1)}</span>}
            {item.cost && <span>💰 ¥{item.cost}/人</span>}
            {item.open && <span className="t-open">开放 {item.open}</span>}
          </div>
          {item.address && <div className="t-address">📍 {item.address}</div>}
          {item.tel && <div className="t-address">📞 {item.tel}</div>}
          {item.note && <div className="tip-box">💡 {item.note}</div>}
          {onNearby && item.location && (
            <button className="nearby-btn" onClick={() => onNearby(item)}>📍 周边搜索</button>
          )}
        </div>
      </div>
    </div>
  );
}

function MealCard({ item }) {
  const label = item.type === "lunch" ? "午餐" : "晚餐";
  if (item.no_restaurant) {
    return (
      <div className="tl-node is-meal">
        <div className="t-card meal-card">
          <div className="t-body">
            <div className="t-title"><span className="meal-flag">{label}</span>该时段附近暂无餐厅数据</div>
            <div className="t-note">建议出发前自行规划{label}，或让我换一片区域再找找。</div>
          </div>
        </div>
      </div>
    );
  }
  return (
    <div className="tl-node is-meal">
      <div className="t-card meal-card">
        <Thumb photo={item.photo} seed={item.seed} alt={item.name} />
        <div className="t-body">
          <div className="t-title">
            {item.name}
            <span className="meal-flag">{label}</span>
          </div>
          <div className="t-meta">
            {item.rating != null && <span className="star">★ {Number(item.rating).toFixed(1)}</span>}
            {item.cost && <span>¥{item.cost} /人</span>}
            {item.category && <span>{item.category}</span>}
            {item.addr && <span>{item.addr}</span>}
          </div>
          {item.open && <div className="t-address">🕐 {item.open}</div>}
          {item.tel && <div className="t-address">📞 {item.tel}</div>}
          {item.reason && <div className="reason-box">{item.reason}</div>}
        </div>
      </div>
    </div>
  );
}

// 导航行：夹在任意相邻两个 item 之间
function NavRow({ itemA, itemB, onNav, isActive }) {
  const hasCoords = itemA?.location?.lat && itemA?.location?.lng
    && itemB?.location?.lat && itemB?.location?.lng;
  if (!hasCoords) return null;
  const dist = itemB.dist;
  return (
    <div className="nav-row">
      <div className="tl-when nav-row-dist">{dist ? `${dist}km` : ""}</div>
      <div className="tl-spine nav-row-spine">
        <div className="tl-line" style={{ height: 8 }}></div>
        <div className={`nav-row-node${isActive ? " active" : ""}`}>🧭</div>
        <div className="tl-line" style={{ flex: 1 }}></div>
      </div>
      <div className="nav-row-content">
        <button
          className={`nav-row-btn${isActive ? " active" : ""}`}
          onClick={() => onNav({ from: itemA.location, to: itemB.location })}
        >🧭 导航</button>
        <span className="nav-row-label">{itemA.name} → {itemB.name}</span>
      </div>
    </div>
  );
}

// 时间轴：左侧时间槽 + 轴线，相邻两项之间插入导航行
function Timeline({ items, onNav, activeNavKey }) {
  return (
    <div className="timeline">
      {items.map((item, i) => {
        const isMeal = item.type !== "attraction";
        const prevItem = i > 0 ? items[i - 1] : null;
        const navKey = i > 0 ? String(i) : null;
        return (
          <React.Fragment key={i}>
            {i > 0 && onNav && (
              <NavRow
                itemA={prevItem}
                itemB={item}
                onNav={(pair) => onNav(activeNavKey === navKey ? null : navKey, pair)}
                isActive={activeNavKey === navKey}
              />
            )}
            <div className="tl-row">
              <div className="tl-when">{isMeal ? "" : (item.start || "")}</div>
              <div className="tl-spine tl-spine-dot"><span className={`tl-dot${isMeal ? " meal" : ""}`}></span></div>
              {isMeal
                ? <MealCard item={item} />
                : <AttractionCard item={item} onNearby={onNav ? (it) => onNav("nearby:" + i, null, it) : undefined} />
              }
            </div>
          </React.Fragment>
        );
      })}
    </div>
  );
}

/* ── 候选景点推荐横滚条 ──────────────────────────── */
function RecommendStrip({ candidates, editing }) {
  const [detail, setDetail] = React.useState(null);

  if (!candidates || !candidates.length) return null;
  return (
    <div className="recommend-strip">
      <div className="recommend-label">
        🗺 LLM 候选景点池{editing ? " · 拖入时间轴可替换景点" : ""}
      </div>
      <div className="recommend-scroll">
        {candidates.map((c, i) => (
          <div
            key={i}
            className={`rec-card${editing ? " draggable" : ""}${detail === c ? " rec-card-active" : ""}`}
            draggable={editing}
            onDragStart={editing ? (e) => {
              e.dataTransfer.setData("application/json", JSON.stringify(c));
              e.dataTransfer.effectAllowed = "copy";
            } : undefined}
            onClick={() => setDetail(detail === c ? null : c)}
          >
            <div
              className="rec-thumb"
              style={c.photo ? { backgroundImage: `url('${c.photo}')` } : undefined}
            />
            <div className="rec-name">{c.name}</div>
            <div className="rec-meta">
              {c.rating != null && <span>★ {Number(c.rating).toFixed(1)}</span>}
            </div>
          </div>
        ))}
      </div>
      {detail && (
        <div className="rec-detail-popup">
          <button className="rec-detail-close" onClick={() => setDetail(null)}>✕</button>
          {detail.photo && (
            <div className="rec-detail-photo" style={{ backgroundImage: `url('${detail.photo}')` }} />
          )}
          <div className="rec-detail-name">{detail.name}</div>
          <div className="rec-detail-rows">
            {detail.rating != null && (
              <div className="rec-detail-row">
                <span className="rec-detail-icon">★</span>
                <span>{Number(detail.rating).toFixed(1)} 分</span>
              </div>
            )}
            {detail.address && (
              <div className="rec-detail-row">
                <span className="rec-detail-icon">📍</span>
                <span>{detail.address}</span>
              </div>
            )}
            {detail.open_time && (
              <div className="rec-detail-row">
                <span className="rec-detail-icon">🕐</span>
                <span>{detail.open_time}</span>
              </div>
            )}
            {detail.cost && (
              <div className="rec-detail-row">
                <span className="rec-detail-icon">💰</span>
                <span>¥{detail.cost}/人</span>
              </div>
            )}
          </div>
        </div>
      )}
    </div>
  );
}

/* ── 周边搜索弹层 ────────────────────────────────── */
function NearbySearchModal({ location, name, onClose, onPickMeal }) {
  const [tab, setTab] = React.useState("attraction");
  const [radius, setRadius] = React.useState(1500);
  const [results, setResults] = React.useState(null);
  const [loading, setLoading] = React.useState(false);
  const [err, setErr] = React.useState("");

  const doSearch = async (t, r) => {
    setLoading(true); setErr(""); setResults(null);
    try {
      const res = await searchNearby(location.lat, location.lng, t === "attraction" ? "风景名胜" : "餐饮服务", r);
      setResults(res);
      if (!res.length) setErr("附近暂无数据，试试调大半径");
    } catch (e) { setErr(e.message || "搜索失败"); }
    finally { setLoading(false); }
  };

  React.useEffect(() => { doSearch(tab, radius); }, []); // eslint-disable-line

  const switchTab = (t) => { setTab(t); doSearch(t, radius); };
  const changeRadius = (r) => { setRadius(r); doSearch(tab, r); };

  return (
    <div className="modal-backdrop" onClick={(e) => e.target === e.currentTarget && onClose()}>
      <div className="modal-card nearby-modal">
        <button className="modal-close" onClick={onClose}>✕</button>
        <div className="modal-title">📍 {name} 周边</div>
        <div className="nearby-tabs">
          <button className={`nearby-tab${tab === "attraction" ? " active" : ""}`} onClick={() => switchTab("attraction")}>景点</button>
          <button className={`nearby-tab${tab === "restaurant" ? " active" : ""}`} onClick={() => switchTab("restaurant")}>餐厅</button>
        </div>
        <div className="nearby-radius-row">
          {[500, 1000, 1500, 3000].map(r => (
            <button key={r} className={`radius-btn${radius === r ? " active" : ""}`} onClick={() => changeRadius(r)}>{r}m</button>
          ))}
        </div>
        {loading && <div className="poi-search-err">搜索中…</div>}
        {err && <div className="poi-search-err">{err}</div>}
        <div className="nearby-results">
          {(results || []).map((p, i) => (
            <div key={i} className="nearby-result">
              <div className="nearby-result-name">{p.name}</div>
              <div className="nearby-result-meta">
                {p.rating != null && <span>★ {Number(p.rating).toFixed(1)}</span>}
                {p.distance != null && <span> · {p.distance}m</span>}
                {p.address && <span> · {p.address}</span>}
              </div>
              {tab === "restaurant" && onPickMeal && (
                <div className="nearby-meal-actions">
                  <button className="nearby-meal-btn" onClick={() => onPickMeal(p, "lunch")}>设为午餐</button>
                  <button className="nearby-meal-btn" onClick={() => onPickMeal(p, "dinner")}>设为晚餐</button>
                </div>
              )}
            </div>
          ))}
        </div>
      </div>
    </div>
  );
}

/* ── Sweep 评测侧栏 ───────────────────────────────── */
const GRADERS = [
  { key: "g1_closed_pool",           label: "G1 无幻觉" },
  { key: "g2_time_check",            label: "G2 时间核查" },
  { key: "g3_proximity",             label: "G3 地理跨度" },
  { key: "g4_structure",             label: "G4 结构合法" },
  { key: "g5_coverage",              label: "G5 覆盖完整" },
  { key: "g6_weather",               label: "G6 天气合规" },
  { key: "g7_convergence",           label: "G7 收敛" },
  { key: "g8_time_check_efficiency", label: "G8 TC效率" },
];

function SweepEvalPanel({ code, reviewRounds, timeCheckRounds, profileUpdate, dialogue, overallPass, elapsedS }) {
  const results = code?.results || {};
  return (
    <div className="sweep-eval-panel">
      <div className={`sweep-verdict ${overallPass ? "pass" : "fail"}`}>
        {overallPass ? "✅ 通过" : "❌ 未通过"}
        {elapsedS != null && <span className="sweep-elapsed">{elapsedS}s</span>}
      </div>

      <div className="sweep-section-title">代码打分</div>
      {GRADERS.map(({ key, label }) => {
        const r = results[key];
        if (!r) return null;
        const isNA = !r.passed && r.detail?.includes("跳过");
        return (
          <React.Fragment key={key}>
            <div className={`sweep-g-row ${isNA ? "na" : r.passed ? "pass" : "fail"}`}>
              <span>{isNA ? "—" : r.passed ? "✅" : "❌"}</span>
              <span>{label}</span>
            </div>
            {!r.passed && !isNA && <div className="sweep-g-detail">{r.detail}</div>}
          </React.Fragment>
        );
      })}

      <div className="sweep-section-title">流程</div>
      <div className="sweep-stat">评审：{reviewRounds} 轮</div>
      <div className="sweep-stat">time_check：{timeCheckRounds} 轮</div>

      {profileUpdate && !profileUpdate.error && (
        <>
          <div className="sweep-section-title">画像更新</div>
          {(profileUpdate.diff || []).length > 0
            ? profileUpdate.diff.map((d, i) => <div key={i} className="sweep-profile-row">{d}</div>)
            : <div className="sweep-profile-row sweep-na">无变更</div>}
          {(profileUpdate.change_log || []).length > 0 && (
            <details className="sweep-details">
              <summary>变更理由</summary>
              {profileUpdate.change_log.map((c, i) => <p key={i}>{c}</p>)}
            </details>
          )}
        </>
      )}

      {(dialogue || []).length > 0 && (
        <details className="sweep-details">
          <summary>📜 规划对话</summary>
          {dialogue.map((d, i) => <p key={i}>{d}</p>)}
        </details>
      )}
    </div>
  );
}

Object.assign(window, {
  JourneyLoading, DayMap, MapPanel, Timeline, NavRow, Thumb,
  RecommendStrip, NearbySearchModal,
  SweepEvalPanel, walkNote, WalkIcon,
});
