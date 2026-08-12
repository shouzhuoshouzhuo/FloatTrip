import {AppState, type AppStateStatus} from 'react-native';
import EventSource, {type EventSourceListener} from 'react-native-sse';
import {API_BASE_URL} from './api';
import type {RunEvent} from '../types';
import {parseEventPayload} from '../utils/planning';

type StreamCallbacks = {onEvent: (event: RunEvent) => void; onDisconnected?: () => void; onError?: (error: Error) => void};
const eventNames = ['messages', 'custom', 'error', 'heartbeat', 'end'] as const;

export class RunStream {
  private source: EventSource<string> | null = null;
  private cursor = 0;
  private retry = 0;
  private timer: ReturnType<typeof setTimeout> | null = null;
  private appState: AppStateStatus = AppState.currentState;
  private subscription?: {remove: () => void};
  private stopped = false;

  constructor(private token: string, private runId: string, private callbacks: StreamCallbacks) {}

  start(): void {
    this.stopped = false;
    this.subscription = AppState.addEventListener('change', state => {
      const wasBackground = this.appState !== 'active'; this.appState = state;
      if (state !== 'active') {this.closeSource();}
      else if (wasBackground && !this.stopped) {this.connect();}
    });
    this.connect();
  }

  stop(): void {this.stopped = true; this.closeSource(); this.subscription?.remove(); if (this.timer) {clearTimeout(this.timer);}}

  private connect(): void {
    if (this.stopped || this.appState !== 'active') {return;}
    this.closeSource();
    const url = `${API_BASE_URL}/api/runs/${this.runId}/stream?after_seq=${this.cursor}`;
    const source = new EventSource<string>(url, {headers: {Authorization: `Bearer ${this.token}`, 'Last-Event-ID': String(this.cursor)}, pollingInterval: 0, timeout: 30_000});
    this.source = source;
    source.addEventListener('open', () => {this.retry = 0;});
    eventNames.forEach(name => {
      source.addEventListener(name, ((event: {data: string | null; lastEventId: string | null}) => {
        try {
          const sequence = Number(event.lastEventId || 0); if (sequence) {this.cursor = Math.max(this.cursor, sequence);}
          const payload = parseEventPayload(event.data);
          this.callbacks.onEvent({runId: this.runId, sequence, kind: name, payload});
          if (name === 'end' || name === 'error') {this.closeSource();}
        } catch (error) {this.callbacks.onError?.(error as Error);}
      }) as EventSourceListener<string>);
    });
    source.addEventListener('error', (() => {this.callbacks.onDisconnected?.(); this.scheduleReconnect();}) as EventSourceListener<string>);
  }

  private scheduleReconnect(): void {
    if (this.stopped || this.timer) {return;}
    const delay = Math.min(16_000, 1_000 * 2 ** this.retry++);
    this.timer = setTimeout(() => {this.timer = null; this.connect();}, delay);
  }
  private closeSource(): void {this.source?.removeAllEventListeners(); this.source?.close(); this.source = null;}
}
