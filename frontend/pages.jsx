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

/* ── 持久化旅行对话 ─────────────────────────────── */
function ChatPage({ currentUsername, onRequestLogin, onOpenPlan }) {
  const [conversations, setConversations] = React.useState([]);
  const [activeId, setActiveId] = React.useState(null);
  const [state, setState] = React.useState(() => ChatState.initialState());
  const [draft, setDraft] = React.useState("");
  const [loading, setLoading] = React.useState(true);
  const [error, setError] = React.useState("");
  const [sidebarOpen, setSidebarOpen] = React.useState(false);
  const [visibleRunIds, setVisibleRunIds] = React.useState(() => new Set());
  const [observerReady, setObserverReady] = React.useState(false);
  const [composerTarget, setComposerTarget] = React.useState(null);
  const [compressing, setCompressing] = React.useState(false);
  const [compressionFeedback, setCompressionFeedback] = React.useState("");
  const abortsRef = React.useRef({});
  const activeIdRef = React.useRef(null);
  const runNodesRef = React.useRef({});
  const composerRef = React.useRef(null);
  const errorRef = React.useRef(null);
  const waitingRunsRef = React.useRef(new Set());
  const activityItems = ChatState.activityItems(state);
  const runList = Object.values(state.runs).sort(
    (a, b) => String(a.created_at || "").localeCompare(String(b.created_at || ""))
  );
  const activeRuns = runList.filter(
    run => run.kind !== "chat" && ["queued", "running", "waiting_user"].includes(run.status)
  );
  const activeConversation = conversations.find(item => item.id === activeId) || null;
  const conversationArchived = activeConversation?.status === "archived";
  const hasConversationMessages = Object.keys(state.messages || {}).length > 0;

  const sidebarConversations = conversations.map(item => {
    if (item.id !== activeId || item.status === "archived") return item;
    const formalRuns = runList.filter(run => run.kind !== "chat");
    return {
      ...item,
      has_waiting_user: item.has_waiting_user
        || formalRuns.some(run => run.status === "waiting_user"),
      has_ready_brief: item.has_ready_brief
        || Object.values(state.briefs).some(brief => brief.status === "ready"),
      has_active_planning: item.has_active_planning
        || formalRuns.some(run => ["queued", "running"].includes(run.status)),
    };
  });

  const persistCursor = (runId, sequence) => {
    if (!sequence) return;
    localStorage.setItem(`run-cursor:${runId}`, String(sequence));
  };

  const applyRunEvent = React.useCallback((runId, event) => {
    setState(previous => {
      const next = ChatState.applyEvent(previous, runId, event);
      persistCursor(runId, next.cursors[runId]);
      return next;
    });
  }, []);

  const markViewedIfVisible = React.useCallback(async conversationId => {
    if (!ChatState.shouldMarkConversationViewed(
      document.visibilityState, activeIdRef.current, conversationId
    )) return;
    try {
      const updated = await markConversationViewed(conversationId);
      setConversations(previous => previous.map(item => (
        item.id === updated.id ? { ...item, ...updated } : item
      )));
    } catch {}
  }, []);

  const subscribeRun = React.useCallback((run, explicitCursor = null) => {
    if (!run?.id || abortsRef.current[run.id]) return;
    const cursor = explicitCursor === null
      ? Number(localStorage.getItem(`run-cursor:${run.id}`) || 0)
      : Number(explicitCursor);
    streamRuntimeRun(run.id, cursor, {
      onAbort: abort => { abortsRef.current[run.id] = abort; },
      onEvent: event => {
        applyRunEvent(run.id, event);
        const completed = (
          event.payload?.kind === "run.status" && event.payload.status === "succeeded"
        ) || (event.kind === "end" && event.payload?.status === "succeeded");
        if (run.kind !== "chat" && completed) {
          markViewedIfVisible(run.conversation_id);
        }
        if (event.payload?.kind === "run.created" && event.payload.run?.id) {
          subscribeRun(event.payload.run);
        }
      },
      onClose: () => { delete abortsRef.current[run.id]; },
      onError: () => { delete abortsRef.current[run.id]; },
    });
  }, [applyRunEvent, markViewedIfVisible]);

  const loadConversation = React.useCallback(async (conversationId) => {
    activeIdRef.current = conversationId;
    setActiveId(conversationId);
    setLoading(true);
    setError("");
    setCompressionFeedback("");
    Object.values(abortsRef.current).forEach(abort => abort());
    abortsRef.current = {};
    try {
      const [messages, runs, brief] = await Promise.all([
        getConversationMessages(conversationId),
        listRuns(conversationId),
        getActivePlanningBrief(conversationId),
      ]);
      const activeRuns = runs.filter(
        run => ["queued", "running", "waiting_user"].includes(run.status)
      );
      const eventHistories = await Promise.all(
        activeRuns.map(async run => [run.id, await getRunEvents(run.id, 0)])
      );
      let next = ChatState.initialState();
      messages.forEach(message => { next = ChatState.upsertMessage(next, message); });
      runs.forEach(run => {
        const previous = next.runs[run.id] || {};
        next.runs[run.id] = { ...previous, ...run };
      });
      if (brief) next.briefs[brief.id] = brief;
      eventHistories.forEach(([runId, events]) => {
        events.forEach(event => {
          next = ChatState.applyEvent(next, runId, event);
        });
        persistCursor(runId, next.cursors[runId]);
      });
      setState(next);
      setComposerTarget(null);
      setSidebarOpen(false);
      activeRuns.forEach(
        run => subscribeRun(run, next.cursors[run.id] || 0)
      );
      await markViewedIfVisible(conversationId);
    } catch (e) {
      setError(e.message || "加载对话失败");
    } finally {
      setLoading(false);
    }
  }, [subscribeRun, markViewedIfVisible]);

  React.useEffect(() => {
    if (!currentUsername) { onRequestLogin?.(); return; }
    let alive = true;
    listConversations().then(async items => {
      if (!alive) return;
      setConversations(items);
      if (items[0]) await loadConversation(items[0].id);
      else setLoading(false);
    }).catch(e => { setError(e.message); setLoading(false); });
    return () => {
      alive = false;
      Object.values(abortsRef.current).forEach(abort => abort());
    };
  }, [currentUsername]); // eslint-disable-line

  React.useEffect(() => {
    if (!currentUsername) return;
    let active = true;
    const refreshConversations = async () => {
      if (!ChatState.shouldPollConversations(document.visibilityState)) return;
      try {
        const items = await listConversations();
        if (active) setConversations(items);
      } catch {}
    };
    const handleVisibility = async () => {
      if (!ChatState.shouldPollConversations(document.visibilityState)) return;
      await markViewedIfVisible(activeId);
      await refreshConversations();
    };
    document.addEventListener("visibilitychange", handleVisibility);
    const timer = window.setInterval(refreshConversations, 4000);
    return () => {
      active = false;
      document.removeEventListener("visibilitychange", handleVisibility);
      window.clearInterval(timer);
    };
  }, [currentUsername, activeId, markViewedIfVisible]);

  const newConversation = async () => {
    try {
      const created = await createConversation("新的旅行对话");
      setConversations(previous => [created, ...previous]);
      await loadConversation(created.id);
    } catch (e) {
      setError(e.message || "暂时无法新建对话");
    }
  };

  React.useEffect(() => {
    if (typeof IntersectionObserver === "undefined") return;
    const observer = new IntersectionObserver(entries => {
      setVisibleRunIds(previous => {
        const next = new Set(previous);
        entries.forEach(entry => {
          const runId = entry.target.dataset.runId;
          if (entry.isIntersecting) next.add(runId);
          else next.delete(runId);
        });
        return next;
      });
      setObserverReady(true);
    }, { root: document.querySelector(".chat-feed"), threshold: 0.3 });
    Object.values(runNodesRef.current).filter(Boolean).forEach(node => observer.observe(node));
    return () => observer.disconnect();
  }, [activityItems.map(item => item.key).join("|")]);

  const send = async () => {
    const content = draft.trim();
    if (!content) return;
    if (composerTarget?.mode === "resume") {
      const run = composerTarget.run;
      const interaction = run.pending_interaction;
      if (!interaction?.interaction_id) return;
      setDraft("");
      setError("");
      try {
        const resumed = await resumeRuntimeRun(run.id, interaction.interaction_id, content);
        setState(previous => ({
          ...previous,
          runs: { ...previous.runs, [run.id]: { ...previous.runs[run.id], ...resumed } },
        }));
        setComposerTarget(null);
      } catch (e) {
        setDraft(content);
        setError(e.message || "回复提交失败，请重试");
      }
      return;
    }
    let conversationId = activeId;
    if (!conversationId) {
      const created = await createConversation(content.slice(0, 20));
      setConversations(previous => [created, ...previous]);
      conversationId = created.id;
      activeIdRef.current = conversationId;
      setActiveId(conversationId);
    }
    setDraft("");
    setError("");
    try {
      const context = composerTarget?.mode === "revision"
        ? { related_itinerary_id: composerTarget.itineraryId }
        : {};
      const result = await submitConversationMessage(conversationId, content, context);
      setConversations(previous => previous.map(item => (
        item.id === conversationId && (!item.title || item.title === "新的旅行对话")
          ? { ...item, title: content.slice(0, 24), updated_at: new Date().toISOString() }
          : item
      )));
      setState(previous => {
        let next = ChatState.upsertMessage(previous, result.message);
        next = { ...next, runs: { ...next.runs, [result.run.id]: result.run } };
        return next;
      });
      subscribeRun(result.run);
      setComposerTarget(null);
    } catch (e) {
      setDraft(content);
      setError(e.message || "发送失败");
    }
  };

  const refreshBrief = brief => {
    setState(previous => ({
      ...previous,
      briefs: { ...previous.briefs, [brief.id]: brief },
    }));
  };

  const submitBrief = async brief => {
    const result = await submitPlanningBrief(brief.id);
    refreshBrief(result.brief);
    setState(previous => ({
      ...previous,
      runs: { ...previous.runs, [result.run.id]: result.run },
    }));
    subscribeRun(result.run);
  };

  const discardBrief = async brief => {
    const result = await discardPlanningBrief(brief.id);
    refreshBrief(result);
  };

  const archiveCurrent = async () => {
    if (!activeConversation || conversationArchived) return;
    setError("");
    try {
      const archived = await archiveConversation(activeConversation.id);
      setConversations(previous => previous.map(item => item.id === archived.id ? { ...item, ...archived } : item));
      setComposerTarget(null);
      setDraft("");
    } catch (e) {
      setError(e.message || "归档失败，请重试");
    }
  };

  const compressCurrent = async () => {
    if (!activeConversation || conversationArchived || compressing) return;
    setCompressing(true);
    setCompressionFeedback("");
    setError("");
    try {
      const result = await compressConversation(activeConversation.id);
      setCompressionFeedback(result.compressed
        ? `已将较早对话整理到第 ${result.summarized_through_sequence} 条，最近 ${result.recent_turns_kept} 轮保持原文。`
        : `当前完整对话不足 ${result.recent_turns_kept + 1} 轮，暂时无需压缩。`);
    } catch (e) {
      setError(e.message || "主动压缩失败，原始消息没有变化");
    } finally {
      setCompressing(false);
    }
  };

  const retryMemory = async () => {
    if (!activeConversation) return;
    try {
      await retryConversationMemory(activeConversation.id);
      setConversations(previous => previous.map(item => item.id === activeConversation.id
        ? { ...item, finalization_status: "pending", memory_error_code: null }
        : item));
    } catch (e) {
      setError(e.message || "记忆整理重试失败");
    }
  };

  const controlRun = async (run, action) => {
    try {
      const result = action === "cancel"
        ? await cancelRuntimeRun(run.id)
        : await retryRuntimeRun(run.id);
      setState(previous => ({
        ...previous,
        runs: { ...previous.runs, [result.id]: result },
      }));
      if (action === "retry") subscribeRun(result);
    } catch (e) {
      setError(e.message || "操作失败");
    }
  };

  const focusRun = runId => {
    const node = runNodesRef.current[runId];
    if (!node) return;
    node.scrollIntoView({ behavior: "smooth", block: "center" });
    window.setTimeout(() => node.focus(), 350);
  };

  React.useEffect(() => {
    if (!loading && activeId && !composerTarget) composerRef.current?.focus();
  }, [loading, activeId]); // eslint-disable-line

  React.useEffect(() => {
    if (error) errorRef.current?.focus();
  }, [error]);

  React.useEffect(() => {
    const waiting = new Set(
      runList.filter(run => run.status === "waiting_user").map(run => run.id)
    );
    const newlyWaiting = [...waiting].find(id => !waitingRunsRef.current.has(id));
    waitingRunsRef.current = waiting;
    if (newlyWaiting) window.setTimeout(() => focusRun(newlyWaiting), 0);
  }, [runList.map(run => `${run.id}:${run.status}`).join("|")]); // eslint-disable-line

  const registerRunNode = (runId, node) => {
    if (node) runNodesRef.current[runId] = node;
    else delete runNodesRef.current[runId];
  };

  const offscreenRuns = observerReady
    ? activeRuns.filter(run => !visibleRunIds.has(run.id))
    : [];

  return (
    <div className="chat-shell page-fade">
      <aside className={`chat-sidebar ${sidebarOpen ? "open" : ""}`} aria-label="旅行对话列表">
        <div className="chat-sidebar-head">
          <div><small>MY JOURNEYS</small><strong>旅行对话</strong></div>
          <button onClick={newConversation} aria-label="创建新旅行对话">＋ 新对话</button>
        </div>
        <div className="conversation-list">
          {sidebarConversations.map(item => {
            const attention = ChatState.conversationAttention(item);
            const active = activeId === item.id;
            const ariaStatus = attention && attention.kind !== "archived"
              ? `，${attention.ariaLabel}` : attention?.ariaLabel ? `，${attention.ariaLabel}` : "";
            return (
              <button key={item.id}
                className={`conversation-item ${active ? "active" : ""} attention-${attention?.kind || "none"}`}
                aria-label={`${item.title || "未命名对话"}${ariaStatus}`}
                onClick={() => loadConversation(item.id)}>
                <span className="conversation-item-main">
                  <strong>{item.title || "未命名对话"}</strong>
                  {attention && attention.kind !== "archived" && (
                    <span className={`conversation-attention ${attention.kind}`} aria-label={attention.ariaLabel}>
                      {attention.kind === "planning" && <i className="conversation-spinner" aria-hidden="true" />}
                      {attention.kind === "unread" && <i className="conversation-unread-dot" aria-hidden="true" />}
                      {attention.label}
                    </span>
                  )}
                </span>
                <small>{new Date(item.updated_at).toLocaleDateString()}{attention?.kind === "archived" ? " · 已归档" : ""}</small>
              </button>
            );
          })}
        </div>
      </aside>
      <main className="chat-main">
        <div className="chat-header">
          <button className="chat-sidebar-toggle" onClick={() => setSidebarOpen(value => !value)}
            aria-expanded={sidebarOpen} aria-label="打开旅行对话列表">☰</button>
          <div className="chat-title-copy">
            <h2>和途途聊旅行</h2>
            <p>{conversationArchived ? "这段对话已归档，途途正在把有用的旅行习惯整理进画像。" : "问一个旅行问题，或把一个模糊念头慢慢变成可出发的行程。"}</p>
          </div>
          {activeConversation && !conversationArchived && (
            <div className="chat-memory-actions">
              {hasConversationMessages && <button className="chat-compress-btn" disabled={compressing} onClick={compressCurrent} aria-label="立即压缩较早的完整对话轮次">
                <span aria-hidden="true">≋</span>{compressing ? "正在压缩…" : "主动压缩"}
              </button>}
              <button className="chat-archive-btn" onClick={archiveCurrent}>归档对话</button>
            </div>
          )}
          {conversationArchived && (
            <span className={`memory-finalization ${activeConversation.finalization_status || "pending"}`}>
              {activeConversation.finalization_status === "succeeded" ? "记忆已整理" : activeConversation.finalization_status === "failed" ? "记忆整理失败" : "记忆整理中"}
            </span>
          )}
          <div className="chat-guide" role="img" aria-label="途途，旅行向导">
            <span className="guide-sun" aria-hidden="true" />
            <span className="guide-map" aria-hidden="true" />
            <span className="guide-hat" aria-hidden="true" />
            <span className="guide-face" aria-hidden="true"><i /><i /></span>
          </div>
          {activeRuns.length > 0 && <span className="chat-task-count">{activeRuns.length} 个旅程在进行</span>}
        </div>
        {compressionFeedback && <div className="chat-compression-feedback" role="status">
          <span aria-hidden="true">✓</span>{compressionFeedback}
        </div>}
        <div className="chat-feed" role="log" aria-label="旅行对话活动" aria-live="off">
          {loading && <div className="chat-empty">正在恢复对话…</div>}
          {!loading && activityItems.length === 0 && (
            <div className="chat-empty">
              <span className="chat-empty-kicker">START WITH A THOUGHT</span>
              <strong>从一个念头，走到一份行程</strong>
              <span>可以先随便问问，也可以直接告诉我你想去哪里。</span>
              <div className="chat-empty-prompts">
                <button onClick={() => setDraft("十月适合去云南吗？")}>聊聊灵感<small>十月适合去云南吗？</small></button>
                <button onClick={() => setDraft("帮我规划去云南旅行")}>开始规划<small>帮我规划去云南旅行</small></button>
              </div>
            </div>
          )}
          <ActivityTimeline
            items={activityItems}
            currentUsername={currentUsername}
            onBriefUpdate={refreshBrief}
            onBriefSubmit={submitBrief}
            onBriefDiscard={discardBrief}
            onRunCancel={run => controlRun(run, "cancel")}
            onRunRetry={run => controlRun(run, "retry")}
            onChatRetry={run => controlRun(run, "retry")}
            onRunOpen={run => run.result_itinerary_id && onOpenPlan?.(run.result_itinerary_id)}
            onRunModify={run => {
              setComposerTarget({
                mode: "revision",
                itineraryId: run.result_itinerary_id,
                label: `${run.request_snapshot?.destination || "这份行程"} · 继续修改`,
              });
              setDraft("");
            }}
            onRunReply={run => {
              setComposerTarget({ mode: "resume", run, label: `${run.request_snapshot?.destination || "规划任务"} · 回复` });
              setDraft("");
            }}
            registerRunNode={registerRunNode}
          />
        </div>
        <div className="chat-status-live" aria-live="polite" aria-atomic="true">
          {runList.find(run => run.status === "waiting_user")
            ? "有一项旅行规划需要你的回复"
            : runList.find(run => run.status === "failed")
              ? "有一项旅行规划未能完成"
              : ""}
        </div>
        {error && <div ref={errorRef} tabIndex="-1" className="chat-error" role="alert">{error}</div>}
        {offscreenRuns.length > 0 && (
          <div className="active-run-rail" aria-label="视口外的活动任务">
            {offscreenRuns.slice(0, 3).map(run => (
              <button key={run.id} onClick={() => focusRun(run.id)}>
                <span>{run.status === "waiting_user" ? "需要回复" : run.status === "queued" ? "等待开始" : "正在规划"}</span>
                <strong>{run.request_snapshot?.destination || (run.kind === "revision" ? "行程修改" : "旅行规划")}</strong>
                <span aria-hidden="true">↗</span>
              </button>
            ))}
          </div>
        )}
        <div className={`chat-composer-wrap ${conversationArchived ? "archived" : ""}`}>
          {conversationArchived ? (
            <div className="archived-conversation-note">
              <div><span>ARCHIVED</span><strong>这段旅途对话已经收好</strong><small>继续聊时会创建新对话，并使用已整理完成的最新记忆。</small></div>
              {activeConversation.finalization_status === "failed"
                ? <button onClick={retryMemory}>重新整理记忆</button>
                : <button onClick={newConversation}>开始新对话</button>}
            </div>
          ) : <>
          <div className="chat-composer">
            {composerTarget && (
              <div className="composer-target">
                <span>{composerTarget.mode === "resume" ? "正在回复任务" : "正在修改行程"}</span>
                <strong>{composerTarget.label}</strong>
                <button onClick={() => setComposerTarget(null)} aria-label="取消指定任务回复">×</button>
              </div>
            )}
            <textarea ref={composerRef} value={draft} onChange={e => setDraft(e.target.value)}
              aria-label={composerTarget ? composerTarget.label : "给途途发送消息"}
              placeholder={composerTarget?.mode === "resume" ? "补充所需信息…" : composerTarget?.mode === "revision" ? "说说你想怎么调整…" : "继续聊天，或描述一趟想规划的旅行…"}
              onKeyDown={e => {
                if (e.key === "Enter" && !e.shiftKey) {
                  e.preventDefault(); send();
                }
              }} />
            <button className="composer-send" onClick={send} disabled={!draft.trim()} aria-label="发送消息">
              <span aria-hidden="true">↑</span>
              <span className="composer-send-label">发送</span>
            </button>
          </div>
          <small className="composer-hint">{composerTarget ? "这条内容会发送到指定任务" : "规划会在后台继续，你可以放心离开或接着聊天"}</small>
          </>}
        </div>
      </main>
    </div>
  );
}

