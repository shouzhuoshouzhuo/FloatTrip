import type {TripPlan, TripStop} from '../types';

export type EditHistory = {present: TripPlan; past: TripPlan[]; future: TripPlan[]};

export function commitEdit(history: EditHistory, next: TripPlan): EditHistory {
  return {present: next, past: [...history.past, history.present], future: []};
}
export function undoEdit(history: EditHistory): EditHistory {
  const previous = history.past.at(-1); if (!previous) {return history;}
  return {present: previous, past: history.past.slice(0, -1), future: [history.present, ...history.future]};
}
export function redoEdit(history: EditHistory): EditHistory {
  const next = history.future[0]; if (!next) {return history;}
  return {present: next, past: [...history.past, history.present], future: history.future.slice(1)};
}
export function optimizeStopOrder(stops: TripStop[]): TripStop[] {
  return [...stops].sort((a, b) => a.coordinate.longitude - b.coordinate.longitude || a.coordinate.latitude - b.coordinate.latitude);
}
export function replaceStop(stops: TripStop[], id: string, replacement: TripStop): TripStop[] {
  return stops.map(stop => stop.id === id ? replacement : stop);
}
export function removeStop(stops: TripStop[], id: string): TripStop[] {return stops.filter(stop => stop.id !== id);}

export function fromLngLatPairs(pairs: [number, number][]) {return pairs.map(([longitude, latitude]) => ({latitude, longitude}));}
