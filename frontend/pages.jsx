// pages.jsx — 三个页面 + Auth 模态框

/* ── Auth 模态框 ──────────────────────────────── */
function AuthModal({ onSuccess, onClose, reason }) {
  const [tab, setTab] = React.useState("login");
  const [username, setUsername] = React.useState("");
  const [password, setPassword] = React.useState("");
  const [err, setErr] = React.useState("");
  const [loading, setLoading] = React.useState(false);

  const submit = async () => {
    if (!username.trim() || !password.trim()) { setErr("请填写用户名和密码"); return; }
    setLoading(true); setErr("");
    try {
      let res;
      if (tab === "login") {
        res = await loginApi(username.trim(), password);
      } else {
        res = await registerApi(username.trim(), password);
        if (res.token) {
          // 注册成功后直接登录
        } else {
          // 注册成功但需要再登录
          res = await loginApi(username.trim(), password);
        }
      }
      setAuth(res.token, res.username || username.trim());
      onSuccess && onSuccess(res.username || username.trim());
    } catch (e) {
      setErr(e.message || "操作失败");
    } finally {
      setLoading(false);
    }
  };

  return (
    <div className="modal-backdrop" onClick={(e) => e.target === e.currentTarget && onClose && onClose()}>
      <div className="modal-card">
        <button className="modal-close" onClick={onClose}>✕</button>
        <div className="modal-title">途见 · AI 旅行规划</div>
        {reason && <div className="modal-sub">{reason}</div>}
        <div className="auth-tabs">
          <button className={`auth-tab ${tab === "login" ? "active" : ""}`} onClick={() => { setTab("login"); setErr(""); }}>登录</button>
          <button className={`auth-tab ${tab === "register" ? "active" : ""}`} onClick={() => { setTab("register"); setErr(""); }}>注册</button>
        </div>
        <div className="form-field">
          <label className="form-label">用户名</label>
          <input className="form-input" value={username} onChange={e => setUsername(e.target.value)}
            placeholder="输入用户名" autoFocus
            onKeyDown={e => e.key === "Enter" && submit()} />
        </div>
        <div className="form-field">
          <label className="form-label">密码</label>
          <input className="form-input" type="password" value={password} onChange={e => setPassword(e.target.value)}
            placeholder="输入密码"
            onKeyDown={e => e.key === "Enter" && submit()} />
        </div>
        <div className="form-error">{err}</div>
        <button className="form-submit" disabled={loading} onClick={submit}>
          {loading ? "处理中…" : tab === "login" ? "登录" : "注册并登录"}
        </button>
      </div>
    </div>
  );
}

/* ── 修改顾虑模态框 ───────────────────────────── */
function ConcernModal({ concern, onKeep, onConfirm }) {
  return (
    <div className="modal-backdrop">
      <div className="modal-card">
        <div className="modal-title">规划师有个顾虑</div>
        <div className="modal-sub">AI 在调整行程时发现了一个问题，请你决定如何处理：</div>
        <div className="concern-box">{concern}</div>
        <div className="concern-actions">
          <button className="keep-btn" onClick={onKeep}>放弃，保留原行程</button>
          <button className="confirm-btn" onClick={onConfirm}>确认，继续修改</button>
        </div>
      </div>
    </div>
  );
}