function ActivityTimeline({
  items, currentUsername,
  onBriefUpdate, onBriefSubmit, onBriefDiscard,
  onRunCancel, onRunRetry, onRunOpen, onRunModify, onRunReply, onChatRetry,
  registerRunNode,
}) {
  return items.map(item => {
    if (item.type === "message") {
      const message = item.entity;
      return (
        <article key={item.key} className={`chat-message ${message.role}`} aria-label={message.role === "user" ? "你的消息" : "途途的回复"}>
          <div className="chat-avatar" aria-hidden="true">{message.role === "user" ? currentUsername?.slice(-1) : "途"}</div>
          <div className="chat-bubble">
            {message.role === "assistant"
              ? <ChatMessageContent content={message.content} />
              : message.content}
            {message.streaming && <span className="typing-caret" aria-hidden="true" />}
          </div>
        </article>
      );
    }
    if (item.type === "brief") {
      return (
        <PlanningBriefCard
          key={item.key}
          brief={item.entity}
          onUpdate={onBriefUpdate}
          onSubmit={() => onBriefSubmit(item.entity)}
          onDiscard={() => onBriefDiscard(item.entity)}
        />
      );
    }
    if (item.type === "chat_thinking") {
      const isQueued = item.entity.status === "queued";
      return (
        <article key={item.key} className="chat-thinking" role="status" aria-live="polite">
          <div className="chat-avatar" aria-hidden="true">途</div>
          <div className="chat-thinking-body">
            <span className="chat-thinking-kicker">{isQueued ? "收到，正在接住这句话" : "途途正在思考"}</span>
            <strong>{isQueued ? "正在准备理解你的旅行想法…" : "正在梳理目的地、日期和你的偏好…"}</strong>
            <span className="chat-thinking-dots" aria-hidden="true"><i /><i /><i /></span>
          </div>
        </article>
      );
    }
    if (item.type === "chat_failure") {
      const run = item.entity;
      return (
        <section key={item.key} className="chat-understanding-failure" role="alert">
          <strong>这条消息暂时没有理解成功</strong>
          <p>{run.error_public?.message || "请重试"}</p>
          <button onClick={() => onChatRetry(run)}>重试这条消息</button>
        </section>
      );
    }
    const run = item.entity;
    return (
      <RuntimeRunCard
        key={item.key}
        refNode={node => registerRunNode(run.id, node)}
        run={run}
        onCancel={() => onRunCancel(run)}
        onRetry={() => onRunRetry(run)}
        onOpen={() => onRunOpen(run)}
        onModify={() => onRunModify(run)}
        onReply={() => onRunReply(run)}
      />
    );
  });
}

