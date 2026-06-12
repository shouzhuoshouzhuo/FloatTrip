// edit.jsx — 行程手动编辑：编辑态时间轴 / 拖拽 / 搜索弹层 / 时间编辑

/* ── 纯函数工具 ──────────────────────────────────── */

// 与后端 helpers.haversine_km 同公式；仅用于编辑态即时显示，落库以服务端重算为准
function haversineKm(a, b) {
  const R = 6371.0;
  const rad = (x) => (x * Math.PI) / 180;
  const dlat = rad(b.lat - a.lat), dlon = rad(b.lng - a.lng);
  const h = Math.sin(dlat / 2) ** 2 +
    Math.cos(rad(a.lat)) * Math.cos(rad(b.lat)) * Math.sin(dlon / 2) ** 2;
  return 2 * R * Math.asin(Math.sqrt(h));
}

// 原地重算一天 timeline 的 dist_from_prev_km（规则与后端 _recalc_dists 一致）
function recalcDayDists(timeline) {
  const valid = (loc) => loc && typeof loc.lat === "number" && typeof loc.lng === "number";
  timeline.forEach((item, i) => {
    if (i === 0) { delete item.dist_from_prev_km; return; }
    const prev = timeline[i - 1].location, cur = item.location;
    if (valid(prev) && valid(cur)) item.dist_from_prev_km = Math.round(haversineKm(prev, cur) * 100) / 100;
    else delete item.dist_from_prev_km;
  });
}

// 拖拽换序：时间段留在位置上不跟卡走——
// 先记录原顺序中各景点的时段，移动后按新顺序把时段逐个套回景点
function reorderKeepTimes(timeline, from, to) {
  const slots = timeline
    .filter(it => it.type === "attraction")
    .map(it => ({ start_time: it.start_time, end_time: it.end_time, period: it.period }));
  const arr = timeline.slice();
  const [moved] = arr.splice(from, 1);
  arr.splice(to, 0, moved);
  let si = 0;
  return arr.map(it => (it.type === "attraction" ? { ...it, ...slots[si++] } : it));
}

/* ── 搜索弹层（更换/新增 景点·餐厅） ───────────────── */
function PoiSearchModal({ city, kind, title, onPick, onClose }) {
  const [kw, setKw] = React.useState("");
  const [results, setResults] = React.useState(null);
  const [loading, setLoading] = React.useState(false);
  const [err, setErr] = React.useState("");

  const search = async () => {
    if (!kw.trim() || loading) return;
    setLoading(true); setErr("");
    try {
      const r = await searchPoi(city, kw.trim(), kind);
      setResults(r);
      if (!r.length) setErr("没找到，换个关键词试试");
    } catch (e) { setErr(e.message || "搜索失败"); }
    finally { setLoading(false); }
  };

  return (
    <div className="modal-backdrop" onClick={(e) => e.target === e.currentTarget && onClose()}>
      <div className="modal-card poi-search-card">
        <button className="modal-close" onClick={onClose}>✕</button>
        <div className="modal-title">{title}</div>
        <div className="poi-search-bar">
          <input className="form-input" autoFocus value={kw}
            placeholder={kind === "restaurant" ? "输入餐厅名或菜系，回车搜索" : "输入景点名，回车搜索"}
            onChange={(e) => setKw(e.target.value)}
            onKeyDown={(e) => e.key === "Enter" && search()} />
          <button className="go-btn" onClick={search} disabled={loading || !kw.trim()}>
            {loading ? "搜索中…" : "搜索"}
          </button>
        </div>
        {err && <div className="poi-search-err">{err}</div>}
        <div className="poi-results">
          {(results || []).map((p, i) => (
            <button key={i} className="poi-result" onClick={() => onPick(p)}>
              <span className="poi-result-name">{p.name}</span>
              <span className="poi-result-meta">
                {p.rating != null && <span>★ {Number(p.rating).toFixed(1)}</span>}
                {p.cost && <span>¥{p.cost}/人</span>}
                {p.open_time && <span>开放 {p.open_time}</span>}
                {p.address && <span>{p.address}</span>}
              </span>
            </button>
          ))}
        </div>
      </div>
    </div>
  );
}

/* ── 时间段编辑器（仅景点） ─────────────────────────── */
function TimeRangeEditor({ start, end, onCommit }) {
  const [st, setSt] = React.useState(start || "");
  const [et, setEt] = React.useState(end || "");
  const [bad, setBad] = React.useState(false);

  // 撤销/重做会改变传入的时间，同步回本地输入
  React.useEffect(() => { setSt(start || ""); setEt(end || ""); setBad(false); }, [start, end]);

  const commit = () => {
    if (st && et && st >= et) { setBad(true); return; }
    setBad(false);
    if (st !== (start || "") || et !== (end || "")) onCommit(st || null, et || null);
  };

  return (
    <span className={`time-edit ${bad ? "bad" : ""}`}>
      <input type="time" value={st} onChange={(e) => setSt(e.target.value)} onBlur={commit} />
      <span>–</span>
      <input type="time" value={et} onChange={(e) => setEt(e.target.value)} onBlur={commit} />
      {bad && <span className="time-edit-err">开始须早于结束</span>}
    </span>
  );
}

