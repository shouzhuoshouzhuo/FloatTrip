import {NativeModules, Platform} from 'react-native';
import type {AuthSession, ConversationMessage, ConversationSummary, MemoryCategory, MemoryPolarity, PlanningBrief, ProfileMemory, Run, TripPlan} from '../types';
import {adaptBrief, adaptConversation, adaptMemory, adaptMessage, adaptRun, adaptTripEnvelope} from './mappers';

type RequestOptions = RequestInit & {token?: string};

let unauthorizedHandler: (() => void) | undefined;

export function setUnauthorizedHandler(handler: (() => void) | undefined): void {
  unauthorizedHandler = handler;
}

export class ApiError extends Error {
  constructor(public status: number, public detail: unknown) {
    super(typeof detail === 'string' ? detail : '请求没有完成');
  }
}

const metroHost = (): string => {
  const scriptURL = String(NativeModules.SourceCode?.scriptURL ?? '');
  const match = scriptURL.match(/^https?:\/\/([^/:]+)/);
  return match?.[1] ?? (Platform.OS === 'android' ? '10.0.2.2' : '127.0.0.1');
};

export const API_BASE_URL = __DEV__ ? `http://${metroHost()}:8000` : 'https://api.qingzhou.app';

async function request<T>(path: string, options: RequestOptions = {}): Promise<T> {
  const headers = new Headers(options.headers);
  if (options.body && !headers.has('Content-Type')) {headers.set('Content-Type', 'application/json');}
  if (options.token) {headers.set('Authorization', `Bearer ${options.token}`);}
  const controller = new AbortController();
  const timeout = setTimeout(() => controller.abort(), 15_000);
  try {
    const response = await fetch(`${API_BASE_URL}${path}`, {...options, headers, signal: options.signal ?? controller.signal});
    const text = await response.text();
    const data = text ? JSON.parse(text) as unknown : null;
    if (!response.ok) {
      if (response.status === 401) {unauthorizedHandler?.();}
      throw new ApiError(response.status, (data as {detail?: unknown} | null)?.detail ?? data);
    }
    return data as T;
  } finally {clearTimeout(timeout);}
}

const authFrom = (raw: Record<string, unknown>): AuthSession => ({
  userId: String(raw.user_id ?? ''), username: String(raw.username ?? ''), token: String(raw.token ?? ''),
});

