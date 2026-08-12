import {
  ArrowLeftIcon,
  CalendarIcon,
  ChatBubbleIcon,
  CheckCircledIcon,
  CheckIcon,
  ChevronDownIcon,
  ChevronUpIcon,
  ClockIcon,
  Cross1Icon,
  DragHandleDots2Icon,
  EnterFullScreenIcon,
  HamburgerMenuIcon,
  MagicWandIcon,
  MixerHorizontalIcon,
  PaperPlaneIcon,
  Pencil1Icon,
  PersonIcon,
  PlusIcon,
  ReaderIcon,
  ResetIcon,
  SewingPinIcon,
  Share2Icon,
  TrashIcon,
} from "@radix-ui/react-icons";
import { useDrag } from "@use-gesture/react";
import { motion } from "motion/react";
import { useEffect, useMemo, useState, type ReactNode, type Dispatch, type SetStateAction } from "react";
import {
  BottomSheet,
  Carousel,
  FlowStack,
  KeyboardTextarea,
  MobileScroll,
  useFlow,
  useKeyboard,
  useKeyboardInsets,
  useMobileDevice,
  type FlowControls,
  type FlowScreen,
} from "./mobile";
import {
  candidateStops,
  defaultBrief,
  defaultState,
  thoughtSteps,
  type PlanningBrief,
  type ProfileMemory,
  type PrototypeState,
  type TripDay,
  type TripPlan,
  type TripStop,
} from "./prototype-data";

const STORAGE_KEY = "qingzhou-mobile-prototype-v2";
const examples = [
  "8 月去滇西北一周，想慢一点看自然风光",
  "南京周末三日游，少走路，多看历史建筑",
];

type Tab = "plan" | "trips" | "profile";
type PlanningPhase = "home" | "collecting" | "ready" | "planning" | "completed";

function clone<T>(value: T): T {
  return JSON.parse(JSON.stringify(value));
}

function loadState(): PrototypeState {
  try {
    const raw = localStorage.getItem(STORAGE_KEY);
    return raw ? { ...clone(defaultState), ...JSON.parse(raw) } : clone(defaultState);
  } catch {
    return clone(defaultState);
  }
}

function saveState(state: PrototypeState) {
  localStorage.setItem(STORAGE_KEY, JSON.stringify(state));
}

function IconButton({ label, onClick, children }: { label: string; onClick: () => void; children: ReactNode }) {
  return <button className="icon-button" aria-label={label} onClick={onClick}>{children}</button>;
}

function AppHeader({ title, subtitle, onBack, action }: { title: string; subtitle?: string; onBack?: () => void; action?: ReactNode }) {
  return (
    <div className="app-header">
      {onBack ? <IconButton label="返回" onClick={onBack}><ArrowLeftIcon /></IconButton> : <div className="brand-mark" aria-label="轻舟">轻</div>}
      <div className="app-header-copy"><strong>{title}</strong>{subtitle ? <span>{subtitle}</span> : null}</div>
      {action ?? <div className="header-spacer" />}
    </div>
  );
}

function BottomNav({ tab, onChange }: { tab: Tab; onChange: (tab: Tab) => void }) {
  const items: { id: Tab; label: string; icon: ReactNode }[] = [
    { id: "plan", label: "规划", icon: <ChatBubbleIcon /> },
    { id: "trips", label: "行程", icon: <CalendarIcon /> },
    { id: "profile", label: "我的", icon: <PersonIcon /> },
  ];
  return (
    <nav className="bottom-nav" aria-label="主导航">
      {items.map((item) => (
        <button key={item.id} className={tab === item.id ? "active" : ""} onClick={() => onChange(item.id)}>
          {item.icon}<span>{item.label}</span>
        </button>
      ))}
    </nav>
  );
}

function TripImage({ src, alt, position, className = "" }: { src: string; alt: string; position?: string; className?: string }) {
  return <img className={className} src={src} alt={alt} draggable={false} style={{ objectPosition: position }} />;
}

