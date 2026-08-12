import * as Keychain from 'react-native-keychain';
import {createMMKV, type MMKV} from 'react-native-mmkv';
import type {AuthSession, ProfileMemory, TripPlan} from '../types';

const AUTH_SERVICE = 'com.qingzhou.travel.auth';
let mmkv: MMKV | null = null;

const getStorage = (): MMKV | null => {
  if (mmkv) {return mmkv;}
  try {mmkv = createMMKV({id: 'qingzhou.preferences'});} catch {mmkv = null;}
  return mmkv;
};

export const secureSession = {
  async load(): Promise<AuthSession | null> {
    try {
      const value = await Keychain.getGenericPassword({service: AUTH_SERVICE});
      return value ? JSON.parse(value.password) as AuthSession : null;
    } catch {return null;}
  },
  async save(session: AuthSession): Promise<void> {
    await Keychain.setGenericPassword('qingzhou', JSON.stringify(session), {
      service: AUTH_SERVICE,
      accessible: Keychain.ACCESSIBLE.WHEN_UNLOCKED_THIS_DEVICE_ONLY,
    });
  },
  async clear(): Promise<void> {await Keychain.resetGenericPassword({service: AUTH_SERVICE});},
};

export const localCache = {
  get<T>(key: string): T | null {
    try {const raw = getStorage()?.getString(key); return raw ? JSON.parse(raw) as T : null;} catch {return null;}
  },
  set(key: string, value: unknown): void {
    try {getStorage()?.set(key, JSON.stringify(value));} catch {}
  },
  remove(key: string): void {try {getStorage()?.remove(key);} catch {}},
  loadDemoTrips: () => localCache.get<TripPlan[]>('demo.trips'),
  saveDemoTrips: (trips: TripPlan[]) => localCache.set('demo.trips', trips),
  loadDemoMemories: () => localCache.get<ProfileMemory[]>('demo.memories'),
  saveDemoMemories: (memories: ProfileMemory[]) => localCache.set('demo.memories', memories),
};
