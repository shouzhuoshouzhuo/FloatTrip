import {create} from 'zustand';
import {demoMemories, demoTrips} from '../data/demo';
import {localCache, secureSession} from '../services/storage';
import type {AppMode, AuthSession, PlanningState, ProfileMemory, TripPlan} from '../types';

type AppStore = {
  hydrated: boolean;
  mode: AppMode;
  session: AuthSession | null;
  trips: TripPlan[];
  memories: ProfileMemory[];
  planningState: PlanningState;
  hydrate: () => Promise<void>;
  setSession: (session: AuthSession) => Promise<void>;
  startDemo: () => void;
  logout: () => Promise<void>;
  setTrips: (trips: TripPlan[]) => void;
  upsertTrip: (trip: TripPlan) => void;
  setMemories: (memories: ProfileMemory[]) => void;
  setPlanningState: (state: PlanningState) => void;
};

export const useAppStore = create<AppStore>((set, get) => ({
  hydrated: false, mode: 'online', session: null, trips: demoTrips, memories: demoMemories, planningState: 'collecting',
  hydrate: async () => {
    const session = await secureSession.load();
    const trips = localCache.loadDemoTrips() ?? demoTrips;
    const memories = localCache.loadDemoMemories() ?? demoMemories;
    set({hydrated: true, session, mode: 'online', trips, memories});
  },
  setSession: async session => {await secureSession.save(session); set({session, mode: 'online'});},
  startDemo: () => set({session: null, mode: 'demo', trips: localCache.loadDemoTrips() ?? demoTrips, memories: localCache.loadDemoMemories() ?? demoMemories}),
  logout: async () => {await secureSession.clear(); set({session: null, mode: 'online', planningState: 'collecting'});},
  setTrips: trips => {set({trips}); if (get().mode === 'demo') {localCache.saveDemoTrips(trips);}},
  upsertTrip: trip => {
    const trips = [trip, ...get().trips.filter(item => item.id !== trip.id)];
    set({trips}); if (get().mode === 'demo') {localCache.saveDemoTrips(trips);}
  },
  setMemories: memories => {set({memories}); if (get().mode === 'demo') {localCache.saveDemoMemories(memories);}},
  setPlanningState: planningState => set({planningState}),
}));