function ChatMessageContent({ content }) {
  const renderInline = (text, keyPrefix) => {
    const parts = String(text || "").split(/(\*\*[^*]+\*\*)/g);
    return parts.map((part, index) => {
      const match = part.match(/^\*\*(.+)\*\*$/);
      return match
        ? <strong key={`${keyPrefix}-${index}`}>{match[1]}</strong>
        : <React.Fragment key={`${keyPrefix}-${index}`}>{part}</React.Fragment>;
    });
  };

  const lines = String(content || "").split(/\r?\n/);
  return (
    <div className="chat-message-content">
      {lines.map((line, index) => {
        const trimmed = line.trim();
        if (!trimmed) return <span className="chat-message-space" key={index} aria-hidden="true" />;
        const numberedHeading = trimmed.match(/^\*\*(\d+\.\s+.+)\*\*$/);
        if (numberedHeading) {
          return <h4 key={index}>{numberedHeading[1]}</h4>;
        }
        if (/^[-•]\s+/.test(trimmed)) {
          return (
            <div className="chat-message-list-item" key={index}>
              <span aria-hidden="true">•</span>
              <p>{renderInline(trimmed.replace(/^[-•]\s+/, ""), `line-${index}`)}</p>
            </div>
          );
        }
        return <p key={index}>{renderInline(trimmed, `line-${index}`)}</p>;
      })}
    </div>
  );
}