function QingzhouRoot() {
  const flow = useFlow();
  const keyboard = useKeyboard();
  const { bottomInset } = useKeyboardInsets();
  const [state, setState] = useState(loadState);
  const [tab, setTab] = useState<Tab>("plan");
  const [phase, setPhase] = useState<PlanningPhase>("home");
  const [draft, setDraft] = useState("");
  const [brief, setBrief] = useState<PlanningBrief>(defaultBrief);
  const [pace, setPace] = useState("轻松悠闲");
  const [companions, setCompanions] = useState("两人出行");
  const [thoughtOpen, setThoughtOpen] = useState(true);
  const [thoughtIndex, setThoughtIndex] = useState(0);
  const [seconds, setSeconds] = useState(0);
  const [menuOpen, setMenuOpen] = useState(false);
  const [chatDraft, setChatDraft] = useState("");
  const [followup, setFollowup] = useState("");

  useEffect(() => saveState(state), [state]);

  useEffect(() => {
    if (phase !== "planning") return;
    setThoughtOpen(true);
    setThoughtIndex(0);
    setSeconds(0);
    const started = Date.now();
    const timer = window.setInterval(() => {
      const elapsed = Math.min(9, Math.floor((Date.now() - started) / 1000));
      setSeconds(elapsed);
      setThoughtIndex(Math.min(thoughtSteps.length - 1, Math.floor(elapsed / 2)));
      if (elapsed >= 9) {
        window.clearInterval(timer);
        setPhase("completed");
        setThoughtOpen(false);
      }
    }, 500);
    return () => window.clearInterval(timer);
  }, [phase]);

  const updateState = (updater: (current: PrototypeState) => PrototypeState) => setState((current) => updater(clone(current)));
  const chooseTab = (next: Tab) => { keyboard.hide(); setTab(next); setPhase(next === "plan" ? phase : "home"); };
  const openTrip = (trip: TripPlan) => {
    keyboard.hide();
    flow.push(makeTripScreen(trip, (next) => {
      updateState((current) => ({ ...current, trips: current.trips.map((item) => item.id === next.id ? next : item) }));
    }));
  };
  const startConversation = (value?: string) => {
    const input = (value ?? draft).trim();
    if (!input) return;
    keyboard.hide();
    setDraft(input);
    setPhase("collecting");
  };
  const confirmBrief = () => {
    setBrief((current) => ({ ...current, pace, companions, memories: state.memories.filter((m) => !m.pending && ["偏好", "必须满足"].includes(m.category)).slice(0, 2).map((m) => m.text) }));
    setPhase("ready");
  };

  return (
    <div className="qingzhou-shell">
      <div className="root-screen">
        {tab === "plan" ? (
          <PlanExperience
            phase={phase} draft={draft} setDraft={setDraft} brief={brief}
            pace={pace} setPace={setPace} companions={companions} setCompanions={setCompanions}
            thoughtOpen={thoughtOpen} setThoughtOpen={setThoughtOpen} thoughtIndex={thoughtIndex} seconds={seconds}
            memories={state.memories} onStart={startConversation} onConfirm={confirmBrief}
            onBeginPlanning={() => { keyboard.hide(); setPhase("planning"); }} onOpenTrip={() => openTrip(state.trips[0])}
            onReset={() => { setPhase("home"); setDraft(""); setFollowup(""); setChatDraft(""); }}
            chatDraft={chatDraft} setChatDraft={setChatDraft} followup={followup}
            onSendFollowup={() => { if (!chatDraft.trim()) return; setFollowup(chatDraft.trim()); setChatDraft(""); keyboard.hide(); }}
            menuOpen={menuOpen} setMenuOpen={setMenuOpen}
          />
        ) : tab === "trips" ? (
          <TripsScreen trips={state.trips} onOpenTrip={openTrip} onNew={() => { setTab("plan"); setPhase("home"); }} />
        ) : (
          <ProfileScreen state={state} setState={setState} />
        )}
      </div>
      {(tab !== "plan" || phase === "home") ? <BottomNav tab={tab} onChange={chooseTab} /> : null}
      <div className="keyboard-safe-cover" style={{ height: bottomInset }} />
    </div>
  );
}

