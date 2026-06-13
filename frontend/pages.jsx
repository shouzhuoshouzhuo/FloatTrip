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
function PlanPage({ onRequestLogin, currentUsername, onPhaseChange, onPlanReady, modifyTrigger, onCancelModify, onManageProfile }) {
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
  const [profile, setProfile] = React.useState(null);
  const abortRef = React.useRef(null);
  // 旅程已走到的最远站点下标：planner⇄reviewer / planner⇄time_check 循环时只前进不后退
  const maxStepRef = React.useRef(-1);

  React.useEffect(() => () => abortRef.current && abortRef.current(), []);

  // 拉取用户画像，在新建规划页展示，引导用户参考自身偏好斟酌措辞
  // 依赖 currentUsername：用户登录后立即刷新展示，登出则清空（无需重新进入本页）
  React.useEffect(() => {
    if (!getAuth()) { setProfile(null); return; }
    getProfile().then(setProfile).catch(() => {});
  }, [currentUsername]);

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
    const isModify = !!(body.plan_id && body.modification_notes);
    if (isModify) {
      const preDone = JOURNEY_STEPS.slice(0, 3).map(s => s.key);
      maxStepRef.current = 3;
      setDoneNodes(preDone);
      setActiveNode("plan_review");
      setStageLabel("");
      setLogs([]);
    } else {
      resetJourney();
    }
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
    "北京明天三日游，想玩颐和园、故宫，不喜欢走太多路",
    "成都周末两天，想泡茶馆吃火锅",
    "杭州一日，西湖边慢慢走",
  ];

  // 画像偏好行（仅渲染非空字段；全空则整卡隐藏）
  const profileRows = profile ? [
    { key: "attr", label: "景点", cls: "attr", items: profile.attraction_prefs || [] },
    { key: "food", label: "餐饮", cls: "food", items: profile.food_prefs || [] },
    { key: "habit", label: "习惯", cls: "habit", items: profile.habit_prefs || [] },
  ].filter(r => r.items.length) : [];

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
          {profileRows.length > 0 && (
            <div className="profile-hint">
              <div className="ph-head">
                <span className="ph-title">途途记得的你</span>
                <button className="ph-manage" onClick={onManageProfile}>管理画像</button>
              </div>
              <p className="ph-desc">这些是从你过往行程沉淀的偏好。规划时可对照它斟酌措辞——说得越贴合，行程越懂你。</p>
              <div className="ph-rows">
                {profileRows.map(r => (
                  <div key={r.key} className="ph-row">
                    <span className="ph-label">{r.label}</span>
                    <div className="ph-chips">
                      {r.items.map((it, i) => (
                        <span key={i} className={`ph-chip ${r.cls}`}>{it}</span>
                      ))}
                    </div>
                  </div>
                ))}
              </div>
            </div>
          )}
          <div className="query-card">
            <div className="query-label"><span className="mode-dot"></span>描述你的旅行需求（含目的地、日期、偏好）</div>
            <textarea
              className="query-textarea"
              placeholder="例如：北京明天三日游，想玩颐和园、故宫，不喜欢走太多路"
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
  const [hotel, setHotel] = React.useState("");
  const [notes, setNotes] = React.useState("");
  const [metaDirty, setMetaDirty] = React.useState(false);
  const [metaSaving, setMetaSaving] = React.useState(false);
  const [activeNavKey, setActiveNavKey] = React.useState(null);
  const [activeNavPair, setActiveNavPair] = React.useState(null);
  const [nearbyTarget, setNearbyTarget] = React.useState(null);
  const [themeInput, setThemeInput] = React.useState("");

  React.useEffect(() => {
    setPlan(planProp);
    setPlanId(planIdProp);
    setDayIdx(0);
    setModQuery("");
    setOptimizedDays({});
    setOptimizingDay(null);
    setDayMsg(null);
    setHotel(planProp?.hotel || "");
    setNotes(planProp?.notes || "");
    setMetaDirty(false);
    setActiveNavKey(null);
    setActiveNavPair(null);
    setNearbyTarget(null);
    // 切换行程时清除编辑态，防止残留
    setEditing(false);
    setDraft(null); draftRef.current = null;
    setUndoStack([]);
    setRedoStack([]);
    setSaveErr("");
    setSearchTarget(null);
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
    if (!confirm("将按最短路程优化景点游玩顺序，餐厅需要你重新规划")) return;
    setOptimizingDay(dayNo);
    try {
      const dayI = dayNo - 1;
      const rawTimeline = plan._raw?.days?.[dayI]?.timeline;
      const res = await optimizeDay(planId, dayNo);
      if (res.optimized_day) {
        if (res.improved) {
          setOptimizedDays(prev => ({ ...prev, [dayI]: rawTimeline }));
          showDayMsg(dayNo, `已优化：${res.original_km}km → ${res.optimized_km}km`);
        } else {
          showDayMsg(dayNo, "当前顺序已是最短路线");
        }
        applyDayTimeline(dayI, res.optimized_day.timeline);
      }
    } catch (e) { alert(e.message || "优化失败"); }
    finally { setOptimizingDay(null); }
  };

  const handleNav = (key, pair, nearbyItem) => {
    if (nearbyItem) {
      setNearbyTarget({ location: nearbyItem.location, name: nearbyItem.name });
      return;
    }
    if (key === activeNavKey) {
      setActiveNavKey(null); setActiveNavPair(null);
    } else {
      setActiveNavKey(key); setActiveNavPair(pair);
    }
  };

  const handleSaveMeta = async () => {
    setMetaSaving(true);
    try {
      await savePlanMetadata(planId, { hotel, notes });
      setMetaDirty(false);
    } catch (e) { alert(e.message || "保存失败"); }
    finally { setMetaSaving(false); }
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

  // ── 手动编辑态 ──
  const [editing, setEditing] = React.useState(false);
  const [draft, setDraft] = React.useState(null);          // _raw.days 的深拷贝
  const draftRef = React.useRef(null);
  React.useEffect(() => { draftRef.current = draft; }, [draft]);
  const [undoStack, setUndoStack] = React.useState([]);    // 元素 = draft 快照
  const [redoStack, setRedoStack] = React.useState([]);
  const [editVer, setEditVer] = React.useState(0);         // 每次变更 +1，驱动 Sortable 重挂载
  const [saving, setSaving] = React.useState(false);
  const [saveErr, setSaveErr] = React.useState("");
  // 搜索弹层目标：{ dayI, idx } 替换；{ dayI, idx:null, addType } 新增
  const [searchTarget, setSearchTarget] = React.useState(null);

  const dirty = undoStack.length > 0;
  const dirtyRef = React.useRef(false);
  React.useEffect(() => { dirtyRef.current = dirty; }, [dirty]);

  // 编辑中刷新/关页守卫（dirtyRef 避免 beforeunload 闭包捕获过期 dirty 值）
  React.useEffect(() => {
    if (!editing) return;
    const guard = (e) => { if (dirtyRef.current) { e.preventDefault(); e.returnValue = ""; } };
    window.addEventListener("beforeunload", guard);
    return () => window.removeEventListener("beforeunload", guard);
  }, [editing]);

  const enterEdit = () => {
    const clone = structuredClone(plan._raw.days);
    setDraft(clone); draftRef.current = clone;
    setUndoStack([]); setRedoStack([]); setSaveErr("");
    setEditing(true); setEditVer(v => v + 1);
  };

  const exitEdit = () => {
    if (dirty && !confirm("放弃未保存的修改？")) return;
    setEditing(false); setDraft(null); draftRef.current = null; setSaveErr(""); setSearchTarget(null);
  };

  // 所有编辑操作的唯一入口：拷贝 → 变更 → 重算距离 → 压撤销栈
  // 经 draftRef 读最新值，同一 tick 多次调用也不会丢快照
  const applyEdit = (mutate) => {
    const cur = draftRef.current;
    setUndoStack(s => [...s, cur]);
    setRedoStack([]);
    const next = structuredClone(cur);
    mutate(next);
    next.forEach(d => recalcDayDists(d.timeline));
    setDraft(next);
    draftRef.current = next;
    setEditVer(v => v + 1);
  };

  const undo = () => {
    if (!undoStack.length) return;
    const cur = draftRef.current;
    const prev = undoStack[undoStack.length - 1];
    setRedoStack(r => [...r, cur]);
    setUndoStack(s => s.slice(0, -1));
    setDraft(prev);
    draftRef.current = prev;
    setEditVer(v => v + 1);
  };

  const redo = () => {
    if (!redoStack.length) return;
    const cur = draftRef.current;
    const next = redoStack[redoStack.length - 1];
    setUndoStack(s => [...s, cur]);
    setRedoStack(r => r.slice(0, -1));
    setDraft(next);
    draftRef.current = next;
    setEditVer(v => v + 1);
  };

  const saveEdit = async () => {
    setSaving(true); setSaveErr("");
    try {
      const days = draftRef.current.map((d, i) => ({ day: d.day ?? i + 1, timeline: d.timeline }));
      const res = await saveTimeline(planId, days);
      // 保存主题编辑
      const day_themes = {};
      draftRef.current.forEach((d, i) => { if (d.theme) day_themes[String(d.day ?? i + 1)] = d.theme; });
      if (Object.keys(day_themes).length) {
        try { await savePlanMetadata(planId, { day_themes }); } catch {}
      }
      const adapted = adaptPlan(res.plan, currentUsername);
      adapted.logs = plan.logs;
      setPlan(adapted);
      setEditing(false); setDraft(null); draftRef.current = null; setSearchTarget(null);
      setOptimizedDays({});   // 手动编辑后旧的"优化前快照"失效
    } catch (e) {
      // 网络层错误（Failed to fetch 等）对用户不可读，换成中文提示
      const msg = e.message && !/fetch|network/i.test(e.message) ? e.message : "保存失败，请检查网络后重试";
      setSaveErr(msg);
    } finally { setSaving(false); }
  };

  // ── 各编辑操作 ──
  const handleReorder = (from, to) =>
    applyEdit(d => { d[dayIdx].timeline = reorderKeepTimes(d[dayIdx].timeline, from, to); });

  const handleDelete = (idx) =>
    applyEdit(d => { d[dayIdx].timeline.splice(idx, 1); });

  const handleTimeChange = (idx, st, et) =>
    applyEdit(d => { Object.assign(d[dayIdx].timeline[idx], { start_time: st, end_time: et }); });

  const handlePoiPick = (poi) => {
    const { dayI, idx, addType } = searchTarget;
    setSearchTarget(null);
    applyEdit(d => {
      const tl = d[dayI].timeline;
      if (idx != null) {
        const old = tl[idx];
        if (old.type === "attraction") {
          // 继承时间段与时段，其余字段来自新 POI；旧贴士不再适用
          tl[idx] = { ...old, name: poi.name, rating: poi.rating ?? null,
            open_time: poi.open_time ?? null, location: poi.location,
            photo: poi.photo ?? null, tip: null };
        } else {
          tl[idx] = { type: old.type, name: poi.name, rating: poi.rating ?? null,
            cost: poi.cost ?? null, address: poi.address ?? null,
            location: poi.location, photo: poi.photo ?? null,
            reason: null, no_restaurant: false };
        }
      } else if (addType === "attraction") {
        tl.push({ type: "attraction", name: poi.name, rating: poi.rating ?? null,
          open_time: poi.open_time ?? null, location: poi.location,
          photo: poi.photo ?? null, tip: null,
          start_time: null, end_time: null, period: "afternoon" });
      } else {
        tl.push({ type: addType, name: poi.name, rating: poi.rating ?? null,
          cost: poi.cost ?? null, address: poi.address ?? null,
          location: poi.location, photo: poi.photo ?? null,
          reason: null, no_restaurant: false });
      }
    });
  };

  // 编辑态主题 input 同步
  React.useEffect(() => {
    if (editing && draft) setThemeInput(draft[dayIdx]?.theme || "");
  }, [editing, dayIdx, editVer]); // eslint-disable-line

  // 编辑态视图：draft 经 adaptPlan 渲染（地图点位/items 跟随编辑实时刷新）
  const editedView = React.useMemo(() => {
    if (!editing || !draft) return null;
    const adapted = adaptPlan({ ...plan._raw, days: draft }, currentUsername);
    adapted.logs = plan.logs;
    return adapted;
  }, [editing, editVer]); // editVer 是版本令牌：draft 每次变更都 +1，故意省略 draft/plan 直接依赖

  const startModify = () => {
    if (editing) {
      if (!confirm("正在手动编辑，离开将丢弃未保存的修改。继续？")) return;
      setEditing(false); setDraft(null); draftRef.current = null; setSaveErr("");
    }
    if (!getAuth()) { onRequestLogin?.(); return; }
    if (!modQuery.trim() || !planId) return;
    onRequestModify?.(modQuery, planId);
  };

  if (!plan) return null;
  const viewPlan = editing && editedView ? editedView : plan;
  const day = viewPlan.days[dayIdx];
  const dayNo = dayIdx + 1;
  const hasAttractions = (day.items || []).filter(it => it.type === "attraction").length >= 2;
  const isOptimized = optimizedDays[dayIdx] !== undefined;

  const handlePickMeal = async (poi, mealType) => {
    if (!planId) return;
    setNearbyTarget(null);
    const rawTimeline = plan._raw.days[dayIdx]?.timeline || [];
    const mealEntry = {
      type: mealType,
      name: poi.name,
      rating: poi.rating ?? null,
      cost: poi.cost ?? null,
      address: poi.address ?? null,
      location: poi.location ?? null,
      photo: poi.photo ?? null,
      open_time: poi.open_time ?? null,
      tel: poi.tel ?? null,
      reason: null,
      no_restaurant: false,
    };
    const hasSlot = rawTimeline.some(it => it.type === mealType);
    const newTimeline = hasSlot
      ? rawTimeline.map(item => item.type !== mealType ? item : mealEntry)
      : [...rawTimeline, mealEntry];
    try {
      await saveTimeline(planId, [{ day: dayIdx + 1, timeline: newTimeline }]);
      applyDayTimeline(dayIdx, newTimeline);
      showDayMsg(dayNo, `已更新${mealType === "lunch" ? "午餐" : "晚餐"}：${poi.name}`);
    } catch (e) {
      alert(e.message || "更新失败");
    }
  };

  return (
    <React.Fragment>
      {searchTarget && (
        <PoiSearchModal
          city={plan.destination}
          kind={searchTarget.idx != null
            ? (draft[searchTarget.dayI].timeline[searchTarget.idx].type === "attraction" ? "attraction" : "restaurant")
            : (searchTarget.addType === "attraction" ? "attraction" : "restaurant")}
          title={searchTarget.idx != null ? "更换为…" : "添加…"}
          onPick={handlePoiPick}
          onClose={() => setSearchTarget(null)} />
      )}
      {nearbyTarget && (
        <NearbySearchModal
          location={nearbyTarget.location}
          name={nearbyTarget.name}
          onClose={() => setNearbyTarget(null)}
          onPickMeal={handlePickMeal} />
      )}
    <div className="page page-fade trip-detail-page">
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
              <button key={i} className={`day-tab ${i === dayIdx ? "active" : ""}`}
                onClick={() => { setDayIdx(i); setActiveNavKey(null); setActiveNavPair(null); }}>
                <span className="dt-num">Day {i + 1}</span>
                <span className="dt-date">{d.date}</span>
              </button>
            ))}
          </div>

          <RecommendStrip candidates={viewPlan.candidate_spots} editing={editing} />

          <div className="day-header">
            {editing ? (
              <input
                className="theme-input"
                value={themeInput}
                onChange={e => setThemeInput(e.target.value)}
                onBlur={() => {
                  const cur = draft[dayIdx]?.theme || "";
                  if (themeInput !== cur) applyEdit(d => { d[dayIdx].theme = themeInput; });
                }}
                onKeyDown={e => e.key === "Enter" && e.target.blur()}
              />
            ) : (
              <div className="day-theme">{day.theme}</div>
            )}
            {dayMsg && dayMsg.day === dayNo && <span className="day-opt-msg">{dayMsg.text}</span>}
            {!editing && planId && (
              <button className="optimize-btn" onClick={enterEdit}>✏️ 编辑行程</button>
            )}
            {!editing && hasAttractions && planId && (
              isOptimized ? (
                <button className="revert-btn" onClick={() => handleRevert(dayNo)}>↩ 回退</button>
              ) : (
                <button className="optimize-btn" disabled={optimizingDay === dayNo} onClick={() => handleOptimize(dayNo)}>
                  {optimizingDay === dayNo ? "优化中…" : "🔀 优化路线"}
                </button>
              )
            )}
          </div>

          {editing ? (
            <>
              <EditToolbar canUndo={undoStack.length > 0} canRedo={redoStack.length > 0}
                saving={saving} saveErr={saveErr}
                onUndo={undo} onRedo={redo} onCancel={exitEdit} onSave={saveEdit} />
              <EditableTimeline rawTimeline={draft[dayIdx].timeline} ver={`${dayIdx}-${editVer}`}
                onReorder={handleReorder}
                onReplace={(idx) => setSearchTarget({ dayI: dayIdx, idx })}
                onDelete={handleDelete}
                onTimeChange={handleTimeChange}
                onAdd={(addType) => setSearchTarget({ dayI: dayIdx, idx: null, addType })}
                onDropCandidate={(idx, candidate) => {
                  applyEdit(d => {
                    const old = d[dayIdx].timeline[idx];
                    d[dayIdx].timeline[idx] = {
                      ...old,
                      name: candidate.name,
                      rating: candidate.rating ?? null,
                      open_time: candidate.open_time ?? null,
                      location: candidate.location,
                      photo: candidate.photo ?? null,
                      address: candidate.address ?? null,
                      tip: null,
                    };
                  });
                }} />
            </>
          ) : (
            <Timeline items={day.items} key={dayIdx} onNav={handleNav} activeNavKey={activeNavKey} />
          )}

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

          {planId && (
            <div className="hotel-notes-section">
              <div className="hn-field">
                <label className="hn-label">🏨 住宿</label>
                <input className="hn-input" value={hotel} placeholder="记录酒店名称、价格…"
                  onChange={e => { setHotel(e.target.value); setMetaDirty(true); }} />
              </div>
              <div className="hn-field">
                <label className="hn-label">📝 备注</label>
                <textarea className="hn-input hn-textarea" value={notes} rows={2}
                  placeholder="特别要求、注意事项…"
                  onChange={e => { setNotes(e.target.value); setMetaDirty(true); }} />
              </div>
              {metaDirty && (
                <button className="go-btn" style={{ marginTop: 8 }} disabled={metaSaving} onClick={handleSaveMeta}>
                  {metaSaving ? "保存中…" : "保存行程备注"}
                </button>
              )}
            </div>
          )}

          {plan.logs && plan.logs.length > 0 && (
            <details className="log-details">
              <summary>规划过程日志（{plan.logs.length} 步）</summary>
              <ul className="log-list">{plan.logs.map((l, i) => <li key={i}>{l}</li>)}</ul>
            </details>
          )}
        </div>

        <div className="map-col">
          <MapPanel day={day} dayIdx={dayIdx} navPair={activeNavPair}
            onNavClear={() => { setActiveNavKey(null); setActiveNavPair(null); }} />
        </div>
      </div>

      {!editing && (
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
      )}
    </div>
  </React.Fragment>
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