function PlanningBriefCard({ brief, onUpdate, onSubmit, onDiscard }) {
  const [editing, setEditing] = React.useState(false);
  const [form, setForm] = React.useState(brief.data || {});
  const [busy, setBusy] = React.useState("");
  const [localError, setLocalError] = React.useState("");
  const editable = ["collecting", "ready"].includes(brief.status);
  React.useEffect(() => setForm(brief.data || {}), [brief.data]);
  const constraints = form.trip_constraints || [];
  const excludedIds = form.excluded_memory_fact_ids || [];
  const memory = brief.memory_context || { status: "none", applied_facts: [], excluded_facts: [] };
  const makeConstraint = () => ({
    id: (window.crypto?.randomUUID?.() || `constraint-${Date.now()}`),
    category: "other_travel_preference", value_text: "", polarity: "fact", source: "manual",
  });
  const persistForm = async () => {
    const updated = await updatePlanningBrief(brief.id, {
      destination: form.destination ?? "",
      start_date: form.start_date ?? "",
      end_date: form.end_date ?? "",
      days: form.days === "" ? null : Number(form.days),
      trip_budget: form.trip_budget ?? form.budget ?? "",
      trip_constraints: constraints.filter(item => item.value_text?.trim()).map(item => ({
        ...item, value_text: item.value_text.trim(), source: item.source || "manual",
      })),
      excluded_memory_fact_ids: excludedIds,
    });
    onUpdate(updated);
    return updated;
  };
  const save = async () => {
    setBusy("save"); setLocalError("");
    try {
      await persistForm();
      setEditing(false);
    } catch (e) {
      setLocalError(e.message || "需求保存失败");
    } finally {
      setBusy("");
    }
  };
  const saveAndSubmit = async () => {
    if (busy) return;
    setBusy("submit"); setLocalError("");
    try {
      const current = editing ? await persistForm() : brief;
      if (current.status !== "ready") {
        setEditing(true);
        setLocalError("信息尚未完整，请补齐提示的内容后再开始规划。");
        return;
      }
      setEditing(false);
      await onSubmit(current);
    } catch (e) {
      setLocalError(e.message || "保存或创建规划任务失败，请重试");
    } finally {
      setBusy("");
    }
  };
  const fields = [
    ["destination", "目的地", "text"],
    ["start_date", "开始日期", "date"],
    ["end_date", "结束日期", "date"],
    ["days", "天数", "number"],
    ["trip_budget", "本次预算", "text"],
  ];
  const view = ChatState.briefViewModel(brief);
  const runAction = async (name, action) => {
    if (busy) return;
    setBusy(name); setLocalError("");
    try { await action(); }
    catch (e) { setLocalError(e.message || "操作失败，请重试"); }
    finally { setBusy(""); }
  };
  const updateMemoryExclusions = async factId => {
    const nextIds = excludedIds.includes(factId)
      ? excludedIds.filter(id => id !== factId)
      : [...excludedIds, factId];
    setBusy(`memory-${factId}`); setLocalError("");
    try {
      const updated = await updatePlanningBrief(brief.id, { excluded_memory_fact_ids: nextIds });
      onUpdate(updated);
    } catch (e) { setLocalError(e.message || "本次记忆设置保存失败"); }
    finally { setBusy(""); }
  };
  const refreshMemory = async () => {
    setBusy("memory-refresh"); setLocalError("");
    try { onUpdate(await refreshPlanningBriefMemory(brief.id)); }
    catch (e) { setLocalError(e.message || "长期记忆重新匹配失败"); }
    finally { setBusy(""); }
  };
  return (
    <section className={`brief-card ${brief.status}`} aria-labelledby={`brief-title-${brief.id}`}>
      <div className="brief-head">
        <div>
          <span>TRIP NOTE</span>
          <strong id={`brief-title-${brief.id}`}>这趟旅行，我理解的是</strong>
        </div>
        <em>{ChatState.planningBriefStatusLabel(brief.status)}</em>
        {editable && (
          <button disabled={!!busy} onClick={() => setEditing(value => !value)}>{editing ? "收起编辑" : "调整"}</button>
        )}
      </div>
      {editing ? (
        <div className="brief-grid">
          {fields.map(([key, label, type]) => (
            <label key={key}>{label}
              <input
                type={type}
                value={form[key] || ""}
                onChange={e => setForm({ ...form, [key]: e.target.value })}
              />
            </label>
          ))}
          <div className="brief-constraint-editor">
            <div className="brief-constraint-title"><strong>本次旅行要求</strong><span>来自当前对话或你的手动调整</span></div>
            {constraints.map((item, index) => (
              <div className="brief-constraint-row" key={item.id || index}>
                <select value={item.category} onChange={e => setForm({ ...form, trip_constraints: constraints.map((entry, i) => i === index ? { ...entry, category: e.target.value } : entry) })}>
                  {Object.entries(MEMORY_CATEGORY_LABELS).filter(([key]) => key !== "destination_history").map(([key, label]) => <option key={key} value={key}>{label}</option>)}
                </select>
                <select value={item.polarity || "fact"} onChange={e => setForm({ ...form, trip_constraints: constraints.map((entry, i) => i === index ? { ...entry, polarity: e.target.value } : entry) })}>
                  {Object.entries(MEMORY_POLARITY_LABELS).map(([key, label]) => <option key={key} value={key}>{label}</option>)}
                </select>
                <input value={item.value_text || ""} placeholder="例如：每天最多安排三个景点" onChange={e => setForm({ ...form, trip_constraints: constraints.map((entry, i) => i === index ? { ...entry, value_text: e.target.value } : entry) })} />
                <button type="button" aria-label="移除这条本次要求" onClick={() => setForm({ ...form, trip_constraints: constraints.filter((_, i) => i !== index) })}>×</button>
              </div>
            ))}
            <button type="button" className="brief-add-constraint" onClick={() => setForm({ ...form, trip_constraints: [...constraints, makeConstraint()] })}>＋ 添加一条本次要求</button>
          </div>
          <button className="brief-save" disabled={!!busy} onClick={save}>{busy === "save" ? "保存中…" : "保存这份理解"}</button>
        </div>
      ) : (
        <div className="brief-summary">
          <div className="brief-destination">
            <span>目的地</span>
            <strong>{view.destination}</strong>
          </div>
          <div className="brief-date">
            <span>出行时间</span>
            <strong>{view.dateLabel}</strong>
          </div>
          {view.preferences.length > 0 && (
            <dl className="brief-preferences">
              {view.preferences.map(([label, value]) => <div key={`${label}:${value}`}><dt>{label}</dt><dd>{value}</dd></div>)}
            </dl>
          )}
          {view.usesDefaults && (
            <p className="brief-defaults">没有特别说明的预算、餐饮或节奏偏好，将采用舒适均衡的推荐方案。</p>
          )}
        </div>
      )}
      {(memory.applied_facts?.length > 0 || memory.excluded_facts?.length > 0 || memory.status === "failed") && (
        <div className="brief-memory-panel">
          <div className="brief-memory-head">
            <div><span>LONG-TERM MEMORY</span><strong>这次自动带入的旅行记忆</strong><small>记忆版本 {memory.revision || 0}</small></div>
            {editable && <button disabled={!!busy} onClick={refreshMemory}>{busy === "memory-refresh" ? "匹配中…" : "重新匹配"}</button>}
          </div>
          {memory.status === "failed" && <p className="brief-memory-warning">长期记忆暂时没有匹配成功。本次明确需求仍会保留，你可以重试或直接继续规划。</p>}
          {!!memory.applied_facts?.length && <div className="brief-memory-list">{memory.applied_facts.map(fact => {
            const presentation = ChatState.memoryFactPresentation(fact);
            return (
              <div className={`brief-memory-fact polarity-${presentation.tone}`} key={fact.fact_id}>
                <div className="brief-memory-copy">
                  <span>{MEMORY_CATEGORY_LABELS[fact.category] || "旅行记忆"} · {MEMORY_SCOPE_LABELS[fact.scope_type] || fact.scope_type}</span>
                  <div className="brief-memory-decision"><b>{presentation.badge}</b><strong>{fact.value_text}</strong></div>
                  <small>{presentation.effect}</small>
                </div>
                <em>来自长期记忆</em>
                {editable && <button disabled={!!busy} aria-label={`${presentation.excludeAction}：${fact.value_text}`} onClick={() => updateMemoryExclusions(fact.fact_id)}>{presentation.excludeAction}</button>}
              </div>
            );
          })}</div>}
          {!!memory.excluded_facts?.length && <details className="brief-memory-excluded"><summary>本次已停用的记忆（{memory.excluded_facts.length}）</summary>{memory.excluded_facts.map(fact => {
            const presentation = ChatState.memoryFactPresentation(fact);
            return (
              <div key={fact.fact_id}>
                <span><b>{presentation.badge}</b>{fact.value_text}</span>
                {editable && <button disabled={!!busy} aria-label={`${presentation.restoreAction}：${fact.value_text}`} onClick={() => updateMemoryExclusions(fact.fact_id)}>{presentation.restoreAction}</button>}
              </div>
            );
          })}</details>}
          <p className="brief-memory-footnote">这里只影响本次旅行；如需彻底忘记，请前往“我的画像”。</p>
        </div>
      )}
      {brief.missing_fields?.length > 0 && (
        <div className="brief-missing">
          <span>下一步只需要</span>
          <strong>{view.missing.join("、")}</strong>
        </div>
      )}
      {localError && <p className="brief-error" role="alert">{localError}</p>}
      <div className="brief-actions">
        {editable ? (
          <>
            <button className="brief-discard" disabled={!!busy}
              onClick={() => runAction("discard", onDiscard)}>
              {busy === "discard" ? "清除中…" : "清除这份需求"}
            </button>
            <button className="brief-submit" disabled={(!editing && brief.status !== "ready") || !!busy}
              onClick={saveAndSubmit}>
              {busy === "submit" ? "正在保存并创建任务…" : editing ? "保存并开始规划" : "确认，开始规划"}
            </button>
          </>
        ) : (
          <span className="brief-submitted-note">正式规划任务已创建</span>
        )}
      </div>
    </section>
  );
}