function PlanExperience(props: {
  phase: PlanningPhase;
  draft: string;
  setDraft: (value: string) => void;
  brief: PlanningBrief;
  pace: string;
  setPace: (value: string) => void;
  companions: string;
  setCompanions: (value: string) => void;
  thoughtOpen: boolean;
  setThoughtOpen: (value: boolean) => void;
  thoughtIndex: number;
  seconds: number;
  memories: ProfileMemory[];
  onStart: (value?: string) => void;
  onConfirm: () => void;
  onBeginPlanning: () => void;
  onOpenTrip: () => void;
  onReset: () => void;
  chatDraft: string;
  setChatDraft: (value: string) => void;
  followup: string;
  onSendFollowup: () => void;
  menuOpen: boolean;
  setMenuOpen: (value: boolean) => void;
}) {
  const keyboard = useKeyboard();
  const { bottomInset } = useKeyboardInsets();
  const chatMode = props.phase !== "home";
  return (
    <>
      {chatMode ? (
        <AppHeader
          title="轻舟旅行助手"
          subtitle={props.phase === "completed" ? "滇西北一周深度漫游" : "新的旅行计划"}
          onBack={props.onReset}
          action={<IconButton label="更多" onClick={() => props.setMenuOpen(true)}><HamburgerMenuIcon /></IconButton>}
        />
      ) : (
        <AppHeader title="轻舟" subtitle="对话式旅行规划" action={<div className="header-actions"><IconButton label="新建计划" onClick={() => props.onStart(examples[0])}><PlusIcon /></IconButton></div>} />
      )}

      <MobileScroll className={chatMode ? "app-scroll chat-scroll" : "app-scroll home-scroll"}>
        {props.phase === "home" ? (
          <main className="home-content">
            <section className="home-intro">
              <span className="kicker">下一段旅程</span>
              <h1>这次想去哪儿？</h1>
              <p>说出一个念头，轻舟会和你一起把它变成能出发的行程。</p>
            </section>
            <HomeComposer value={props.draft} setValue={props.setDraft} onSend={() => props.onStart()} />
            <section className="prompt-section">
              <div className="section-heading"><strong>试着这样说</strong><span>从一句话开始</span></div>
              <div className="prompt-list">
                {examples.map((example) => <button key={example} onClick={() => props.onStart(example)}><span>{example}</span><PaperPlaneIcon /></button>)}
              </div>
            </section>
            <section className="recent-preview">
              <div className="section-heading"><strong>最近行程</strong><span>已完成</span></div>
              <div className="mini-trip-card">
                <TripImage src="/assets/app/yunnan-cover.png" alt="滇西北高山湖泊" />
                <div><span>7天6晚</span><strong>滇西北一周深度漫游</strong><small>18 个地点 · 轻松悠闲</small></div>
              </div>
            </section>
          </main>
        ) : (
          <main className="conversation-feed">
            <div className="user-bubble">{props.draft}</div>
            {props.phase === "collecting" ? (
              <section className="assistant-turn">
                <div className="assistant-avatar">轻</div>
                <div className="assistant-copy">
                  <p>我理解你想用一周慢慢走过大理、丽江和香格里拉。再确认两件事，就可以开始规划。</p>
                  <ChoiceQuestion label="旅行节奏" values={["轻松悠闲", "适中均衡", "紧凑充实"]} value={props.pace} onChange={props.setPace} />
                  <ChoiceQuestion label="同行情况" values={["独自出行", "两人出行", "亲子出行"]} value={props.companions} onChange={props.setCompanions} />
                  <button className="primary-button" onClick={props.onConfirm}>确认并继续</button>
                </div>
              </section>
            ) : null}
            {["ready", "planning", "completed"].includes(props.phase) ? (
              <>
                <div className="user-bubble compact">{props.pace} · {props.companions}</div>
                {props.phase === "ready" ? (
                  <section className="assistant-turn">
                    <div className="assistant-avatar">轻</div>
                    <div className="assistant-copy">
                      <p>好的，我把这次旅程整理好了。你可以直接开始，也可以再调整。</p>
                      <BriefSummary brief={props.brief} memories={props.memories} />
                      <button className="primary-button" onClick={props.onBeginPlanning}>开始规划</button>
                    </div>
                  </section>
                ) : null}
              </>
            ) : null}
            {["planning", "completed"].includes(props.phase) ? (
              <section className="assistant-turn thinking-turn">
                <div className="assistant-avatar">轻</div>
                <div className="assistant-copy">
                  <ThinkingDisclosure running={props.phase === "planning"} seconds={props.phase === "planning" ? props.seconds : 9}
                    open={props.thoughtOpen} setOpen={props.setThoughtOpen} activeIndex={props.thoughtIndex} />
                  {props.phase === "completed" ? (
                    <div className="result-message">
                      <p>行程已经准备好了。我把高海拔活动拆开安排，也给大理和丽江留出了慢慢逛的时间。</p>
                      <TripResultCard onOpen={props.onOpenTrip} />
                      <div className="result-actions">
                        <button onClick={props.onOpenTrip}>查看完整行程</button>
                        <button onClick={() => props.setChatDraft("想把第二天安排得更轻松")}>继续调整</button>
                      </div>
                    </div>
                  ) : null}
                </div>
              </section>
            ) : null}
            {props.followup ? (
              <>
                <div className="user-bubble">{props.followup}</div>
                <section className="assistant-turn compact-turn"><div className="assistant-avatar">轻</div><div className="assistant-copy"><p>已经记下。你可以继续补充，或打开完整行程直接调整时间和地点。</p></div></section>
              </>
            ) : null}
          </main>
        )}
      </MobileScroll>

      {chatMode ? (
        <div className="chat-composer-layer" style={{ bottom: bottomInset }}>
          <button aria-label="添加附件"><PlusIcon /></button>
          <KeyboardTextarea value={props.chatDraft} onChange={(event) => props.setChatDraft(event.target.value)} placeholder={props.phase === "planning" ? "规划会在后台继续…" : "发消息继续调整"} disabled={props.phase === "planning"} />
          <button className="send-button" aria-label="发送" disabled={!props.chatDraft.trim() || props.phase === "planning"} onClick={props.onSendFollowup}><PaperPlaneIcon /></button>
        </div>
      ) : null}

      <BottomSheet open={props.menuOpen} onOpenChange={props.setMenuOpen} title="对话设置" description="管理当前旅行对话" snap={0.42}>
        <div className="sheet-action-list">
          <button onClick={() => props.setMenuOpen(false)}><ReaderIcon />查看本次参考画像</button>
          <button onClick={() => { props.onReset(); props.setMenuOpen(false); }}><PlusIcon />新建旅行对话</button>
          <button onClick={() => { props.onReset(); props.setMenuOpen(false); }}><ResetIcon />清空当前演示</button>
        </div>
      </BottomSheet>
    </>
  );
}

