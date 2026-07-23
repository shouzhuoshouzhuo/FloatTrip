// main.jsx — App 壳：导航 / 主题 / 认证 / 路由

const TWEAK_DEFAULTS = /*EDITMODE-BEGIN*/{
  "theme": "morning",
  "mascot": true
}/*EDITMODE-END*/;

const THEME_OPTIONS = [
  { value: "morning", label: "晨刊 · 暖纸" },
  { value: "celadon", label: "青瓷 · 临水" },
  { value: "night",   label: "夜航 · 墨蓝" },
  { value: "sky",     label: "晴空 · 淡蓝" },
];
const THEME_ICONS = { morning: "☀", celadon: "🍃", night: "🌙", sky: "☁" };

function App() {
  const [t, setTweak] = useTweaks(TWEAK_DEFAULTS);
  const [page, setPage] = React.useState("chat");
  const [planKey, setPlanKey] = React.useState(0);
  const [authUser, setAuthUser] = React.useState(() => getAuth()?.username || null);
  const [showAuthModal, setShowAuthModal] = React.useState(false);
  const [authReason, setAuthReason] = React.useState("");
  const [pendingAuthAction, setPendingAuthAction] = React.useState(null);
  const [showUserMenu, setShowUserMenu] = React.useState(false);
  // 行程详情页数据
  const [detailPlan, setDetailPlan] = React.useState(null);
  const [detailPlanId, setDetailPlanId] = React.useState(null);
  // 触发 PlanPage 执行修改流
  const [modifyTrigger, setModifyTrigger] = React.useState(null);
  const modifyNonceRef = React.useRef(0);
  const [planPhase, setPlanPhase] = React.useState("idle");

  React.useEffect(() => {
    requestAnimationFrame(() => requestAnimationFrame(() => {
      document.documentElement.classList.add("anim-ready");
    }));
    // 处理 URL 参数
    const params = new URLSearchParams(window.location.search);
    if (params.get("login") === "1" && !getAuth()) {
      setPendingAuthAction(NavigationState.chatTarget(false));
      setShowAuthModal(true);
      history.replaceState({}, "", "/");
    }
    const viewId = params.get("view_plan_id");
    if (viewId) {
      history.replaceState({}, "", "/");
      const a = getAuth();
      if (!a) {
        setPendingAuthAction(NavigationState.detailTarget(viewId));
        setAuthReason("登录后继续打开这份行程");
        setShowAuthModal(true);
        return;
      }
      getHistoryItem(viewId).then(data => {
        if (data?.plan) {
          const adapted = adaptPlan(data.plan, a.username);
          setDetailPlan(adapted);
          setDetailPlanId(viewId);
          setPage("detail");
        }
      }).catch(() => {});
    }
  }, []);

  // 页面加载时验证 token 有效性
  React.useEffect(() => {
    checkAuth().then(result => {
      if (!result) setAuthUser(null);
    });
    const onExpired = () => setAuthUser(null);
    window.addEventListener("auth:expired", onExpired);
    return () => window.removeEventListener("auth:expired", onExpired);
  }, []);

  React.useEffect(() => {
    document.documentElement.setAttribute("data-theme", t.theme || "morning");
  }, [t.theme]);

  React.useEffect(() => {
    document.documentElement.setAttribute("data-mascot", t.mascot ? "on" : "off");
  }, [t.mascot]);

  // 点击空白关闭用户菜单（mousedown 避免与按钮 click 冲突）
  React.useEffect(() => {
    if (!showUserMenu) return;
    const handler = (e) => {
      if (!e.target.closest(".user-chip")) {
        setShowUserMenu(false);
      }
    };
    document.addEventListener("mousedown", handler);
    return () => document.removeEventListener("mousedown", handler);
  }, [showUserMenu]);

  const go = (p) => {
    setPage(p);
    if (p === "plan") {
      setModifyTrigger(null);
      // 规划进行中时导航回来只是显示页面，不重置（保活）
      if (planPhase !== "loading") setPlanKey(k => k + 1);
    }
    window.scrollTo({ top: 0 });
  };

  // 规划/修改完成后由 PlanPage 回调，跳到行程详情页
  const onPlanReady = (plan, planId) => {
    setDetailPlan(plan);
    setDetailPlanId(planId);
    setModifyTrigger(null);
    setPage("detail");
    window.scrollTo({ top: 0 });
  };

  // 从行程详情页发起修改：跳到规划页执行修改流
  const onRequestModify = (query, planId) => {
    const nonce = ++modifyNonceRef.current;
    setModifyTrigger({ query, planId, nonce });
    if (planPhase !== "loading") setPlanKey(k => k + 1);
    setPage("plan");
    window.scrollTo({ top: 0 });
  };

  // 修改被放弃（concern modal 选"保留原行程"）
  const onCancelModify = () => {
    setModifyTrigger(null);
    if (detailPlan) { setPage("detail"); window.scrollTo({ top: 0 }); }
  };

  const requestLogin = (reason = "请先登录再继续", continuation = null) => {
    setAuthReason(reason);
    setPendingAuthAction(continuation);
    setShowAuthModal(true);
  };

  const onAuthSuccess = (username) => {
    setAuthUser(username);
    setShowAuthModal(false);
    setAuthReason("");
    const continuation = NavigationState.resolveAfterAuth(pendingAuthAction);
    setPendingAuthAction(null);
    if (!continuation) return;
    if (continuation.page === "detail" && continuation.planId) {
      getHistoryItem(continuation.planId).then(data => {
        if (data?.plan) onOpenHistoryPlan(data.plan, continuation.planId);
      }).catch(() => {});
      return;
    }
    if (continuation.page === "chat") {
      setPage("chat");
      window.scrollTo({ top: 0 });
    }
  };

  const openChat = () => {
    if (!authUser) {
      requestLogin(
        "登录后继续你的旅行对话",
        NavigationState.chatTarget(),
      );
      return;
    }
    setPage("chat");
    window.scrollTo({ top: 0 });
  };

  const logout = () => {
    clearAuth();
    setAuthUser(null);
    setShowUserMenu(false);
    go("chat");
  };

  const onOpenHistoryPlan = (rawPlan, planId) => {
    const adapted = adaptPlan(rawPlan, authUser);
    setDetailPlan(adapted);
    setDetailPlanId(planId);
    setPage("detail");
    window.scrollTo({ top: 0 });
  };

  const initial = authUser ? authUser.slice(-1) : "";

  return (
    <div>
      <header className="topbar">
        <div className="brand" onClick={() => openChat()}>
          <div className="brand-glyph">途</div>
          <div>
            <div className="brand-name">途见 · AI 旅行规划</div>
            <div className="brand-sub">Travel Journal by Agents</div>
          </div>
        </div>
        <nav className="topnav">
          <button className={`topnav-link ${page === "chat" ? "active" : ""}`}
            onClick={openChat}>
            旅行对话
          </button>
          <button className={`topnav-link ${page === "history" ? "active" : ""}`}
            onClick={() => { if (!authUser) { requestLogin("请先登录查看历史行程"); return; } go("history"); }}>
            历史行程
          </button>
          <button className={`topnav-link ${page === "profile" ? "active" : ""}`}
            onClick={() => { if (!authUser) { requestLogin("请先登录管理旅行画像"); return; } go("profile"); }}>
            我的画像
          </button>
          <button className={`topnav-link sweep-nav-link ${page === "sweep" ? "active" : ""}`} onClick={() => go("sweep")}>
            🧪 测试
          </button>
        </nav>

        <div className="theme-switcher" role="group" aria-label="切换主题">
          {THEME_OPTIONS.map(({ value, label }) => (
            <button
              key={value}
              className={`theme-seg${t.theme === value ? " active" : ""}`}
              title={label}
              aria-pressed={t.theme === value}
              onClick={() => setTweak("theme", value)}
            >
              {THEME_ICONS[value]}
            </button>
          ))}
        </div>

        {authUser ? (
          <div className="user-chip" onClick={(e) => { e.stopPropagation(); setShowUserMenu(v => !v); }}>
            <span className="chip-name">{authUser}</span>
            <span className="avatar-dot">{initial}</span>
            {showUserMenu && (
              <div className="user-dropdown" onClick={e => e.stopPropagation()}>
                <button onClick={logout}>退出登录</button>
              </div>
            )}
          </div>
        ) : (
          <button className="user-login-btn" onClick={() => requestLogin("")}>登录 / 注册</button>
        )}
      </header>

      {showAuthModal && (
        <AuthModal
          reason={authReason}
          onSuccess={onAuthSuccess}
          onClose={() => { setShowAuthModal(false); setAuthReason(""); setPendingAuthAction(null); }}
        />
      )}

      {/* PlanPage 始终挂载，切换页面时隐藏而非卸载，保持规划流继续运行 */}
      <div style={{ display: page === "plan" ? "" : "none" }}>
        <PlanPage
          key={planKey}
          onRequestLogin={() => requestLogin()}
          currentUsername={authUser}
          onPhaseChange={setPlanPhase}
          onPlanReady={onPlanReady}
          modifyTrigger={modifyTrigger}
          onCancelModify={onCancelModify}
          onManageProfile={() => { if (!authUser) { requestLogin("请先登录管理旅行画像"); return; } go("profile"); }}
        />
      </div>
      {page === "detail" && detailPlan && (
        <TripDetailPage
          plan={detailPlan}
          planId={detailPlanId}
          onRequestModify={onRequestModify}
          onRequestLogin={() => requestLogin()}
          currentUsername={authUser}
        />
      )}
      {page === "chat" && (
        <ChatPage
          currentUsername={authUser}
          onRequestLogin={() => requestLogin("登录后继续你的旅行对话", NavigationState.chatTarget())}
          onOpenPlan={(planId) => {
            getHistoryItem(planId).then(data => {
              if (data?.plan) onOpenHistoryPlan(data.plan, planId);
            });
          }}
        />
      )}
      {page === "history" && (
        <HistoryPage onOpenPlan={onOpenHistoryPlan} currentUsername={authUser} />
      )}
      {page === "profile" && (
        <ProfilePage currentUsername={authUser} />
      )}
      {page === "sweep" && (
        <SweepPreviewPage />
      )}

      <TweaksPanel>
        <TweakSection label="整体方案" />
        <TweakSelect
          label="主题"
          value={t.theme}
          options={THEME_OPTIONS}
          onChange={(v) => setTweak("theme", v)}
        />
        <TweakSection label="虚拟形象" />
        <TweakToggle label="显示向导「途途」" value={t.mascot} onChange={(v) => setTweak("mascot", v)} />
      </TweaksPanel>
    </div>
  );
}

ReactDOM.createRoot(document.getElementById("root")).render(<App />);
