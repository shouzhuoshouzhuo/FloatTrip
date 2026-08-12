import type {ConversationMessage, ConversationSummary, PlanningBrief, ProfileMemory, Run, TripDay, TripPlan, TripStop} from '../types';

const images = {
  cover: require('../assets/images/yunnan-cover.png'),
  dali: require('../assets/images/poi-dali.png'),
  food: require('../assets/images/poi-erhai.png'),
  mountain: require('../assets/images/poi-snow.png'),
};

const text = (value: unknown, fallback = '') => typeof value === 'string' && value.trim() ? value : fallback;
const record = (value: unknown): Record<string, unknown> => value && typeof value === 'object' && !Array.isArray(value) ? value as Record<string, unknown> : {};
const list = (value: unknown): unknown[] => Array.isArray(value) ? value : [];

export function adaptRun(raw: Record<string, unknown>): Run {
  return {
    id: text(raw.id), kind: text(raw.kind, 'chat') as Run['kind'], status: text(raw.status, 'queued') as Run['status'],
    conversationId: text(raw.conversation_id) || null, resultItineraryId: text(raw.result_itinerary_id) || null,
    createdAt: text(raw.created_at), updatedAt: text(raw.updated_at),
  };
}

export function adaptConversation(raw: Record<string, unknown>): ConversationSummary {
  return {
    id: text(raw.id), title: text(raw.title, '新的旅行对话'), status: text(raw.status, 'active') as ConversationSummary['status'],
    createdAt: text(raw.created_at), updatedAt: text(raw.updated_at), lastViewedAt: text(raw.last_viewed_at),
    hasActivePlanning: Boolean(raw.has_active_planning), hasWaitingUser: Boolean(raw.has_waiting_user),
    hasReadyBrief: Boolean(raw.has_ready_brief), hasUnreadCompleted: Boolean(raw.has_unread_completed),
  };
}

export function adaptMessage(raw: Record<string, unknown>): ConversationMessage {
  return {
    id: text(raw.id), role: text(raw.role, 'assistant') as ConversationMessage['role'], content: text(raw.content),
    sequence: Number(raw.sequence ?? 0), relatedRunId: text(raw.related_run_id) || null,
    relatedItineraryId: text(raw.related_itinerary_id) || null, createdAt: text(raw.created_at),
  };
}

export function adaptBrief(raw: Record<string, unknown>): PlanningBrief {
  const data = record(raw.data ?? raw.summary ?? raw);
  return {
    id: text(raw.id ?? raw.brief_id), status: text(raw.status, 'collecting') as PlanningBrief['status'],
    destination: text(data.destination), startDate: text(data.start_date), endDate: text(data.end_date), days: Number(data.days ?? 0),
    pace: text(data.habit_preference, '轻松悠闲'), companions: text(data.companion_context, '同行情况待确认'),
    interests: [text(data.attraction_preference), text(data.food_preference)].filter(Boolean),
    memories: list(raw.memory_context ?? data.memory_context).map(String),
    missingFields: list(raw.missing_fields).map(String),
  };
}

export function adaptMemory(raw: Record<string, unknown>): ProfileMemory {
  return {
    id: text(raw.id), category: text(raw.category, 'other_travel_preference') as ProfileMemory['category'],
    value: text(raw.value_text), polarity: text(raw.polarity, 'fact') as ProfileMemory['polarity'],
    status: text(raw.status, 'active') as ProfileMemory['status'], scopeType: text(raw.scope_type, 'global') as ProfileMemory['scopeType'],
  };
}

function adaptStop(value: unknown, day: number, index: number): TripStop {
  const raw = record(value); const location = record(raw.location);
  const nativeType = text(raw.type, 'attraction');
  const type: TripStop['type'] = ['lunch', 'dinner', 'restaurant', 'food'].includes(nativeType) ? 'food' : nativeType === 'walk' ? 'walk' : nativeType === 'hotel' ? 'hotel' : 'attraction';
  const latitude = Number(location.lat ?? location.latitude ?? 25.693 + day * 0.01 + index * 0.004);
  const longitude = Number(location.lng ?? location.longitude ?? 100.165 + day * 0.01 + index * 0.004);
  const name = text(raw.name, `地点 ${index + 1}`);
  return {
    id: text(raw.id, `d${day}-${index + 1}`), type, name, category: type === 'food' ? '餐饮' : type === 'walk' ? '漫步' : '景点',
    start: text(raw.start_time ?? raw.start, index === 0 ? '09:00' : '14:00'), end: text(raw.end_time ?? raw.end, index === 0 ? '11:30' : '17:00'),
    duration: text(raw.duration, '2小时'), transport: text(raw.transport ?? raw.distance_from_prev, index ? '驾车约 20 分钟' : '从住处出发'),
    note: text(raw.note ?? raw.description ?? raw.tips, '轻舟已为这个地点留出舒适的游玩时间。'),
    image: /山|雪/.test(name) ? images.mountain : type === 'food' ? images.food : images.dali,
    coordinate: {latitude, longitude}, raw,
  };
}

function adaptDay(value: unknown, index: number): TripDay {
  const raw = record(value); const day = Number(raw.day ?? index + 1);
  return {
    id: `day-${day}`, day, label: `Day ${day}`, date: text(raw.date, `第 ${day} 天`), weather: text(raw.weather, '天气待更新'),
    theme: text(raw.theme, '自在漫游'), stops: list(raw.timeline ?? raw.stops).map((item, stopIndex) => adaptStop(item, day, stopIndex)),
  };
}

export function adaptTripEnvelope(envelope: Record<string, unknown>): TripPlan {
  const plan = record(envelope.plan ?? envelope); const days = list(plan.days).map(adaptDay);
  const startDate = text(plan.start_date); const endDate = text(plan.end_date);
  return {
    id: text(envelope.id ?? plan.id), title: text(plan.title, `${text(plan.destination, '旅行')}深度漫游`), destination: text(plan.destination, '目的地待定'),
    dateRange: startDate && endDate ? `${startDate} — ${endDate} · ${days.length}天` : `${days.length}天行程`, startDate, endDate,
    status: 'completed', daysCount: days.length, placesCount: days.reduce((sum, day) => sum + day.stops.length, 0),
    tags: list(plan.tags ?? record(plan.preferences).attraction).map(String).slice(0, 3), cover: images.cover, days, version: Number(envelope.version ?? 1),
  };
}