function HomeComposer({ value, setValue, onSend }: { value: string; setValue: (value: string) => void; onSend: () => void }) {
  return (
    <div className="home-composer">
      <KeyboardTextarea value={value} onChange={(event) => setValue(event.target.value)} placeholder="例如：8 月去云南一周，想看自然风光，节奏轻松" />
      <div className="home-composer-foot"><span>轻舟会在必要时追问</span><button aria-label="发送需求" disabled={!value.trim()} onClick={onSend}><PaperPlaneIcon /></button></div>
    </div>
  );
}

function ChoiceQuestion({ label, values, value, onChange }: { label: string; values: string[]; value: string; onChange: (value: string) => void }) {
  return (
    <div className="choice-question"><strong>{label}</strong><div>{values.map((item) => <button key={item} className={value === item ? "selected" : ""} onClick={() => onChange(item)}>{value === item ? <CheckIcon /> : null}{item}</button>)}</div></div>
  );
}

function BriefSummary({ brief, memories }: { brief: PlanningBrief; memories: ProfileMemory[] }) {
  const applied = memories.filter((item) => !item.pending && ["偏好", "必须满足"].includes(item.category)).slice(0, 2);
  return (
    <div className="brief-summary">
      <div className="brief-top"><span>规划摘要</span><strong>{brief.destination}</strong></div>
      <dl><div><dt>时间</dt><dd>{brief.dateLabel}</dd></div><div><dt>节奏</dt><dd>{brief.pace}</dd></div><div><dt>偏好</dt><dd>{brief.interests.join(" · ")}</dd></div></dl>
      <div className="memory-applied"><ReaderIcon /><span><strong>已参考你的画像</strong>{applied.map((item) => item.text).join("；")}</span></div>
    </div>
  );
}

function ThinkingDisclosure({ running, seconds, open, setOpen, activeIndex }: { running: boolean; seconds: number; open: boolean; setOpen: (value: boolean) => void; activeIndex: number }) {
  return (
    <div className="thinking-disclosure">
      <button className="thinking-head" onClick={() => setOpen(!open)}>
        <span><MagicWandIcon /><strong>{running ? "正在深度思考…" : "深度思考完成"}</strong><small>{seconds}s</small></span>
        {open ? <ChevronUpIcon /> : <ChevronDownIcon />}
      </button>
      {open ? <div className="thought-log">{thoughtSteps.map((step, index) => (
        <div key={step.id} className={index < activeIndex || !running ? "done" : index === activeIndex ? "active" : "pending"}>
          <span className="thought-dot">{index < activeIndex || !running ? <CheckIcon /> : null}</span>
          <p><strong>{step.title}</strong><small>{index <= activeIndex || !running ? step.detail : "等待上一步完成"}</small></p>
        </div>
      ))}</div> : null}
    </div>
  );
}

function TripResultCard({ onOpen }: { onOpen: () => void }) {
  return (
    <button className="trip-result-card" onClick={onOpen}>
      <TripImage src="/assets/app/yunnan-cover.png" alt="滇西北旅行封面" />
      <div><span>已完成</span><strong>滇西北一周深度漫游</strong><small>08.20 — 08.26 · 7天6晚</small><p>大理 → 丽江 → 香格里拉</p></div>
    </button>
  );
}