/* ── 编辑态卡片 ─────────────────────────────────────── */
function EditCard({ raw, dist, onReplace, onDelete, onTimeChange }) {
  const isAttr = raw.type === "attraction";
  const mealLabel = isAttr ? null : raw.type === "lunch" ? "午餐" : "晚餐";
  return (
    <div className="edit-card">
      <span className="drag-grip" title="拖拽调整顺序">⠿</span>
      <div className="edit-card-body">
        <div className="edit-card-title">
          <span>{raw.name || `${mealLabel || "条目"}（待安排）`}</span>
          {mealLabel && <span className="meal-flag">{mealLabel}</span>}
          {dist != null && dist > 0 && <span className="edit-dist">↕ {dist} km</span>}
        </div>
        <div className="edit-card-meta">
          {isAttr && <TimeRangeEditor start={raw.start_time} end={raw.end_time} onCommit={onTimeChange} />}
          {raw.rating != null && <span className="star">★ {Number(raw.rating).toFixed(1)}</span>}
          {!isAttr && raw.cost && <span>¥{raw.cost}/人</span>}
          {isAttr && raw.open_time && <span>开放 {raw.open_time}</span>}
        </div>
      </div>
      <div className="edit-card-acts">
        <button className="edit-act" onClick={onReplace}>↔ 更换</button>
        <button className="edit-act danger" onClick={onDelete} title="删除（可撤销）">✕</button>
      </div>
    </div>
  );
}

/* ── 可拖拽时间轴 ───────────────────────────────────── */
// ver：编辑版本号。每次 draft 变化 +1，靠 key 强制重挂载列表，
// 保证 Sortable 动过的 DOM 与 React state 重新对齐（SortableJS×React 标准做法）。
function EditableTimeline({ rawTimeline, ver, onReorder, onReplace, onDelete, onTimeChange, onAdd }) {
  const listRef = React.useRef(null);

  React.useEffect(() => {
    // CDN 加载失败时优雅降级：拖拽不可用，但更换/删除/改时间照常
    if (!listRef.current || !window.Sortable) return;
    const s = window.Sortable.create(listRef.current, {
      animation: 180,
      handle: ".drag-grip",
      ghostClass: "edit-ghost",
      onEnd: (evt) => {
        if (evt.oldIndex !== evt.newIndex) onReorder(evt.oldIndex, evt.newIndex);
      },
    });
    return () => s.destroy();
  }, [ver]); // eslint-disable-line

  return (
    <div className="edit-timeline">
      <div ref={listRef} key={ver} className="edit-list">
        {rawTimeline.map((raw, i) => (
          <EditCard key={`${ver}-${i}`} raw={raw} dist={raw.dist_from_prev_km}
            onReplace={() => onReplace(i)}
            onDelete={() => onDelete(i)}
            onTimeChange={(st, et) => onTimeChange(i, st, et)} />
        ))}
      </div>
      {rawTimeline.length === 0 && <div className="edit-empty">这一天还没有安排，用下面的按钮添加吧</div>}
      <div className="edit-add-row">
        <button className="edit-add" onClick={() => onAdd("attraction")}>＋ 景点</button>
        <button className="edit-add" onClick={() => onAdd("lunch")}>＋ 午餐</button>
        <button className="edit-add" onClick={() => onAdd("dinner")}>＋ 晚餐</button>
      </div>
    </div>
  );
}

/* ── 编辑工具栏 ─────────────────────────────────────── */
function EditToolbar({ canUndo, canRedo, saving, saveErr, onUndo, onRedo, onCancel, onSave }) {
  return (
    <div className="edit-toolbar">
      <button className="edit-tool" disabled={!canUndo} onClick={onUndo}>↩ 撤销</button>
      <button className="edit-tool" disabled={!canRedo} onClick={onRedo}>↪ 重做</button>
      <span className="edit-toolbar-hint">{saveErr ? "" : "拖动 ⠿ 调整顺序 · 点时间可修改"}</span>
      {saveErr && <span className="edit-save-err">{saveErr}</span>}
      <button className="edit-tool" onClick={onCancel}>✕ 取消</button>
      <button className="edit-tool primary" disabled={saving} onClick={onSave}>
        {saving ? "保存中…" : "✓ 完成编辑"}
      </button>
    </div>
  );
}

Object.assign(window, {
  haversineKm, recalcDayDists, reorderKeepTimes,
  PoiSearchModal, TimeRangeEditor, EditCard, EditableTimeline, EditToolbar,
});