/* ── 主页（新建规划） ─────────────────────────── */
function PlanPage({ onRequestLogin, currentUsername, onPhaseChange, onPlanReady, modifyTrigger, onCancelModify }) {
  const [phase, setPhase] = React.useState("idle");

  React.useEffect(() => { onPhaseChange?.(phase); }, [phase]); // eslint-disable-line
  const [query, setQuery] = React.useState("");
  const [planId, setPlanId] = React.useState(null);
  const [logs, setLogs] = React.useState([]);
  const [activeNode, setActiveNode] = React.useState(null);
  const [doneNodes, setDoneNodes] = React.useState([]);
  const [stageLabel, setStageLabel] = React.useState("");
  const [missingFields, setMissingFields] = React.useState([]);
  const [threadId, setThreadId] = React.useState(null);
  const [concernModal, setConcernModal] = React.useState(null);
  const [pendingModState, setPendingModState] = React.useState(null);
  const [errMsg, setErrMsg] = React.useState("");
  const abortRef = React.useRef(null);
  // 旅程已走到的最远站点下标：planner⇄reviewer / planner⇄time_check 循环时只前进不后退
  const maxStepRef = React.useRef(-1);

  React.useEffect(() => () => abortRef.current && abortRef.current(), []);

  // 由 App 传入修改触发器，在挂载时（planKey bump 后）立即执行修改流
  React.useEffect(() => {
    if (modifyTrigger) {
      doStream({ query: modifyTrigger.query, plan_id: modifyTrigger.planId, modification_notes: modifyTrigger.query });
    }
  }, []); // eslint-disable-line

  const handleStage = (ev) => {
    setLogs(prev => [...prev, ev.label || ev.node]);
    setStageLabel(ev.label || "");
    const key = NODE_TO_STEP[ev.node] || ev.node;
    const idx = JOURNEY_STEPS.findIndex(s => s.key === key);
    if (idx < 0 || idx <= maxStepRef.current) return; // 未知节点或回头路（多轮循环）不动小人
    maxStepRef.current = idx;
    setActiveNode(key);
    setDoneNodes(JOURNEY_STEPS.slice(0, idx).map(s => s.key));
  };

  const resetJourney = () => {
    maxStepRef.current = -1;
    setActiveNode(null);
    setDoneNodes([]);
    setStageLabel("");
  };

  const doStream = (body) => {
    setPhase("loading");
    resetJourney();
    setErrMsg("");

    streamPlan(body, {
      onAbort: (fn) => { abortRef.current = fn; },
      onStage: handleStage,
      onResult: (ev) => {
        const adapted = adaptPlan(ev.plan, currentUsername);
        adapted.logs = ev.history || logs;
        setPlanId(ev.plan_id);
        setDoneNodes(JOURNEY_STEPS.map(s => s.key));
        setTimeout(() => { onPlanReady?.(adapted, ev.plan_id); setPhase("idle"); }, 600);
      },
      onMissingFields: (ev) => {
        setMissingFields(ev.missing_fields || []);
        setThreadId(ev.thread_id || null);
        setPhase("idle");
      },
      onWarning: (ev) => {
        setConcernModal({
          concern: ev.concern,
          pending_id: ev.pending_id,
          parent_plan_id: ev.parent_plan_id || planId,
        });
        setPhase("idle");
      },
      onError: (msg) => {
        setErrMsg(msg);
        setPhase("idle");
      },
    });
  };

  const startPlan = () => {
    if (!getAuth()) { onRequestLogin && onRequestLogin(); return; }
    const q = threadId ? (query + " " + (threadId || "")).trim() : query.trim();
    if (!q) return;
    setMissingFields([]);
    doStream({ query: q, thread_id: threadId || undefined });
  };

  const confirmConcern = async () => {
    const { pending_id, parent_plan_id } = concernModal;
    setConcernModal(null);
    setPhase("loading");
    resetJourney();
    confirmModification(pending_id, parent_plan_id, {
      onAbort: (fn) => { abortRef.current = fn; },
      onStage: handleStage,
      onResult: (ev) => {
        const adapted = adaptPlan(ev.plan, currentUsername);
        const newPlanId = ev.plan_id || planId;
        setPlanId(newPlanId);
        setDoneNodes(JOURNEY_STEPS.map(s => s.key));
        setTimeout(() => { onPlanReady?.(adapted, newPlanId); setPhase("idle"); }, 600);
      },
      onError: (msg) => { setErrMsg(msg); setPhase("idle"); },
    });
  };

  const examples = [
    "南京 06.10–06.12 三天，喜欢历史古迹和本地小吃，慢节奏",
    "成都周末两天，想泡茶馆吃火锅",
    "杭州一日，西湖边慢慢走",
  ];

  // ── 加载中 ──
  if (phase === "loading") {
    return (
      <div className="page page-fade">
        <div className="journey">
          <div className="journey-head">
            <h2>正在为你规划这趟旅程</h2>
            <span className="sub">多位 Agent 接力工作中 · 通常需要 1–2 分钟</span>
          </div>
          <JourneyLoading steps={JOURNEY_STEPS} activeNode={activeNode} doneNodes={doneNodes} />
          <div className="journey-steps">
            {JOURNEY_STEPS.map((s) => {
              const isDone = doneNodes.includes(s.key);
              const isActive = s.key === activeNode;
              const cls = isDone ? "done" : isActive ? "active" : "";
              return (
                <div key={s.key} className={`j-step ${cls}`}>
                  <span className="j-ico">{isDone ? "✓" : JOURNEY_STEPS.indexOf(s) + 1}</span>
                  <span>{s.label}</span>
                  <span className="j-detail">{isActive && stageLabel ? stageLabel : s.detail}</span>
                </div>
              );
            })}
          </div>
        </div>
      </div>
    );
  }

  // ── 首屏 idle ──
  return (
    <div className="page page-fade">
      {concernModal && (
        <ConcernModal
          concern={concernModal.concern}
          onKeep={() => { setConcernModal(null); onCancelModify?.(); }}
          onConfirm={confirmConcern}
        />
      )}
      <div className="hero">
        <div>
          <div className="hero-eyebrow">AI Travel Planner · Vol.06</div>
          <h1>把目的地交给我，<br />你只管<em>期待出发</em>。</h1>
          <p className="hero-lede">
            告诉我想去哪里、哪几天、喜欢什么——多位 AI Agent 会查景点、订路线、看天气、找馆子，几分钟内排出一份像杂志一样好读的行程。
          </p>
          <div className="query-card">
            <div className="query-label"><span className="mode-dot"></span>描述你的旅行需求（含目的地、日期、偏好）</div>
            <textarea
              className="query-textarea"
              placeholder="例如：南京 2026-06-10 到 2026-06-12 三天，喜欢历史古迹，想吃本地小吃，慢节奏"
              value={query}
              onChange={(e) => setQuery(e.target.value)}
              onKeyDown={(e) => { if (e.key === "Enter" && (e.metaKey || e.ctrlKey)) startPlan(); }}
            />
            {missingFields.length > 0 && (
              <div className="missing-hints">
                {missingFields.map(f => (
                  <span key={f} className="missing-hint">
                    ⚠ 缺少{f}
                  </span>
                ))}
              </div>
            )}
            {errMsg && <div style={{ marginTop: 8, fontSize: ".85rem", color: "var(--accent)" }}>{errMsg}</div>}
            <div className="query-foot">
              <div className="example-chips">
                {examples.map((ex) => (
                  <button key={ex} className="chip" onClick={() => setQuery(ex)}>{ex.slice(0, 14)}…</button>
                ))}
              </div>
              <button className="go-btn" onClick={startPlan} disabled={!query.trim()}>
                开始规划 <span className="arrow">→</span>
              </button>
            </div>
          </div>
        </div>
        <div className="hero-stage">
          <div className="stamp">PASSPORT<br />2026<br />已盖章</div>
          <div style={{ display: "flex", flexDirection: "column", alignItems: "center", gap: 6 }}>
            <div className="speech">你好呀，我是向导<strong>途途</strong>。这次想去哪儿？</div>
            <Mascot size={190} pose="wave" />
          </div>
        </div>
      </div>
    </div>
  );
}