function StructuredInteractionInput({ interaction, disabled, onSubmit }) {
  const schema = interaction?.input_schema || {};
  const question = interaction?.question || "";
  const inputKind = ChatState.interactionInputKind(interaction);
  const isDateRange = inputKind === "date-range";
  const choices = Array.isArray(schema.enum) ? schema.enum : [];
  const multiChoices = schema.type === "array" && Array.isArray(schema.items?.enum)
    ? schema.items.enum : [];
  const [text, setText] = React.useState("");
  const [startDate, setStartDate] = React.useState("");
  const [endDate, setEndDate] = React.useState("");
  const [selected, setSelected] = React.useState([]);
  const [inputError, setInputError] = React.useState("");
  const submit = () => {
    let value = text.trim();
    if (isDateRange) {
      if (!startDate || !endDate) { setInputError("请选择开始和结束日期"); return; }
      if (endDate < startDate) { setInputError("结束日期不能早于开始日期"); return; }
      value = `${startDate} 至 ${endDate}`;
    } else if (choices.length) {
      if (!text) { setInputError("请选择一个选项"); return; }
      value = text;
    } else if (multiChoices.length) {
      if (!selected.length) { setInputError("请至少选择一项"); return; }
      value = selected;
    }
    if (!value || (Array.isArray(value) && !value.length)) { setInputError("请补充信息后继续"); return; }
    setInputError("");
    onSubmit(value);
  };
  return (
    <div className="interaction-input">
      {isDateRange ? (
        <div className="date-range-input">
          <label>开始日期<input type="date" value={startDate} onChange={e => setStartDate(e.target.value)} /></label>
          <span aria-hidden="true">→</span>
          <label>结束日期<input type="date" value={endDate} onChange={e => setEndDate(e.target.value)} /></label>
        </div>
      ) : choices.length ? (
        <div className="choice-input" role="radiogroup" aria-label={question}>
          {choices.map(choice => (
            <label key={choice}><input type="radio" name={`interaction-${interaction.interaction_id}`}
              checked={text === choice} onChange={() => setText(choice)} />{choice}</label>
          ))}
        </div>
      ) : multiChoices.length ? (
        <div className="choice-input" aria-label={question}>
          {multiChoices.map(choice => (
            <label key={choice}><input type="checkbox" checked={selected.includes(choice)}
              onChange={() => setSelected(values => values.includes(choice) ? values.filter(item => item !== choice) : [...values, choice])} />{choice}</label>
          ))}
        </div>
      ) : (
        <textarea value={text} onChange={e => setText(e.target.value)} placeholder="补充信息后继续" aria-label="任务所需补充信息" />
      )}
      {inputError && <p className="interaction-error" role="alert">{inputError}</p>}
      <button className="run-primary" disabled={disabled} onClick={submit}>{disabled ? "提交中…" : "提交并继续规划"}</button>
    </div>
  );
}

