const test = require("node:test");
const assert = require("node:assert/strict");

require("../frontend/chat-state.js");

test("streams assistant deltas and reconciles the durable message", () => {
  let state = ChatState.initialState();
  state = ChatState.applyEvent(state, "run-1", {
    kind: "messages",
    payload: { message_id: "assistant:run-1", delta: "你" },
  });
  state = ChatState.applyEvent(state, "run-1", {
    kind: "messages",
    payload: { message_id: "assistant:run-1", delta: "好" },
  });
  assert.equal(state.messages["assistant:run-1"].content, "你好");
  state = ChatState.applyEvent(state, "run-1", {
    kind: "custom",
    sequence: 4,
    payload: {
      kind: "chat.message.completed",
      message_id: "message-1",
      content: "你好",
      sequence: 2,
      created_at: "2026-07-23T10:00:01Z",
    },
  });
  assert.equal(state.messages["assistant:run-1"], undefined);
  assert.equal(state.messages["message-1"].content, "你好");
  assert.equal(state.messages["message-1"].created_at, "2026-07-23T10:00:01Z");
});

test("keeps a just-completed historical reply above the formal planning card", () => {
  let state = ChatState.initialState();
  state = ChatState.applyEvent(state, "chat-run", {
    kind: "custom",
    sequence: 1,
    payload: {
      kind: "chat.message.completed",
      message_id: "assistant-before-plan",
      content: "请补充日期",
      sequence: 2,
      created_at: "2026-07-23T10:00:01Z",
    },
  });
  state.runs["formal-plan"] = {
    id: "formal-plan", kind: "travel_plan", status: "queued",
    created_at: "2026-07-23T10:00:02Z",
  };
  assert.deepEqual(
    ChatState.activityItems(state).map(item => item.key),
    ["message:assistant-before-plan", "run:formal-plan"],
  );
});

test("keeps independent run cards and ignores duplicate cursors", () => {
  let state = ChatState.initialState();
  state.runs = {
    "run-a": { id: "run-a", status: "running" },
    "run-b": { id: "run-b", status: "queued" },
  };
  state = ChatState.applyEvent(state, "run-a", {
    kind: "custom",
    sequence: 3,
    payload: { kind: "run.status", status: "succeeded" },
  });
  const duplicated = ChatState.applyEvent(state, "run-a", {
    kind: "custom",
    sequence: 3,
    payload: { kind: "run.status", status: "failed" },
  });
  assert.equal(duplicated.runs["run-a"].status, "succeeded");
  assert.equal(duplicated.runs["run-b"].status, "queued");
});

test("makes a completed itinerary actionable without requiring a reload", () => {
  let state = ChatState.initialState();
  state.runs.revision = {
    id: "revision",
    kind: "revision",
    status: "running",
    request_snapshot: {},
  };
  state = ChatState.applyEvent(state, "revision", {
    kind: "custom",
    sequence: 6,
    payload: {
      kind: "planning.itinerary_created",
      itinerary_id: "itinerary-v2",
      destination: "泉州",
    },
  });
  state = ChatState.applyEvent(state, "revision", {
    kind: "custom",
    sequence: 7,
    payload: { kind: "run.status", status: "succeeded" },
  });
  assert.equal(state.runs.revision.status, "succeeded");
  assert.equal(state.runs.revision.result_itinerary_id, "itinerary-v2");
  assert.equal(state.runs.revision.request_snapshot.destination, "泉州");
});

test("stores planning briefs by id", () => {
  let state = ChatState.initialState();
  state = ChatState.applyEvent(state, "chat-run", {
    kind: "custom",
    sequence: 1,
    payload: {
      kind: "planning_brief.ready",
      brief_id: "brief-a",
      status: "ready",
      summary: { destination: "云南", days: 5 },
      missing_fields: [],
    },
  });
  assert.equal(state.briefs["brief-a"].data.destination, "云南");
  assert.equal(state.briefs["brief-a"].status, "ready");
});

test("shows a thinking item only while a chat run is awaiting its response", () => {
  let state = ChatState.initialState();
  state.runs["chat-run"] = {
    id: "chat-run", kind: "chat", status: "queued",
    created_at: "2026-07-23T10:00:01Z",
  };
  assert.deepEqual(
    ChatState.activityItems(state).map(item => item.key),
    ["chat-thinking:chat-run"],
  );
  state = ChatState.applyEvent(state, "chat-run", {
    kind: "custom", sequence: 1,
    payload: { kind: "run.status", status: "succeeded" },
  });
  assert.deepEqual(ChatState.activityItems(state), []);
});