function TripsScreen({ trips, onOpenTrip, onNew }: { trips: TripPlan[]; onOpenTrip: (trip: TripPlan) => void; onNew: () => void }) {
  const [filter, setFilter] = useState<"all" | TripPlan["status"]>("all");
  const visibleTrips = filter === "all" ? trips : trips.filter((trip) => trip.status === filter);
  return (
    <>
      <AppHeader title="我的行程" subtitle={`${visibleTrips.length} 段旅程`} action={<IconButton label="新建行程" onClick={onNew}><PlusIcon /></IconButton>} />
      <MobileScroll className="app-scroll tab-scroll"><main className="trips-content">
        <div className="page-title"><span className="kicker">轻装出发</span><h1>所有行程</h1><p>每份行程都可以继续对话、调整和优化。</p></div>
        <div className="filter-row"><button className={filter === "all" ? "active" : ""} onClick={() => setFilter("all")}>全部</button><button className={filter === "planning" ? "active" : ""} onClick={() => setFilter("planning")}>进行中</button><button className={filter === "completed" ? "active" : ""} onClick={() => setFilter("completed")}>已完成</button></div>
        <div className="trip-list">{visibleTrips.map((trip) => (
          <button key={trip.id} className="trip-list-card" onClick={() => onOpenTrip(trip)}>
            <TripImage src={trip.cover} alt={`${trip.destination}旅行封面`} />
            <div className="trip-card-overlay" />
            <div className="trip-card-content"><span className="status-pill">{trip.status === "completed" ? "已完成" : "进行中"}</span><strong>{trip.title}</strong><small>{trip.dateRange}</small><div>{trip.tags.map((tag) => <span key={tag}>{tag}</span>)}</div><p>{trip.placesCount} 个地点</p></div>
          </button>
        ))}</div>
      </main></MobileScroll>
    </>
  );
}

function ProfileScreen({ state, setState }: { state: PrototypeState; setState: Dispatch<SetStateAction<PrototypeState>> }) {
  const keyboard = useKeyboard();
  const [sheetOpen, setSheetOpen] = useState(false);
  const [editing, setEditing] = useState<ProfileMemory | null>(null);
  const [category, setCategory] = useState<ProfileMemory["category"]>("偏好");
  const [text, setText] = useState("");
  const [menuOpen, setMenuOpen] = useState(false);
  const groups: ProfileMemory["category"][] = ["偏好", "避雷", "必须满足", "背景信息"];
  const activeMemories = state.memories.filter((item) => !item.pending);
  const pending = state.memories.filter((item) => item.pending);
  const changeMemories = (next: ProfileMemory[]) => setState((current) => ({ ...current, memories: next }));
  const openAdd = () => { setEditing(null); setCategory("偏好"); setText(""); setSheetOpen(true); };
  const openEdit = (memory: ProfileMemory) => { setEditing(memory); setCategory(memory.category); setText(memory.text); setSheetOpen(true); };
  const saveMemory = () => {
    if (!text.trim()) return;
    const next = editing
      ? state.memories.map((item) => item.id === editing.id ? { ...item, category, text: text.trim() } : item)
      : [...state.memories, { id: `memory-${Date.now()}`, category, text: text.trim() }];
    changeMemories(next); keyboard.hide(); setSheetOpen(false);
  };
  return (
    <>
      <AppHeader title="我的" subtitle="旅行画像" action={<IconButton label="菜单" onClick={() => setMenuOpen(true)}><HamburgerMenuIcon /></IconButton>} />
      <MobileScroll className="app-scroll tab-scroll"><main className="profile-content">
        <section className="profile-hero">
          <TripImage src="/assets/app/avatar.png" alt="用户头像" />
          <div><span>轻舟旅行者</span><strong>守拙</strong><small>轻舟会把你确认过的习惯带进下一次规划</small></div>
        </section>
        <div className="profile-stats"><div><strong>{state.trips.length}</strong><span>旅程</span></div><div><strong>5</strong><span>城市</span></div><div><strong>{activeMemories.length}</strong><span>记忆</span></div></div>
        {pending.length ? <section className="pending-memory"><div className="section-heading"><strong>待你确认</strong><span>不会自动使用</span></div>{pending.map((item) => <div key={item.id}><p>{item.text}</p><div><button onClick={() => changeMemories(state.memories.filter((m) => m.id !== item.id))}>忽略</button><button onClick={() => changeMemories(state.memories.map((m) => m.id === item.id ? { ...m, pending: false } : m))}>确认记住</button></div></div>)}</section> : null}
        <section className="memory-section"><div className="section-heading"><strong>旅行记忆</strong><button onClick={openAdd}><PlusIcon />新增</button></div>
          {groups.map((group) => {
            const list = activeMemories.filter((item) => item.category === group);
            if (!list.length) return null;
            return <div className="memory-group" key={group}><span>{group}</span>{list.map((item) => <div className="memory-row" key={item.id}><p>{item.text}</p><div><button aria-label="编辑记忆" onClick={() => openEdit(item)}><Pencil1Icon /></button><button aria-label="删除记忆" onClick={() => changeMemories(state.memories.filter((m) => m.id !== item.id))}><TrashIcon /></button></div></div>)}</div>;
          })}
        </section>
      </main></MobileScroll>
      <BottomSheet open={sheetOpen} onOpenChange={setSheetOpen} title={editing ? "编辑旅行记忆" : "新增旅行记忆"} description="这些信息会从下一段新对话开始使用" snap={0.58}>
        <div className="memory-form"><label>类型<div className="memory-type-grid">{groups.map((item) => <button key={item} className={category === item ? "selected" : ""} onClick={() => setCategory(item)}>{item}</button>)}</div></label><label>内容<KeyboardTextarea value={text} onChange={(event) => setText(event.target.value)} placeholder="例如：每天最多安排三个核心地点" /></label><button className="primary-button" onClick={saveMemory}>保存记忆</button></div>
      </BottomSheet>
      <BottomSheet open={menuOpen} onOpenChange={setMenuOpen} title="画像设置" description="管理轻舟如何使用旅行记忆" snap={0.36}>
        <div className="sheet-action-list">
          <button onClick={() => setMenuOpen(false)}><ReaderIcon />仅使用已确认记忆</button>
          <button onClick={() => setMenuOpen(false)}><CheckCircledIcon />待确认内容不自动应用</button>
        </div>
      </BottomSheet>
    </>
  );
}