/* ── 行程详情页 ───────────────────────────────── */
function TripDetailPage({ plan: planProp, planId: planIdProp, onRequestModify, onRequestLogin, currentUsername }) {
  const [plan, setPlan] = React.useState(planProp);
  const [planId, setPlanId] = React.useState(planIdProp);
  const [dayIdx, setDayIdx] = React.useState(0);
  const [modQuery, setModQuery] = React.useState("");
  const [optimizedDays, setOptimizedDays] = React.useState({});
  const [optimizingDay, setOptimizingDay] = React.useState(null);
  const [dayMsg, setDayMsg] = React.useState(null);

  React.useEffect(() => {
    setPlan(planProp);
    setPlanId(planIdProp);
    setDayIdx(0);
    setModQuery("");
    setOptimizedDays({});
    setOptimizingDay(null);
    setDayMsg(null);
  }, [planProp, planIdProp]);

  const applyDayTimeline = (dayI, timeline) => {
    const raw = { ...plan._raw, days: plan._raw.days.map((d, i) => i === dayI ? { ...d, timeline } : d) };
    const adapted = adaptPlan(raw, currentUsername);
    adapted.logs = plan.logs;
    setPlan(adapted);
  };

  const showDayMsg = (dayNo, text) => {
    setDayMsg({ day: dayNo, text });
    setTimeout(() => setDayMsg(m => (m && m.day === dayNo && m.text === text ? null : m)), 5000);
  };

  const handleOptimize = async (dayNo) => {
    setOptimizingDay(dayNo);
    try {
      const dayI = dayNo - 1;
      const rawTimeline = plan._raw?.days?.[dayI]?.timeline;
      const res = await optimizeDay(planId, dayNo);
      if (res.improved && res.optimized_day) {
        setOptimizedDays(prev => ({ ...prev, [dayI]: rawTimeline }));
        applyDayTimeline(dayI, res.optimized_day.timeline);
        showDayMsg(dayNo, `已优化：${res.original_km}km → ${res.optimized_km}km`);
      } else {
        showDayMsg(dayNo, "当前顺序已是最短路线");
      }
    } catch (e) { alert(e.message || "优化失败"); }
    finally { setOptimizingDay(null); }
  };

  const handleRevert = async (dayNo) => {
    const dayI = dayNo - 1;
    const orig = optimizedDays[dayI];
    if (!orig || !planId) return;
    try {
      await revertDay(planId, dayNo, orig);
      setOptimizedDays(prev => { const n = { ...prev }; delete n[dayI]; return n; });
      applyDayTimeline(dayI, orig);
      showDayMsg(dayNo, "已回退到优化前的顺序");
    } catch (e) { alert(e.message || "回退失败"); }
  };

  const startModify = () => {
    if (!getAuth()) { onRequestLogin?.(); return; }
    if (!modQuery.trim() || !planId) return;
    onRequestModify?.(modQuery, planId);
  };

  if (!plan) return null;
  const day = plan.days[dayIdx];
  const dayNo = dayIdx + 1;
  const hasAttractions = (day.items || []).filter(it => it.type === "attraction").length >= 2;
  const isOptimized = optimizedDays[dayIdx] !== undefined;

  return (
    <div className="page page-fade">
      <div className="result-grid">
        <div>
          <div className="plan-cover">
            <div className="cover-img" style={{ backgroundImage: `url('${plan.cover_img}')` }}></div>
            <div className="cover-shade"></div>
            <div className="cover-body">
              <div className="eyebrow">ITINERARY · 行程总览</div>
              <h2>{plan.title}</h2>
              <div className="cover-meta">
                <span>{plan.date_range}</span>
                {plan.badges.map((b) => <span key={b} className="cover-badge">{b}</span>)}
              </div>
            </div>
          </div>

          {plan.weather.length > 0 && (
            <div className="weather-strip">
              {plan.weather.map((w, i) => (
                <div key={i} className="weather-cell">
                  <span className="w-ico">{w.icon}</span>
                  <span>
                    <div className="w-day">{w.day}</div>
                    <div className="w-temp">
                      <span className="w-weather">{w.text}</span>
                      <span className="w-hi">{w.hi}°</span>
                      <span className="w-sep">/</span>
                      <span className="w-lo">{w.lo}°</span>
                    </div>
                  </span>
                </div>
              ))}
            </div>
          )}

          <div className="day-tabs">
            {plan.days.map((d, i) => (
              <button key={i} className={`day-tab ${i === dayIdx ? "active" : ""}`} onClick={() => setDayIdx(i)}>
                <span className="dt-num">Day {i + 1}</span>
                <span className="dt-date">{d.date}</span>
              </button>
            ))}
          </div>

          <div className="day-header">
            <div className="day-theme">{day.theme}</div>
            {dayMsg && dayMsg.day === dayNo && <span className="day-opt-msg">{dayMsg.text}</span>}
            {hasAttractions && planId && (
              isOptimized ? (
                <button className="revert-btn" onClick={() => handleRevert(dayNo)}>↩ 回退</button>
              ) : (
                <button className="optimize-btn" disabled={optimizingDay === dayNo} onClick={() => handleOptimize(dayNo)}>
                  {optimizingDay === dayNo ? "优化中…" : "🔀 优化路线"}
                </button>
              )
            )}
          </div>

          <Timeline items={day.items} key={dayIdx} />

          <div className="tip-card">
            <Mascot size={72} pose="point" />
            <div className="tip-body">
              <div className="tip-title">途途的小贴士</div>
              {plan.tips.length > 0 ? (
                <ul className="tip-list">{plan.tips.map((t, i) => <li key={i}>{t}</li>)}</ul>
              ) : (
                <div className="tip-text">行程已为你精心安排，祝旅途愉快！</div>
              )}
            </div>
          </div>

          {plan.logs && plan.logs.length > 0 && (
            <details className="log-details">
              <summary>规划过程日志（{plan.logs.length} 步）</summary>
              <ul className="log-list">{plan.logs.map((l, i) => <li key={i}>{l}</li>)}</ul>
            </details>
          )}
        </div>

        <div className="map-col">
          <MapPanel day={day} dayIdx={dayIdx} />
        </div>
      </div>

      <div className="query-card" style={{ margin: "30px auto 0", maxWidth: 760 }}>
        <div className="query-label">
          <span className="mode-dot" style={{ background: "var(--second)" }}></span>
          对行程有意见？直接说，我来改
        </div>
        <div style={{ display: "flex", gap: 12, alignItems: "flex-end" }}>
          <textarea className="query-textarea" rows="1" style={{ minHeight: 30 }}
            placeholder="例如：第 2 天把玄武湖换成颐和路，景点别太多"
            value={modQuery} onChange={(e) => setModQuery(e.target.value)}
            onKeyDown={(e) => { if (e.key === "Enter" && (e.metaKey || e.ctrlKey)) startModify(); }}
          />
          <button className="go-btn" onClick={startModify} disabled={!modQuery.trim()}>
            修改规划 <span className="arrow">→</span>
          </button>
        </div>
      </div>
    </div>
  );
}