test("adds a planning run created from a chat decision without a reload", () => {
  let state = ChatState.initialState();
  state = ChatState.applyEvent(state, "chat-run", {
    kind: "custom",
    sequence: 1,
    payload: {
      kind: "run.created",
      run: { id: "plan-run", kind: "travel_plan", status: "queued", request_snapshot: { destination: "南京" } },
    },
  });
  assert.equal(state.runs["plan-run"].status, "queued");
  assert.equal(state.runs["plan-run"].request_snapshot.destination, "南京");
});

test("keeps a waiting interaction after the following status event", () => {
  let state = ChatState.initialState();
  state.runs["run-waiting"] = { id: "run-waiting", status: "running" };
  state = ChatState.applyEvent(state, "run-waiting", {
    kind: "custom",
    sequence: 3,
    payload: {
      kind: "run.waiting_user",
      interaction_id: "interaction-1",
      question: "请补充出行日期",
    },
  });
  state = ChatState.applyEvent(state, "run-waiting", {
    kind: "custom",
    sequence: 4,
    payload: { kind: "run.status", status: "waiting_user" },
  });
  assert.equal(state.runs["run-waiting"].status, "waiting_user");
  assert.equal(
    state.runs["run-waiting"].pending_interaction.interaction_id,
    "interaction-1",
  );
  assert.equal(
    state.runs["run-waiting"].pending_interaction.question,
    "请补充出行日期",
  );
});

test("clears a waiting interaction when the run resumes", () => {
  let state = ChatState.initialState();
  state.runs["run-waiting"] = {
    id: "run-waiting",
    status: "waiting_user",
    pending_interaction: { interaction_id: "interaction-1" },
  };
  state = ChatState.applyEvent(state, "run-waiting", {
    kind: "custom",
    sequence: 5,
    payload: { kind: "run.status", status: "running" },
  });
  assert.equal(state.runs["run-waiting"].pending_interaction, null);
});

test("labels submitted planning briefs accurately", () => {
  assert.equal(ChatState.planningBriefStatusLabel("collecting"), "信息收集中");
  assert.equal(ChatState.planningBriefStatusLabel("ready"), "等待确认");
  assert.equal(ChatState.planningBriefStatusLabel("submitted"), "已提交");
});

test("projects messages, briefs, non-chat runs, and failed chat retries into one stable activity timeline", () => {
  let state = ChatState.initialState();
  state = ChatState.upsertMessage(state, {
    id: "message-1", role: "user", content: "规划云南",
    sequence: 1, created_at: "2026-07-23T10:00:00Z",
  });
  state.briefs["brief-1"] = {
    id: "brief-1", status: "ready", data: { destination: "云南" },
    created_at: "2026-07-23T10:00:01Z",
  };
  state.runs["chat-run"] = {
    id: "chat-run", kind: "chat", created_at: "2026-07-23T10:00:02Z",
  };
  state.runs["failed-chat-run"] = {
    id: "failed-chat-run", kind: "chat", status: "failed",
    created_at: "2026-07-23T10:00:02.5Z",
  };
  state.runs["plan-run"] = {
    id: "plan-run", kind: "travel_plan", status: "queued",
    created_at: "2026-07-23T10:00:03Z",
  };
  assert.deepEqual(
    ChatState.activityItems(state).map(item => item.key),
    ["message:message-1", "brief:brief-1", "chat-failure:failed-chat-run", "run:plan-run"],
  );
});

test("keeps activity order stable after entity updates and reconstruction", () => {
  const build = () => {
    let state = ChatState.initialState();
    state = ChatState.upsertMessage(state, {
      id: "m", role: "assistant", content: "已整理",
      sequence: 2, created_at: "2026-07-23T10:00:00Z",
    });
    state.briefs.b = {
      id: "b", status: "collecting", data: {},
      created_at: "2026-07-23T10:00:01Z",
      updated_at: "2026-07-23T10:05:00Z",
    };
    state.runs.r = {
      id: "r", kind: "travel_plan", status: "queued",
      created_at: "2026-07-23T10:00:02Z",
    };
    return state;
  };
  const before = build();
  before.briefs.b = { ...before.briefs.b, status: "ready", updated_at: "2026-07-23T10:10:00Z" };
  assert.deepEqual(
    ChatState.activityItems(before).map(item => item.key),
    ChatState.activityItems(build()).map(item => item.key),
  );
});