function makeTripScreen(trip: TripPlan, onChange: (trip: TripPlan) => void): FlowScreen {
  return { id: `trip-${trip.id}`, render: (flow) => <TripDetail initialTrip={trip} flow={flow} onChange={onChange} /> };
}

function TripDetail({ initialTrip, flow, onChange }: { initialTrip: TripPlan; flow: FlowControls; onChange: (trip: TripPlan) => void }) {
  const { device } = useMobileDevice();
  const [trip, setTrip] = useState(clone(initialTrip));
  const [dayIndex, setDayIndex] = useState(0);
  const [optimized, setOptimized] = useState(false);
  const [beforeOptimize, setBeforeOptimize] = useState<TripDay[] | null>(null);
  const [panelExpanded, setPanelExpanded] = useState(false);
  const [panelDrag, setPanelDrag] = useState(0);
  const [recommendations, setRecommendations] = useState(true);
  const day = trip.days[dayIndex];
  const collapsedY = Math.round(device.geometry.screen.height * .49);
  const panelY = Math.max(0, Math.min(collapsedY, (panelExpanded ? 0 : collapsedY) + panelDrag));
  const updateTrip = (next: TripPlan) => { setTrip(next); onChange(next); };
  const optimize = () => {
    if (optimized && beforeOptimize) { updateTrip({ ...trip, days: beforeOptimize }); setOptimized(false); return; }
    setBeforeOptimize(clone(trip.days));
    const days = clone(trip.days); days[dayIndex].stops = [...days[dayIndex].stops].sort((a, b) => a.category.localeCompare(b.category));
    updateTrip({ ...trip, days }); setOptimized(true);
  };
  const edit = () => flow.push(makeEditScreen(trip, dayIndex, (next) => { setTrip(next); onChange(next); }));
  const bindPanel = useDrag(({ last, movement: [, movementY], velocity: [, velocityY], direction: [, directionY] }) => {
    if (!last) { setPanelDrag(movementY); return; }
    const shouldExpand = panelExpanded
      ? !(movementY > 84 || (velocityY > .5 && directionY > 0))
      : movementY < -70 || (velocityY > .45 && directionY < 0);
    setPanelExpanded(shouldExpand);
    setPanelDrag(0);
  }, { axis: "y", filterTaps: true });
  const markerPositions = [
    { top: "24%", left: "65%" },
    { top: "39%", left: "34%" },
    { top: "57%", left: "59%" },
  ];
  return (
    <div className="detail-shell">
      <div className="trip-map-canvas">
        <img src="/assets/app/dali-route-map-portrait.png" alt="大理当日路线地图" draggable={false} />
        <div className="map-topbar">
          <IconButton label="返回" onClick={flow.pop}><ArrowLeftIcon /></IconButton>
          <div className="map-title-pill"><strong>{trip.title}</strong><span>{day.label} · {day.theme}</span></div>
          <div><IconButton label="分享行程" onClick={() => {}}><Share2Icon /></IconButton><IconButton label="地图设置" onClick={() => {}}><MixerHorizontalIcon /></IconButton></div>
        </div>
        {day.stops.slice(0, 3).map((stop, index) => <div className="map-stop-marker" key={stop.id} style={markerPositions[index]}><span>{index + 1}</span><strong>{stop.name}</strong></div>)}
        {recommendations ? <><div className="map-recommendation rec-one"><SewingPinIcon /><span>海景咖啡</span></div><div className="map-recommendation rec-two"><SewingPinIcon /><span>白族小院</span></div></> : null}
        <button className={`map-recommend-toggle ${recommendations ? "active" : ""}`} onClick={() => setRecommendations((value) => !value)}>{recommendations ? <CheckIcon /> : null}推荐地点</button>
        <button className="map-fit-button" aria-label="查看完整路线"><EnterFullScreenIcon /></button>
      </div>

      <motion.section className="itinerary-sheet" animate={{ y: panelY }} transition={{ type: "spring", stiffness: 430, damping: 40, mass: .9 }}>
        <button className="sheet-peek-handle" aria-label={panelExpanded ? "下拉收起详情" : "上拉展开详情"} onClick={() => setPanelExpanded((value) => !value)} {...bindPanel()}><span /></button>
        <Carousel ariaLabel="选择行程日期" className="sheet-day-carousel" contentClassName="sheet-day-track">
          <button className="overview-day" onClick={() => setPanelExpanded(true)}>总览</button>
          {trip.days.map((item, index) => <button key={item.id} className={dayIndex === index ? "active" : ""} onClick={() => { setDayIndex(index); setPanelExpanded(true); }}><strong>{item.date}</strong><span>{item.label}</span></button>)}
        </Carousel>
        <MobileScroll className="itinerary-scroll"><main className="sheet-day-content">
          <div className="sheet-day-heading"><div><span>{day.date}</span><h2>{day.theme}</h2><small>{day.weather} · 约 7 小时</small></div><button aria-label={panelExpanded ? "收起详情" : "展开详情"} onClick={() => setPanelExpanded((value) => !value)}>{panelExpanded ? <ChevronDownIcon /> : <ChevronUpIcon />}</button></div>
          <div className="sheet-route-summary"><SewingPinIcon /><span>{day.stops.map((stop) => stop.name).join(" → ")}</span><button onClick={optimize}>{optimized ? <ResetIcon /> : <MagicWandIcon />}{optimized ? "恢复" : "优化"}</button></div>
          <div className="sheet-stop-list">{day.stops.map((stop, index) => <div className="sheet-stop-wrap" key={stop.id}>
            <article className="sheet-stop-row"><TripImage src={stop.image} position={stop.imagePosition} alt={stop.name} /><div className="sheet-stop-copy"><span>{stop.category}</span><strong>{index + 1}. {stop.name}</strong><div><ClockIcon />{stop.start}–{stop.end} · {stop.duration}</div><p>{stop.note}</p></div><button aria-label={`编辑${stop.name}`} onClick={edit}><Pencil1Icon /></button></article>
            {index < day.stops.length - 1 ? <div className="sheet-distance">{stop.transport || "步行约 12 分钟"}</div> : null}
          </div>)}</div>
        </main></MobileScroll>
      </motion.section>
      <div className="map-detail-actions"><button onClick={flow.pop}><ChatBubbleIcon />继续调整</button><button onClick={edit}><Pencil1Icon />编辑</button><button aria-label="添加地点" onClick={edit}><PlusIcon /></button></div>
    </div>
  );
}