/* ── 历史行程页 ───────────────────────────────── */
function HistoryPage({ onOpenPlan, currentUsername }) {
  const [trips, setTrips] = React.useState(null);
  const [loading, setLoading] = React.useState(true);

  React.useEffect(() => {
    getHistory().then(data => {
      setTrips(Array.isArray(data) ? data : []);
      setLoading(false);
    }).catch(() => { setTrips([]); setLoading(false); });
  }, []);

  const open = async (trip) => {
    try {
      const data = await getHistoryItem(trip.id);
      if (data && data.plan) onOpenPlan && onOpenPlan(data.plan, trip.id);
    } catch {}
  };

  return (
    <div className="page page-fade">
      <div className="mag-head">
        <div>
          <div className="eyebrow">ARCHIVE · 过往旅程</div>
          <h1>历史行程</h1>
        </div>
        {!loading && trips && (
          <div className="head-note">共 {trips.length} 期 · 点击封面回看<br />每一趟都是一期独立的「刊物」</div>
        )}
      </div>

      {loading && (
        <div className="skeleton-grid">
          {[1,2,3,4].map(i => <div key={i} className="skeleton-card" />)}
        </div>
      )}

      {!loading && trips && trips.length === 0 && (
        <div className="empty-state">
          <Mascot size={100} pose="think" />
          <div className="es-title">还没有行程记录</div>
          <div>先去新建一趟旅行吧！</div>
        </div>
      )}

      {!loading && trips && trips.length > 0 && (
        <div className="trip-grid">
          {trips.map((t, idx) => {
            const dest = t.destination || "旅行";
            const encDest = encodeURIComponent(dest);
            const imgUrl = `https://picsum.photos/seed/${encDest}-${t.id}/600/760`;
            const dates = (() => {
              const s = t.start_date ? t.start_date.replace(/-/g, ".").slice(2) : "";
              const e = t.end_date ? t.end_date.replace(/-/g, ".").slice(2) : "";
              return s && e ? `${s} — ${e}` : (t.created_at || "").slice(0, 10);
            })();
            const daysCount = t.days_count ||
              (t.start_date && t.end_date
                ? Math.ceil((new Date(t.end_date) - new Date(t.start_date)) / 86400000) + 1
                : 1);
            const isModified = !!t.parent_id;

            return (
              <div key={t.id} className="trip-cover"
                onClick={() => open(t)} role="button" tabIndex={0}
                onKeyDown={(e) => e.key === "Enter" && open(t)}>
                <div className="tc-img" style={{ backgroundImage: `url('${imgUrl}')` }}></div>
                <div className="tc-shade"></div>
                <div className="tc-top">
                  <span>VOL.{String(idx + 1).padStart(2, "0")}</span>
                  <span>{daysCount} DAYS</span>
                </div>
                <div className="tc-body">
                  <div className="tc-dest">{dest}</div>
                  <div className="tc-dates">{dates}</div>
                  <div className="tc-badges">
                    <span className="tc-badge">{daysCount} 天行程</span>
                    {isModified && <span className="tc-badge modified">修改版</span>}
                  </div>
                </div>
              </div>
            );
          })}
        </div>
      )}
    </div>
  );
}