test("uses conversation sequence for live assistant messages without timestamps", () => {
  let state = ChatState.initialState();
  state = ChatState.upsertMessage(state, {
    id: "user-1", role: "user", sequence: 1,
    created_at: "2026-07-23T10:00:00Z",
  });
  state = ChatState.upsertMessage(state, {
    id: "assistant-1", role: "assistant", sequence: 2,
  });
  state = ChatState.upsertMessage(state, {
    id: "user-2", role: "user", sequence: 3,
    created_at: "2026-07-23T10:02:00Z",
  });
  assert.deepEqual(
    ChatState.activityItems(state)
      .filter(item => item.type === "message")
      .map(item => item.entityId),
    ["user-1", "assistant-1", "user-2"],
  );
});

test("maps internal planning loops to monotonic product stages", () => {
  let state = ChatState.initialState();
  state.runs.r = { id: "r", kind: "travel_plan", status: "running" };
  const progress = (sequence, stage) => {
    state = ChatState.applyEvent(state, "r", {
      kind: "custom", sequence,
      payload: { kind: "planning_run.progress", stage, label: stage },
    });
  };
  progress(1, "planner");
  progress(2, "reviewer");
  progress(3, "time_check");
  progress(4, "planner");
  assert.equal(state.runs.r.product_stage, "compose");
  assert.equal(state.runs.r.journey_step_index, 4);
  assert.equal(state.runs.r.internal_stage, "time_check");
  assert.deepEqual(state.runs.r.completed_product_stages, ["understand", "discover"]);
  progress(5, "meal_search");
  progress(6, "reviewer");
  assert.equal(state.runs.r.product_stage, "polish");
  assert.equal(state.runs.r.journey_step_index, 5);
  assert.equal(state.runs.r.internal_stage, "meal_search");
});

test("keeps retry runs as independent associated activity items", () => {
  const state = ChatState.initialState();
  state.runs.failed = {
    id: "failed", kind: "travel_plan", status: "failed",
    created_at: "2026-07-23T10:00:00Z",
  };
  state.runs.retry = {
    id: "retry", kind: "travel_plan", status: "queued",
    retry_of_run_id: "failed", created_at: "2026-07-23T10:00:01Z",
  };
  const runs = ChatState.activityItems(state).filter(item => item.type === "run");
  assert.equal(runs.length, 2);
  assert.equal(runs[1].entity.retry_of_run_id, "failed");
});

test("chooses safe structured controls with a text fallback", () => {
  assert.equal(ChatState.interactionInputKind({
    question: "请补充 start_date、end_date",
    input_schema: { type: "string" },
  }), "date-range");
  assert.equal(ChatState.interactionInputKind({
    question: "选择节奏",
    input_schema: { enum: ["舒缓", "紧凑"] },
  }), "single-choice");
  assert.equal(ChatState.interactionInputKind({
    question: "选择偏好",
    input_schema: { type: "array", items: { enum: ["美食", "人文"] } },
  }), "multi-choice");
  assert.equal(ChatState.interactionInputKind({
    question: "还有什么想补充？",
    input_schema: { type: "object", unsafe: "<script>" },
  }), "text");
});

test("builds a ready brief summary with explicit defaults", () => {
  const view = ChatState.briefViewModel({
    status: "ready",
    data: {
      destination: "云南",
      start_date: "2026-10-01",
      end_date: "2026-10-05",
      food_preference: "清淡",
    },
    missing_fields: [],
  });
  assert.equal(view.destination, "云南");
  assert.equal(view.dateLabel, "2026-10-01 — 2026-10-05");
  assert.equal(view.usesDefaults, true);
  assert.deepEqual(view.preferences, [["餐饮", "清淡"]]);
});

test("describes every run terminal and non-terminal state with an action", () => {
  for (const status of ["queued", "running", "waiting_user", "succeeded", "failed", "cancelled"]) {
    assert.ok(ChatState.RUN_PRESENTATIONS[status].label);
    assert.ok(ChatState.RUN_PRESENTATIONS[status].copy);
    assert.ok(ChatState.RUN_PRESENTATIONS[status].primaryAction);
  }
  assert.equal(ChatState.RUN_PRESENTATIONS.waiting_user.primaryAction, "resume");
  assert.equal(ChatState.RUN_PRESENTATIONS.failed.primaryAction, "retry");
});