function makeEditScreen(trip: TripPlan, dayIndex: number, onSave: (trip: TripPlan) => void): FlowScreen {
  return { id: `edit-${trip.id}`, render: (flow) => <TripEditor initialTrip={trip} initialDay={dayIndex} flow={flow} onSave={onSave} /> };
}

function TripEditor({ initialTrip, initialDay, flow, onSave }: { initialTrip: TripPlan; initialDay: number; flow: FlowControls; onSave: (trip: TripPlan) => void }) {
  const [draft, setDraft] = useState(clone(initialTrip));
  const [dayIndex, setDayIndex] = useState(initialDay);
  const [history, setHistory] = useState<TripPlan[]>([]);
  const [future, setFuture] = useState<TripPlan[]>([]);
  const [picker, setPicker] = useState<{ mode: "add" | "replace"; index?: number } | null>(null);
  const day = draft.days[dayIndex];
  const commit = (mutate: (next: TripPlan) => void) => {
    setHistory((items) => [...items, clone(draft)]); setFuture([]);
    const next = clone(draft); mutate(next); setDraft(next);
  };
  const undo = () => { const previous = history.at(-1); if (!previous) return; setFuture((items) => [clone(draft), ...items]); setDraft(previous); setHistory((items) => items.slice(0, -1)); };
  const redo = () => { const next = future[0]; if (!next) return; setHistory((items) => [...items, clone(draft)]); setDraft(next); setFuture((items) => items.slice(1)); };
  const reorder = (from: number, to: number) => commit((next) => { const list = next.days[dayIndex].stops; const [item] = list.splice(from, 1); list.splice(to, 0, item); });
  const chooseCandidate = (candidate: TripStop) => {
    commit((next) => {
      const copy = { ...candidate, id: `${candidate.id}-${Date.now()}` };
      if (picker?.mode === "replace" && picker.index !== undefined) next.days[dayIndex].stops[picker.index] = copy;
      else next.days[dayIndex].stops.push(copy);
    });
    setPicker(null);
  };
  return (
    <div className="editor-shell">
      <AppHeader title="编辑行程" subtitle={`${day.label} · ${day.theme}`} onBack={flow.pop} action={<button className="save-text-button" onClick={() => { onSave(draft); saveState({ ...loadState(), trips: loadState().trips.map((item) => item.id === draft.id ? draft : item) }); flow.pop(); }}>保存</button>} />
      <MobileScroll className="app-scroll editor-scroll"><main className="editor-content">
        <Carousel ariaLabel="选择编辑日期" className="day-carousel" contentClassName="day-carousel-track">{draft.days.map((item, index) => <button key={item.id} className={dayIndex === index ? "active" : ""} onClick={() => setDayIndex(index)}><strong>{item.label}</strong><span>{item.date}</span></button>)}</Carousel>
        <div className="edit-toolbar"><div><button disabled={!history.length} onClick={undo}><ArrowLeftIcon />撤销</button><button disabled={!future.length} onClick={redo}>重做<ArrowLeftIcon /></button></div><span>按住把手上下拖动排序</span></div>
        <div className="editable-list">{day.stops.map((stop, index) => <EditableStop key={stop.id} stop={stop} index={index} total={day.stops.length} onMove={reorder} onTime={(start, end) => commit((next) => { Object.assign(next.days[dayIndex].stops[index], { start, end }); })} onReplace={() => setPicker({ mode: "replace", index })} onDelete={() => commit((next) => { next.days[dayIndex].stops.splice(index, 1); })} />)}</div>
        <button className="add-stop-button" onClick={() => setPicker({ mode: "add" })}><PlusIcon />添加地点</button>
      </main></MobileScroll>
      <BottomSheet open={!!picker} onOpenChange={(open) => !open && setPicker(null)} title={picker?.mode === "replace" ? "替换地点" : "添加地点"} description="从轻舟整理的候选地点中选择" snap={0.62}>
        <div className="candidate-list">{candidateStops.map((candidate) => <button key={candidate.id} onClick={() => chooseCandidate(candidate)}><TripImage src={candidate.image} position={candidate.imagePosition} alt={candidate.name} /><span><strong>{candidate.name}</strong><small>{candidate.category} · {candidate.duration}</small><p>{candidate.note}</p></span></button>)}</div>
      </BottomSheet>
    </div>
  );
}