/* ── 画像页 ──────────────────────────────────── */
function TagEditor({ label, hint, tags, onChange }) {
  const [val, setVal] = React.useState("");

  const add = () => {
    const v = val.trim().replace(/[,，]$/, "");
    if (v && !tags.includes(v)) onChange([...tags, v]);
    setVal("");
  };

  const remove = (t) => onChange(tags.filter(x => x !== t));

  return (
    <div className="pf-field">
      <div className="pf-label">{label}<span className="pf-hint">{hint}</span></div>
      <div className="tag-editor">
        {tags.map((t) => (
          <span key={t} className="tag">{t}
            <button onClick={() => remove(t)} aria-label={`删除 ${t}`}>✕</button>
          </span>
        ))}
        <input className="tag-input" value={val} placeholder="输入后回车添加…"
          onChange={(e) => setVal(e.target.value)}
          onKeyDown={(e) => { if (e.key === "Enter" || e.key === "," || e.key === "，") { e.preventDefault(); add(); } }}
          onBlur={() => val.trim() && add()} />
      </div>
    </div>
  );
}

function ProfilePage({ currentUsername }) {
  const [prefs, setPrefs] = React.useState({
    attraction_prefs: [],
    food_prefs: [],
    habit_prefs: [],
    visited_destinations: [],
  });
  const [stats, setStats] = React.useState({ trips: 0, cities: 0 });
  const [saved, setSaved] = React.useState(false);
  const [loading, setLoading] = React.useState(true);
  // 用户改过标签且未保存时为 true，此时自动刷新不覆盖编辑中的内容
  const dirtyRef = React.useRef(false);

  const applyProfile = (data) => {
    setPrefs({
      attraction_prefs: data.attraction_prefs || [],
      food_prefs: data.food_prefs || [],
      habit_prefs: data.habit_prefs || [],
      visited_destinations: data.visited_destinations || [],
    });
    setStats({
      trips: data.trip_count || 0,
      cities: (data.visited_destinations || []).length,
    });
  };

  // 画像更新 Agent 在规划完成后异步落库，停留本页时靠聚焦/轮询拉到最新画像
  const refreshProfile = async () => {
    if (dirtyRef.current) return;
    try {
      const data = await getProfile();
      if (data && !dirtyRef.current) applyProfile(data);
    } catch {}
  };

  React.useEffect(() => {
    refreshProfile().finally(() => setLoading(false));
    const onVisible = () => { if (!document.hidden) refreshProfile(); };
    window.addEventListener("focus", onVisible);
    document.addEventListener("visibilitychange", onVisible);
    const timer = setInterval(refreshProfile, 15000);
    return () => {
      window.removeEventListener("focus", onVisible);
      document.removeEventListener("visibilitychange", onVisible);
      clearInterval(timer);
    };
  }, []);

  const save = async () => {
    try {
      const data = await saveProfile(prefs);
      dirtyRef.current = false;
      if (data) applyProfile(data);
      setSaved(true);
      setTimeout(() => setSaved(false), 2200);
    } catch (e) {
      alert(e.message || "保存失败");
    }
  };

  const fields = [
    { key: "attraction_prefs", label: "喜欢的旅行主题", hint: "回车或逗号添加" },
    { key: "habit_prefs",      label: "节奏与游玩方式",  hint: "影响每天的景点数量" },
    { key: "food_prefs",       label: "饮食偏好 / 忌口",  hint: "用于餐厅推荐" },
    { key: "visited_destinations", label: "去过的城市", hint: "规划时作为参考" },
  ];

  const username = currentUsername || getAuth()?.username || "旅行者";
  const initial = username.slice(-1);

  return (
    <div className="page page-fade">
      <div className="mag-head">
        <div>
          <div className="eyebrow">PROFILE · 旅行画像</div>
          <h1>我的旅行画像</h1>
        </div>
        <div className="head-note">这些偏好会在每次规划时<br />自动作为默认参考</div>
      </div>

      <div className="profile-grid">
        <aside className="profile-aside">
          <div style={{ display: "grid", placeItems: "center" }}>
            <Mascot size={120} pose="idle" />
          </div>
          <div className="pa-name">{username}</div>
          <div className="pa-sub">途途已陪你走过 {stats.cities} 座城</div>
          <div className="pa-stats">
            <div className="pa-stat"><div className="ps-n">{stats.trips}</div><div className="ps-l">趟旅程</div></div>
            <div className="pa-stat"><div className="ps-n">{stats.cities}</div><div className="ps-l">座城市</div></div>
            <div className="pa-stat">
              <div className="ps-n">{(prefs.attraction_prefs.length + prefs.food_prefs.length + prefs.habit_prefs.length)}</div>
              <div className="ps-l">个偏好</div>
            </div>
          </div>
        </aside>

        <div>
          {loading ? (
            <div style={{ color: "var(--ink-3)", padding: "40px 0" }}>加载中…</div>
          ) : (
            fields.map(f => (
              <TagEditor
                key={f.key}
                label={f.label}
                hint={f.hint}
                tags={prefs[f.key]}
                onChange={(v) => { dirtyRef.current = true; setPrefs(p => ({ ...p, [f.key]: v })); }}
              />
            ))
          )}
          <div className="pf-actions">
            <button className="go-btn" onClick={save} disabled={loading}>保存画像</button>
            <span className={`save-hint ${saved ? "show" : ""}`}>✓ 已保存，下次规划自动生效</span>
          </div>
        </div>
      </div>
    </div>
  );
}