function RuntimeRunCard({ run, onCancel, onRetry, onOpen, onModify, onReply, refNode }) {
  const [busy, setBusy] = React.useState("");
  const [resultSummary, setResultSummary] = React.useState(null);
  const [localError, setLocalError] = React.useState("");
  const presentation = ChatState.RUN_PRESENTATIONS[run.status] || {
    label: run.status, copy: "", primaryAction: null,
  };
  const interaction = run.pending_interaction;
  const target = run.request_snapshot?.destination
    || (run.kind === "revision" ? "已有行程" : "新的旅行");
  const journeyIndex = run.status === "succeeded"
    ? JOURNEY_STEPS.length - 1
    : Math.max(-1, Number(run.journey_step_index ?? -1));
  const journeyActiveNode = run.status === "succeeded"
    ? null
    : JOURNEY_STEPS[journeyIndex]?.key;
  const journeyDoneNodes = run.status === "succeeded"
    ? JOURNEY_STEPS.map(step => step.key)
    : JOURNEY_STEPS.slice(0, Math.max(0, journeyIndex)).map(step => step.key);
  const planningHeadings = {
    queued: `正在准备 ${target} 的规划`,
    running: `正在为你规划 ${target} 之旅`,
    waiting_user: `${target} 的规划等你补充`,
    succeeded: `${target} 的行程已经准备好`,
    failed: `${target} 的规划暂未完成`,
    cancelled: `${target} 的规划已停止`,
  };
  const revisionHeadings = {
    queued: `正在准备修改 ${target} 行程`,
    running: `正在修改 ${target} 行程`,
    waiting_user: `${target} 行程修改等你补充`,
    succeeded: `${target} 的新版行程已准备好`,
    failed: `${target} 行程修改暂未完成`,
    cancelled: `${target} 行程修改已停止`,
  };
  const heading = (run.kind === "revision" ? revisionHeadings : planningHeadings)[run.status]
    || `${target} · ${presentation.label}`;
  React.useEffect(() => {
    if (run.status !== "succeeded" || !run.result_itinerary_id || resultSummary) return;
    let alive = true;
    getHistoryItem(run.result_itinerary_id).then(data => {
      if (!alive || !data) return;
      const plan = data.plan || data;
      setResultSummary({
        destination: plan.destination || run.request_snapshot?.destination || "旅行行程",
        days: Array.isArray(plan.days) ? plan.days.length : (plan.days || run.request_snapshot?.days),
        startDate: plan.travel_start_date || plan.start_date || run.request_snapshot?.start_date,
        endDate: plan.travel_end_date || plan.end_date || run.request_snapshot?.end_date,
      });
    }).catch(() => {});
    return () => { alive = false; };
  }, [run.status, run.result_itinerary_id]); // eslint-disable-line
  const action = async (name, fn) => {
    if (busy) return;
    setBusy(name); setLocalError("");
    try { await fn(); }
    catch (e) { setLocalError(e.message || "操作失败，请重试"); }
    finally { setBusy(""); }
  };
  return (
    <section ref={refNode} data-run-id={run.id} tabIndex="-1"
      className={`run-card status-${run.status}`} aria-labelledby={`run-title-${run.id}`}>
      <div className="run-journey-head">
        <div>
          <span>{run.kind === "revision" ? "ITINERARY REVISION" : "MULTI-AGENT JOURNEY"}</span>
          <h3 id={`run-title-${run.id}`}>{heading}</h3>
        </div>
        <strong className="run-status-badge">{presentation.label}</strong>
      </div>
      <p className="run-status-copy">{presentation.copy}</p>
      {["queued", "running", "waiting_user", "succeeded"].includes(run.status) && (
        <div className="run-journey-progress" aria-label="规划进度">
          <div className="run-journey-scene" aria-hidden="true">
            <JourneyLoading
              steps={JOURNEY_STEPS}
              activeNode={journeyActiveNode}
              doneNodes={journeyDoneNodes}
            />
          </div>
          <div className="run-journey-steps">
            {JOURNEY_STEPS.map((step, index) => {
              const complete = run.status === "succeeded" || index < journeyIndex;
              const active = run.status !== "succeeded" && index === journeyIndex;
              return (
                <div key={step.key} className={`run-journey-step ${complete ? "done" : ""} ${active ? "active" : ""}`}>
                  <span className="run-journey-marker">{complete ? "✓" : index + 1}</span>
                  <span>
                    <strong>{step.label}</strong>
                    <small>{
                      complete
                        ? (step.doneDetail || step.detail)
                        : active && run.latest_progress_label
                          ? run.latest_progress_label
                          : step.detail
                    }</small>
                  </span>
                </div>
              );
            })}
          </div>
        </div>
      )}
      {run.request_snapshot?.related_itinerary_id && (
        <p className="run-context">这是一项针对已有行程的独立修改，不会覆盖原版本。</p>
      )}
      {run.retry_of_run_id && <p className="run-context">这是上一次未完成任务的新尝试，原任务记录仍然保留。</p>}
      {run.error_public?.message && <p className="run-error" role="alert">{run.error_public.message}</p>}
      {run.status === "waiting_user" && interaction?.question && (
        <div className="run-question">
          <span>规划需要确认一件事</span>
          <strong>{interaction.question}</strong>
          <StructuredInteractionInput interaction={interaction} disabled={busy === "resume"}
            onSubmit={value => action("resume", async () => {
              await resumeRuntimeRun(run.id, interaction.interaction_id, value);
            })} />
          <button className="run-inline-reply" onClick={onReply}>也可以在下方输入框回复</button>
        </div>
      )}
      {run.status === "succeeded" && (
        <div className="run-result-preview">
          <span>YOUR ITINERARY</span>
          <strong>{resultSummary?.destination || target}</strong>
          <p>
            {resultSummary?.days ? `${resultSummary.days} 天` : "完整行程"}
            {resultSummary?.startDate && resultSummary?.endDate ? ` · ${resultSummary.startDate} — ${resultSummary.endDate}` : ""}
          </p>
          <small>路线、开放时间、餐饮与游玩提示已整理</small>
        </div>
      )}
      {localError && <p className="run-error" role="alert">{localError}</p>}
      <div className="run-actions">
        {["queued", "running", "waiting_user"].includes(run.status) && (
          <button className="run-secondary" disabled={!!busy} onClick={() => action("cancel", onCancel)}>
            {busy === "cancel" ? "正在停止…" : "停止规划"}
          </button>
        )}
        {["failed", "cancelled"].includes(run.status) && (
          <button className="run-primary" disabled={!!busy} onClick={() => action("retry", onRetry)}>
            {busy === "retry" ? "正在创建新任务…" : "使用原需求再试一次"}
          </button>
        )}
        {run.status === "succeeded" && run.result_itinerary_id && (
          <>
            <button className="run-secondary" onClick={onModify}>继续修改</button>
            <button className="run-primary" onClick={onOpen}>打开完整行程</button>
          </>
        )}
      </div>
    </section>
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
  const activeProfileFacts = profile?.active_facts || [];
  const profileRows = profile ? [
    { key: "attr", label: "景点", cls: "attr", items: activeProfileFacts.filter(item => item.category === "attraction_preference").map(item => item.value_text) },
    { key: "food", label: "餐饮", cls: "food", items: activeProfileFacts.filter(item => ["food_preference", "dietary_requirement"].includes(item.category)).map(item => item.value_text) },
    { key: "habit", label: "习惯", cls: "habit", items: activeProfileFacts.filter(item => ["travel_pace", "transport_preference", "schedule_preference"].includes(item.category)).map(item => item.value_text) },
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

const MEMORY_CATEGORY_LABELS = {
  attraction_preference: "旅行主题", food_preference: "餐饮偏好", dietary_requirement: "饮食要求",
  travel_pace: "旅行节奏", budget_style: "预算习惯", transport_preference: "交通偏好",
  accommodation_preference: "住宿偏好", schedule_preference: "时间习惯", companion_context: "同行情境",
  accessibility_need: "无障碍需求", destination_history: "去过的地方", other_travel_preference: "其他偏好",
};
const MEMORY_POLARITY_LABELS = { prefer: "喜欢", avoid: "避开", require: "需要", fact: "事实" };
const MEMORY_SCOPE_LABELS = { global: "所有旅行", destination: "特定目的地", companion: "特定同行人", destination_companion: "目的地与同行人" };

function MemoryFactCard({ fact, candidate = false, onChanged }) {
  const [editing, setEditing] = React.useState(false);
  const [value, setValue] = React.useState(fact.value_text);
  const [category, setCategory] = React.useState(fact.category);
  const [polarity, setPolarity] = React.useState(fact.polarity);
  const [scopeType, setScopeType] = React.useState(fact.scope_type);
  const [destination, setDestination] = React.useState(fact.scope_key?.destination || "");
  const [companion, setCompanion] = React.useState(fact.scope_key?.companion || "");
  const [busy, setBusy] = React.useState(false);
  const scopeDetail = Object.values(fact.scope_key || {}).filter(Boolean).join(" · ");
  const run = async action => {
    setBusy(true);
    try { await action(); await onChanged(); setEditing(false); }
    catch (e) { alert(e.message || "操作失败"); }
    finally { setBusy(false); }
  };
  return (
    <article className={`memory-fact-card ${candidate ? "candidate" : "active"}`}>
      <div className="memory-fact-mark" aria-hidden="true">{candidate ? "?" : "✓"}</div>
      <div className="memory-fact-body">
        <div className="memory-fact-meta">
          <span>{MEMORY_CATEGORY_LABELS[fact.category] || fact.category}</span>
          <em>{MEMORY_POLARITY_LABELS[fact.polarity] || fact.polarity}</em>
          <small>{MEMORY_SCOPE_LABELS[fact.scope_type] || fact.scope_type}{scopeDetail ? ` · ${scopeDetail}` : ""}</small>
        </div>
        {editing ? (
          <div className="memory-inline-edit">
            <select value={category} onChange={e => setCategory(e.target.value)}>{Object.entries(MEMORY_CATEGORY_LABELS).map(([key, label]) => <option key={key} value={key}>{label}</option>)}</select>
            <select value={polarity} onChange={e => setPolarity(e.target.value)}>{Object.entries(MEMORY_POLARITY_LABELS).map(([key, label]) => <option key={key} value={key}>{label}</option>)}</select>
            <select value={scopeType} onChange={e => setScopeType(e.target.value)}>{Object.entries(MEMORY_SCOPE_LABELS).map(([key, label]) => <option key={key} value={key}>{label}</option>)}</select>
            {(scopeType === "destination" || scopeType === "destination_companion") && <input value={destination} onChange={e => setDestination(e.target.value)} placeholder="目的地，例如：日本" />}
            {(scopeType === "companion" || scopeType === "destination_companion") && <input value={companion} onChange={e => setCompanion(e.target.value)} placeholder="同行情境，例如：带孩子" />}
            <input value={value} onChange={e => setValue(e.target.value)} autoFocus />
            <button disabled={busy || !value.trim() || ((scopeType === "destination" || scopeType === "destination_companion") && !destination.trim()) || ((scopeType === "companion" || scopeType === "destination_companion") && !companion.trim())} onClick={() => run(() => updateMemoryFact(fact.id, {
              category, value_text: value.trim(), polarity, scope_type: scopeType,
              scope_key: scopeType === "global" ? {} : {
                ...(scopeType === "destination" || scopeType === "destination_companion" ? { destination: destination.trim() } : {}),
                ...(scopeType === "companion" || scopeType === "destination_companion" ? { companion: companion.trim() } : {}),
              },
            }))}>保存</button>
            <button disabled={busy} onClick={() => { setValue(fact.value_text); setEditing(false); }}>取消</button>
          </div>
        ) : <strong>{fact.value_text}</strong>}
        <p>{candidate ? (fact.sensitivity === "protected" ? "这条信息较敏感，确认后才会用于新的旅行对话。" : "途途从对话中推测了这条习惯，请你确认。") : `来源：${fact.source_kind === "manual" ? "你手动添加" : fact.source_kind === "legacy" ? "旧画像迁移" : "旅行对话"}`}</p>
      </div>
      <div className="memory-fact-actions">
        {candidate && <button className="memory-approve" disabled={busy} onClick={() => run(() => approveMemoryFact(fact.id))}>确认记住</button>}
        {!editing && <button disabled={busy} onClick={() => setEditing(true)}>{candidate ? "编辑并确认" : "编辑"}</button>}
        <button className="memory-forget" disabled={busy} onClick={() => run(() => deleteMemoryFact(fact.id))}>{candidate ? "忽略" : "忘记"}</button>
      </div>
    </article>
  );
}

function ProfilePage({ currentUsername }) {
  const [profile, setProfile] = React.useState({ revision: 0, active_facts: [], candidate_facts: [], trip_count: 0 });
  const [loading, setLoading] = React.useState(true);
  const [form, setForm] = React.useState({ category: "attraction_preference", value_text: "", polarity: "prefer", scope_type: "global", destination: "", companion: "" });
  const [adding, setAdding] = React.useState(false);
  const refreshProfile = async () => {
    try {
      const data = await getProfile();
      if (data) setProfile(data);
    } catch {}
  };

  React.useEffect(() => {
    refreshProfile().finally(() => setLoading(false));
    const onVisible = () => { if (!document.hidden) refreshProfile(); };
    window.addEventListener("focus", onVisible);
    document.addEventListener("visibilitychange", onVisible);
    return () => {
      window.removeEventListener("focus", onVisible);
      document.removeEventListener("visibilitychange", onVisible);
    };
  }, []);
  const addFact = async e => {
    e.preventDefault();
    if (!form.value_text.trim()) return;
    setAdding(true);
    try {
      const scope_key = form.scope_type === "global" ? {} : {
        ...(form.scope_type === "destination" || form.scope_type === "destination_companion" ? { destination: form.destination.trim() } : {}),
        ...(form.scope_type === "companion" || form.scope_type === "destination_companion" ? { companion: form.companion.trim() } : {}),
      };
      const { destination, companion, ...payload } = form;
      await createMemoryFact({ ...payload, value_text: form.value_text.trim(), scope_key });
      setForm(previous => ({ ...previous, value_text: "", destination: "", companion: "" }));
      await refreshProfile();
    } catch (e) { alert(e.message || "添加失败"); }
    finally { setAdding(false); }
  };

  const username = currentUsername || getAuth()?.username || "旅行者";
  const cityCount = profile.active_facts.filter(item => item.category === "destination_history").length;
  const groups = Object.entries(profile.active_facts.reduce((acc, fact) => {
    const key = MEMORY_CATEGORY_LABELS[fact.category] || "其他记忆";
    (acc[key] ||= []).push(fact); return acc;
  }, {}));

  return (
    <div className="page page-fade">
      <div className="mag-head">
        <div>
          <div className="eyebrow">PROFILE · 旅行画像</div>
          <h1>我的旅行画像</h1>
        </div>
        <div className="head-note">只把你确认过的旅行习惯<br />带进下一段对话</div>
      </div>

      <div className="profile-grid">
        <aside className="profile-aside">
          <div style={{ display: "grid", placeItems: "center" }}>
            <Mascot size={120} pose="idle" />
          </div>
          <div className="pa-name">{username}</div>
          <div className="pa-sub">记忆版本 {profile.revision} · 每段对话都会冻结一份独立快照</div>
          <div className="pa-stats">
            <div className="pa-stat"><div className="ps-n">{profile.trip_count}</div><div className="ps-l">趟旅程</div></div>
            <div className="pa-stat"><div className="ps-n">{cityCount}</div><div className="ps-l">座城市</div></div>
            <div className="pa-stat">
              <div className="ps-n">{profile.active_facts.length}</div><div className="ps-l">条记忆</div>
            </div>
          </div>
        </aside>

        <div>
          <form className="memory-add-card" onSubmit={addFact}>
            <div><span>ADD A MEMORY</span><strong>告诉途途一条稳定的旅行习惯</strong></div>
            <div className="memory-add-grid">
              <select value={form.category} onChange={e => setForm({ ...form, category: e.target.value })}>{Object.entries(MEMORY_CATEGORY_LABELS).map(([key, label]) => <option key={key} value={key}>{label}</option>)}</select>
              <select value={form.polarity} onChange={e => setForm({ ...form, polarity: e.target.value })}>{Object.entries(MEMORY_POLARITY_LABELS).map(([key, label]) => <option key={key} value={key}>{label}</option>)}</select>
              <select value={form.scope_type} onChange={e => setForm({ ...form, scope_type: e.target.value })}>{Object.entries(MEMORY_SCOPE_LABELS).map(([key, label]) => <option key={key} value={key}>{label}</option>)}</select>
              {(form.scope_type === "destination" || form.scope_type === "destination_companion") && <input value={form.destination} onChange={e => setForm({ ...form, destination: e.target.value })} placeholder="目的地，例如：日本" required />}
              {(form.scope_type === "companion" || form.scope_type === "destination_companion") && <input value={form.companion} onChange={e => setForm({ ...form, companion: e.target.value })} placeholder="同行情境，例如：带孩子" required />}
              <input className="memory-value-input" value={form.value_text} onChange={e => setForm({ ...form, value_text: e.target.value })} placeholder="例如：旅行时通常喜欢慢节奏，每天不超过三个景点" />
              <button disabled={adding || !form.value_text.trim()}>{adding ? "正在记住…" : "记住这条"}</button>
            </div>
          </form>
          {loading ? <div className="memory-loading">正在翻开你的旅行档案…</div> : <>
            {profile.candidate_facts.length > 0 && <section className="memory-section candidate-section"><header><span>NEEDS YOUR WORD</span><h2>待你确认</h2><p>推断或较敏感的信息不会自动用于新对话。</p></header><div className="memory-fact-list">{profile.candidate_facts.map(fact => <MemoryFactCard key={fact.id} fact={fact} candidate onChanged={refreshProfile} />)}</div></section>}
            <section className="memory-section"><header><span>TRAVEL MEMORY</span><h2>途途已经记住</h2><p>当前对话不会中途刷新；这些变化会从下一段新对话开始生效。</p></header>
              {groups.length ? groups.map(([label, facts]) => <div className="memory-group" key={label}><h3>{label}<small>{facts.length}</small></h3><div className="memory-fact-list">{facts.map(fact => <MemoryFactCard key={fact.id} fact={fact} onChanged={refreshProfile} />)}</div></div>) : <div className="memory-empty">还没有长期旅行记忆。你可以先添加一条，或在聊完后归档对话。</div>}
            </section>
          </>}
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

/* ── 首页（产品介绍落地页） ──────────────────────── */
function HomePage({ onStart }) {
  const videoRef = React.useRef(null);

  // 自动播放兜底：标签 autoplay 在部分浏览器被拦截时，手动 play；返回前台/首次交互再试
  React.useEffect(() => {
    const play = () => { videoRef.current?.play?.().catch(() => {}); };
    play();
    const onVisible = () => { if (!document.hidden) play(); };
    const onPointer = () => { play(); };
    document.addEventListener("visibilitychange", onVisible);
    window.addEventListener("pointerdown", onPointer, { once: true });
    return () => {
      document.removeEventListener("visibilitychange", onVisible);
      window.removeEventListener("pointerdown", onPointer);
    };
  }, []);

  const viewAbilities = () =>
    document.getElementById("home-abilities")?.scrollIntoView({ behavior: "smooth", block: "start" });

  return (
    <div className="home-page page-fade">
      <main className="hero-shell">
        <div className="video-poster" aria-hidden="true"></div>
        <video
          ref={videoRef}
          className="hero-video"
          autoPlay loop muted playsInline preload="auto"
          poster="https://images.unsplash.com/photo-1557683316-973673baf926?w=1600&q=60"
        >
          <source src="https://d8j0ntlcm91z4.cloudfront.net/user_38xzZboKViGWJOttwIXH07lWA1P/hf_20260424_064411_9e9d7f84-9277-41f4-ab10-59172d89e6be.mp4" type="video/mp4" />
        </video>

        <section className="home-hero" id="start">
          <div className="hero-copy">
            <div className="hero-eyebrow">AI Travel Planner · Product Intro</div>
            <h1>你只管<br />期待出发。</h1>
            <p className="hero-lede">
              从灵感到出发，途见帮你把复杂的旅行决策变成一份真正可执行的计划。<br />
              多位 AI Agent 协同完成景点检索、路线编排、餐饮建议、天气参考与交通校验，<br />
              在几分钟内生成清晰、好读、可落地的旅行方案。
            </p>
            <div className="hero-actions">
              <button className="go-btn" onClick={onStart}>立即开始规划 <span aria-hidden="true">→</span></button>
              <button className="ghost-btn" onClick={viewAbilities}>查看产品能力</button>
            </div>
          </div>

          <aside className="capability-panel" aria-label="规划能力">
            <div className="panel-title">Planning Capabilities</div>
            <div className="capability-list">
              <article className="capability-item">
                <span className="capability-icon" aria-hidden="true">
                  <svg viewBox="0 0 24 24" fill="none" stroke="currentColor">
                    <path d="M16 20v-2a4 4 0 0 0-4-4H8a4 4 0 0 0-4 4v2" />
                    <circle cx="10" cy="7" r="4" />
                    <path d="M20 20v-2a4 4 0 0 0-3-3.87" />
                    <path d="M17 3.13a4 4 0 0 1 0 7.75" />
                  </svg>
                </span>
                <span>
                  <h2>多 Agent 协同规划</h2>
                  <p>专业分工，高效协作</p>
                </span>
              </article>
              <article className="capability-item">
                <span className="capability-icon" aria-hidden="true">
                  <svg viewBox="0 0 24 24" fill="none" stroke="currentColor">
                    <circle cx="12" cy="12" r="9" />
                    <path d="M12 7v5l3 2" />
                  </svg>
                </span>
                <span>
                  <h2>自动校验路线与时间</h2>
                  <p>时间、交通、天气智能校验</p>
                </span>
              </article>
              <article className="capability-item">
                <span className="capability-icon" aria-hidden="true">
                  <svg viewBox="0 0 24 24" fill="none" stroke="currentColor">
                    <path d="M6 3h9l4 4v14H6z" />
                    <path d="M14 3v5h5" />
                    <path d="M9 13h6" />
                    <path d="M9 17h6" />
                  </svg>
                </span>
                <span>
                  <h2>输出可执行行程</h2>
                  <p>清晰、好读、可直接使用</p>
                </span>
              </article>
            </div>
          </aside>
        </section>

        <section className="features" id="home-abilities" aria-label="产品能力">
          <div className="feature-grid">
            <article className="feature-card">
              <div className="feature-no">01</div>
              <div className="feature-row">
                <span className="feature-icon" aria-hidden="true">
                  <svg viewBox="0 0 24 24" fill="none" stroke="currentColor">
                    <circle cx="11" cy="11" r="7" />
                    <path d="m20 20-3.4-3.4" />
                  </svg>
                </span>
                <span>
                  <h2>需求理解</h2>
                  <p>识别目的地、天数、用户偏好</p>
                </span>
              </div>
              <span className="card-arrow" aria-hidden="true">→</span>
            </article>
            <article className="feature-card">
              <div className="feature-no">02</div>
              <div className="feature-row">
                <span className="feature-icon" aria-hidden="true">
                  <svg viewBox="0 0 24 24" fill="none" stroke="currentColor">
                    <path d="M6 18c3-7 9-5 12-12" />
                    <path d="M7 7h.01" />
                    <path d="M17 17h.01" />
                    <path d="M8 7a2 2 0 1 1-4 0 2 2 0 0 1 4 0Z" />
                    <path d="M20 17a2 2 0 1 1-4 0 2 2 0 0 1 4 0Z" />
                  </svg>
                </span>
                <span>
                  <h2>智能规划</h2>
                  <p>拆解景点、交通、餐饮与节奏安排</p>
                </span>
              </div>
              <span className="card-arrow" aria-hidden="true">→</span>
            </article>
            <article className="feature-card">
              <div className="feature-no">03</div>
              <div className="feature-row">
                <span className="feature-icon" aria-hidden="true">
                  <svg viewBox="0 0 24 24" fill="none" stroke="currentColor">
                    <path d="M8 2v4" />
                    <path d="M16 2v4" />
                    <rect x="4" y="5" width="16" height="16" rx="2" />
                    <path d="M8 13l3 3 5-6" />
                  </svg>
                </span>
                <span>
                  <h2>路线校验</h2>
                  <p>结合时间、天气与通行方式优化行程</p>
                </span>
              </div>
              <span className="card-arrow" aria-hidden="true">→</span>
            </article>
            <article className="feature-card">
              <div className="feature-no">04</div>
              <div className="feature-row">
                <span className="feature-icon" aria-hidden="true">
                  <svg viewBox="0 0 24 24" fill="none" stroke="currentColor">
                    <path d="M6 3h9l4 4v14H6z" />
                    <path d="M14 3v5h5" />
                    <path d="M9 13h6" />
                    <path d="M9 17h4" />
                  </svg>
                </span>
                <span>
                  <h2>结果交付</h2>
                  <p>生成清晰、可执行、可编辑的旅游计划</p>
                </span>
              </div>
              <span className="card-arrow" aria-hidden="true">→</span>
            </article>
          </div>
        </section>
      </main>
    </div>
  );
}

Object.assign(window, { PlanPage, TripDetailPage, HistoryPage, ProfilePage, AuthModal, SweepPreviewPage });