function EditableStop({ stop, index, total, onMove, onTime, onReplace, onDelete }: { stop: TripStop; index: number; total: number; onMove: (from: number, to: number) => void; onTime: (start: string, end: string) => void; onReplace: () => void; onDelete: () => void }) {
  const [dragY, setDragY] = useState(0);
  const bind = useDrag((gesture) => {
    const y = gesture.movement[1]; setDragY(gesture.last ? 0 : y);
    if (gesture.last) {
      if (y > 42 && index < total - 1) onMove(index, index + 1);
      if (y < -42 && index > 0) onMove(index, index - 1);
    }
  }, { axis: "y", filterTaps: true });
  return (
    <div className="editable-stop" style={{ transform: `translateY(${dragY}px)` }}>
      <button className="drag-handle" aria-label={`拖动${stop.name}`} data-scroll-drag="ignore" {...bind()}><DragHandleDots2Icon /></button>
      <TripImage src={stop.image} position={stop.imagePosition} alt={stop.name} />
      <div className="editable-stop-main"><strong>{stop.name}</strong><div className="time-inputs"><label>开始<input type="time" value={stop.start} onChange={(event) => onTime(event.target.value, stop.end)} /></label><span>—</span><label>结束<input type="time" value={stop.end} onChange={(event) => onTime(stop.start, event.target.value)} /></label></div><div className="edit-row-actions"><button onClick={onReplace}><ResetIcon />替换</button><button onClick={onDelete}><TrashIcon />删除</button></div></div>
    </div>
  );
}

export default function Prototype() {
  const initial = useMemo<FlowScreen>(() => ({ id: "qingzhou-root", render: () => <QingzhouRoot /> }), []);
  return <FlowStack initial={initial} />;
}