/* ── Sweep 预览页 ─────────────────────────────────── */
function SweepPreviewPage() {
  const [files, setFiles]   = React.useState([]);
  const [selFile, setSelFile] = React.useState(null);
  const [selIdx, setSelIdx]   = React.useState(0);
  const [trial, setTrial]     = React.useState(null);
  const [loading, setLoading] = React.useState(false);
  const [dayIdx, setDayIdx]   = React.useState(0);

  // 获取文件列表
  React.useEffect(() => {
    fetch("/api/sweep/list")
      .then(r => r.json())
      .then(data => {
        setFiles(Array.isArray(data) ? data : []);
        if (data.length > 0) setSelFile(data[0].file);
      })
      .catch(() => {});
  }, []);

  // 获取 trial 数据
  React.useEffect(() => {
    if (!selFile) return;
    setLoading(true);
    setDayIdx(0);
    setTrial(null);
    fetch(`/api/sweep/trial?file=${encodeURIComponent(selFile)}&idx=${selIdx}`)
      .then(r => r.json())
      .then(data => { setTrial(data); setLoading(false); })
      .catch(() => setLoading(false));
  }, [selFile, selIdx]);

  const fileTrials = files.find(f => f.file === selFile)?.trials || [];
  const adapted    = trial?.final_plan ? adaptPlan(trial.final_plan, null) : null;
  const day        = adapted?.days?.[dayIdx];

  return (
    <div className="sweep-preview-page">
      {/* 顶部导航：文件 + trial 下拉 */}
      <div className="sweep-nav">
        <span className="sweep-nav-title">🧪 测试预览</span>
        <select
          value={selFile || ""}
          onChange={e => { setSelFile(e.target.value); setSelIdx(0); }}
          disabled={files.length === 0}
        >
          {files.length === 0 && <option>暂无 sweep 结果</option>}
          {files.map(f => (
            <option key={f.file} value={f.file}>
              {f.file}（{f.trials.length} 条）
            </option>
          ))}
        </select>
        <select
          value={selIdx}
          onChange={e => setSelIdx(Number(e.target.value))}
          disabled={fileTrials.length === 0}
        >
          {fileTrials.map(t => (
            <option key={t.idx} value={t.idx}>
              {t.crash ? "💥" : t.pass ? "✅" : "❌"} {t.dest} / {t.pref} / trial {t.idx + 1}
            </option>
          ))}
        </select>
        {trial && !trial.crash && (
          <span className="sweep-nav-meta">
            rev={trial.review_rounds}轮 · tc={trial.time_check_rounds}轮 · {trial.elapsed_s}s
          </span>
        )}
      </div>

      {loading && <div className="sweep-loading">加载中…</div>}

      {!loading && trial?.crash && (
        <div className="sweep-crash">
          💥 该 trial 崩溃：{trial.crash_reason} — {trial.crash_detail || ""}
        </div>
      )}

      {!loading && trial && !trial.crash && !adapted && (
        <div className="sweep-empty">
          <div className="es-title">该 trial 无 final_plan 数据</div>
          <div>这是旧版 sweep 结果，请重新运行 sweep 生成新文件</div>
        </div>
      )}

      {!loading && trial && !trial.crash && adapted && (
        <div className="sweep-body">
          {/* 左：行程 */}
          <div className="sweep-plan">
            {adapted.weather?.length > 0 && (
              <div className="weather-strip">
                {adapted.weather.map((w, i) => (
                  <div key={i} className="weather-cell">
                    <span className="w-ico">{w.icon}</span>
                    <span>
                      <div className="w-day">{w.day}</div>
                      <div className="w-temp">
                        <span className="w-weather">{w.text}</span>
                        <span className="w-hi">{w.hi}°</span>
                        <span className="w-sep">/</span>
                        <span className="w-lo">{w.lo}°</span>
                      </div>
                    </span>
                  </div>
                ))}
              </div>
            )}

            <div className="day-tabs">
              {adapted.days.map((d, i) => (
                <button key={i} className={`day-tab ${i === dayIdx ? "active" : ""}`} onClick={() => setDayIdx(i)}>
                  <span className="dt-num">Day {i + 1}</span>
                  <span className="dt-date">{d.date}</span>
                </button>
              ))}
            </div>

            {day && <div className="day-header"><div className="day-theme">{day.theme}</div></div>}
            {day && <Timeline items={day.items} key={dayIdx} />}

            {adapted.tips?.length > 0 && (
              <div className="tip-card" style={{ marginTop: 20 }}>
                <div className="tip-body">
                  <div className="tip-title">途途的小贴士</div>
                  <ul className="tip-list">
                    {adapted.tips.map((t, i) => <li key={i}>{t}</li>)}
                  </ul>
                </div>
              </div>
            )}
          </div>

          {/* 中：地图 */}
          <div className="map-col">
            {day && <MapPanel day={day} dayIdx={dayIdx} />}
          </div>

          {/* 右：评测面板 */}
          <SweepEvalPanel
            code={trial.code}
            reviewRounds={trial.review_rounds}
            timeCheckRounds={trial.time_check_rounds}
            profileUpdate={trial.profile_update}
            dialogue={trial.transcript?.dialogue}
            overallPass={trial.overall_pass}
            elapsedS={trial.elapsed_s}
          />
        </div>
      )}

      {!loading && files.length === 0 && (
        <div className="sweep-empty">
          <div className="es-title">暂无 sweep 结果</div>
          <div>先运行 <code>python -m tests.eval.sweep --dest 北京 --pref history --k 1 --no-judge</code></div>
        </div>
      )}
    </div>
  );
}

Object.assign(window, { PlanPage, TripDetailPage, HistoryPage, ProfilePage, AuthModal, SweepPreviewPage });
