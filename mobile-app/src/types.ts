import type {ImageSourcePropType} from 'react-native';

export type AuthSession = {userId: string; username: string; token: string};
export type AppMode = 'online' | 'demo';
export type PlanningState = 'collecting' | 'ready' | 'planning' | 'completed' | 'editing';

export type Coordinate = {latitude: number; longitude: number};
export type MapMarker = {
  id: string;
  title: string;
  coordinate: Coordinate;
  index: number;
  kind: 'attraction' | 'food' | 'walk' | 'hotel';
  selected: boolean;
};
export type RoutePolyline = {id: string; coordinates: Coordinate[]; color: string; width: number};

export type ConversationMessage = {
  id: string;
  role: 'user' | 'assistant' | 'system';
  content: string;
  sequence?: number;
  relatedRunId?: string | null;
  relatedItineraryId?: string | null;
  createdAt?: string;
};

export type ConversationSummary = {
  id: string;
  title: string;
  status: 'active' | 'archived';
  createdAt: string;
  updatedAt: string;
  lastViewedAt?: string;
  hasActivePlanning: boolean;
  hasWaitingUser: boolean;
  hasReadyBrief: boolean;
  hasUnreadCompleted: boolean;
};

export type PlanningBrief = {
  id?: string;
  status: 'collecting' | 'ready' | 'submitted' | 'discarded';
  destination: string;
  startDate: string;
  endDate: string;
  days: number;
  pace: string;
  companions: string;
  interests: string[];
  memories: string[];
  missingFields: string[];
};

export type ThoughtStep = {id: string; title: string; detail: string; completed: boolean; active?: boolean};

export type TripStop = {
  id: string;
  type: 'attraction' | 'food' | 'walk' | 'hotel';
  name: string;
  category: string;
  start: string;
  end: string;
  duration: string;
  transport: string;
  note: string;
  image: ImageSourcePropType;
  coordinate: Coordinate;
  raw?: Record<string, unknown>;
};

export type TripDay = {
  id: string;
  day: number;
  label: string;
  date: string;
  weather: string;
  theme: string;
  stops: TripStop[];
};

export type TripPlan = {
  id: string;
  title: string;
  destination: string;
  dateRange: string;
  startDate: string;
  endDate: string;
  status: 'planning' | 'completed';
  daysCount: number;
  placesCount: number;
  tags: string[];
  cover: ImageSourcePropType;
  days: TripDay[];
  version?: number;
};

export type MemoryCategory =
  | 'attraction_preference' | 'food_preference' | 'dietary_requirement'
  | 'travel_pace' | 'budget_style' | 'transport_preference'
  | 'accommodation_preference' | 'schedule_preference' | 'companion_context'
  | 'accessibility_need' | 'destination_history' | 'other_travel_preference';
export type MemoryPolarity = 'prefer' | 'avoid' | 'require' | 'fact';
export type ProfileMemory = {
  id: string;
  category: MemoryCategory;
  value: string;
  polarity: MemoryPolarity;
  status: 'active' | 'candidate';
  scopeType: 'global' | 'destination' | 'companion' | 'destination_companion';
};

export type Run = {
  id: string;
  kind: 'chat' | 'travel_plan' | 'revision';
  status: 'queued' | 'running' | 'waiting_user' | 'succeeded' | 'failed' | 'cancelled';
  conversationId?: string | null;
  resultItineraryId?: string | null;
  createdAt?: string;
  updatedAt?: string;
};

export type RunEvent = {
  runId: string;
  sequence?: number;
  kind: 'messages' | 'custom' | 'error' | 'heartbeat' | 'end';
  payload: Record<string, unknown>;
  durable?: boolean;
};

export type AppSessionState = {
  hydrated: boolean;
  mode: AppMode;
  session: AuthSession | null;
  trips: TripPlan[];
  memories: ProfileMemory[];
  planningState: PlanningState;
};