export const api = {
  async login(username: string, password: string): Promise<AuthSession> {
    return authFrom(await request<Record<string, unknown>>('/api/auth/login', {method: 'POST', body: JSON.stringify({username, password})}));
  },
  async register(username: string, password: string): Promise<AuthSession> {
    return authFrom(await request<Record<string, unknown>>('/api/auth/register', {method: 'POST', body: JSON.stringify({username, password})}));
  },
  async listTrips(token: string): Promise<TripPlan[]> {
    const rows = await request<Array<Record<string, unknown>>>('/api/history', {token});
    const envelopes = await Promise.all(rows.map(row => request<Record<string, unknown>>(`/api/history/${String(row.id)}`, {token})));
    return envelopes.map(adaptTripEnvelope);
  },
  async getTrip(token: string, id: string): Promise<TripPlan> {
    return adaptTripEnvelope(await request<Record<string, unknown>>(`/api/history/${id}`, {token}));
  },
  async getProfile(token: string): Promise<{memories: ProfileMemory[]; tripCount: number; revision: number}> {
    const raw = await request<Record<string, unknown>>('/api/profile', {token});
    const active = Array.isArray(raw.active_facts) ? raw.active_facts : [];
    const candidates = Array.isArray(raw.candidate_facts) ? raw.candidate_facts : [];
    return {memories: [...active, ...candidates].map(item => adaptMemory(item as Record<string, unknown>)), tripCount: Number(raw.trip_count ?? 0), revision: Number(raw.revision ?? 0)};
  },
  async createMemory(token: string, input: {category: MemoryCategory; value: string; polarity: MemoryPolarity}): Promise<ProfileMemory> {
    return adaptMemory(await request<Record<string, unknown>>('/api/memories', {token, method: 'POST', body: JSON.stringify({category: input.category, value_text: input.value, polarity: input.polarity, scope_type: 'global', scope_key: {}})}));
  },
  async updateMemory(token: string, id: string, input: {category: MemoryCategory; value: string; polarity: MemoryPolarity}): Promise<ProfileMemory> {
    return adaptMemory(await request<Record<string, unknown>>(`/api/memories/${id}`, {token, method: 'PATCH', body: JSON.stringify({category: input.category, value_text: input.value, polarity: input.polarity})}));
  },
  async approveMemory(token: string, id: string): Promise<ProfileMemory> {
    return adaptMemory(await request<Record<string, unknown>>(`/api/memories/${id}/approve`, {token, method: 'POST'}));
  },
  deleteMemory: (token: string, id: string) => request(`/api/memories/${id}`, {token, method: 'DELETE'}),
  async createConversation(token: string, title = '新的旅行对话'): Promise<Record<string, unknown>> {
    return request('/api/conversations', {token, method: 'POST', body: JSON.stringify({title})});
  },
  async listConversations(token: string): Promise<ConversationSummary[]> {
    return (await request<Array<Record<string, unknown>>>('/api/conversations', {token})).map(adaptConversation);
  },
  async getConversation(token: string, conversationId: string): Promise<ConversationSummary> {
    return adaptConversation(await request<Record<string, unknown>>(`/api/conversations/${conversationId}`, {token}));
  },
  async markConversationViewed(token: string, conversationId: string): Promise<ConversationSummary> {
    return adaptConversation(await request<Record<string, unknown>>(`/api/conversations/${conversationId}/view`, {token, method: 'POST'}));
  },
  async getMessages(token: string, conversationId: string, afterSequence = 0): Promise<ConversationMessage[]> {
    return (await request<Array<Record<string, unknown>>>(`/api/conversations/${conversationId}/messages?after_sequence=${afterSequence}&limit=200`, {token})).map(adaptMessage);
  },
  async sendMessage(token: string, conversationId: string, content: string): Promise<{message: ConversationMessage; run: Run}> {
    const raw = await request<{message: Record<string, unknown>; run: Record<string, unknown>}>(`/api/conversations/${conversationId}/messages`, {token, method: 'POST', body: JSON.stringify({content})});
    return {message: adaptMessage(raw.message), run: adaptRun(raw.run)};
  },
  async getBrief(token: string, conversationId: string): Promise<PlanningBrief | null> {
    const raw = await request<Record<string, unknown> | null>(`/api/conversations/${conversationId}/planning-brief`, {token});
    return raw ? adaptBrief(raw) : null;
  },
  async updateBrief(token: string, briefId: string, patch: Record<string, unknown>): Promise<PlanningBrief> {
    return adaptBrief(await request<Record<string, unknown>>(`/api/planning-briefs/${briefId}`, {token, method: 'PATCH', body: JSON.stringify(patch)}));
  },
  async submitBrief(token: string, briefId: string): Promise<{brief: PlanningBrief; run: Run}> {
    const raw = await request<{brief: Record<string, unknown>; run: Record<string, unknown>}>(`/api/planning-briefs/${briefId}/submit`, {token, method: 'POST'});
    return {brief: adaptBrief(raw.brief), run: adaptRun(raw.run)};
  },
  async getRun(token: string, runId: string): Promise<Run> {return adaptRun(await request<Record<string, unknown>>(`/api/runs/${runId}`, {token}));},
  async listActiveRuns(token: string): Promise<Run[]> {
    return (await request<Array<Record<string, unknown>>>('/api/runs?active_only=true', {token})).map(adaptRun);
  },
  async listRuns(token: string, conversationId: string, activeOnly = false): Promise<Run[]> {
    const params = new URLSearchParams({conversation_id: conversationId, active_only: String(activeOnly)});
    return (await request<Array<Record<string, unknown>>>(`/api/runs?${params}`, {token})).map(adaptRun);
  },
  retryRun: async (token: string, runId: string): Promise<Run> => adaptRun(await request<Record<string, unknown>>(`/api/runs/${runId}/retry`, {token, method: 'POST'})),
  resumeRun: async (token: string, runId: string, interactionId: string, value: unknown): Promise<Run> => adaptRun(await request<Record<string, unknown>>(`/api/runs/${runId}/resume`, {token, method: 'POST', body: JSON.stringify({interaction_id: interactionId, value})})),
  async saveTimeline(token: string, trip: TripPlan): Promise<TripPlan> {
    const days = trip.days.map(day => ({day: day.day, timeline: day.stops.map(item => ({...item.raw, type: item.type === 'food' ? 'lunch' : item.type, name: item.name, start_time: item.start, end_time: item.end, note: item.note, location: {lat: item.coordinate.latitude, lng: item.coordinate.longitude}}))}));
    const raw = await request<Record<string, unknown>>(`/api/plan/${trip.id}/timeline`, {token, method: 'PUT', body: JSON.stringify({days})});
    return adaptTripEnvelope({id: trip.id, plan: raw.plan});
  },
  async walkingRoute(token: string, origin: {latitude: number; longitude: number}, destination: {latitude: number; longitude: number}) {
    const params = new URLSearchParams({origin_lng: String(origin.longitude), origin_lat: String(origin.latitude), dest_lng: String(destination.longitude), dest_lat: String(destination.latitude)});
    return request<{coords: [number, number][]; distance: string; duration: string}>(`/api/route/walking?${params}`, {token});
  },
};
