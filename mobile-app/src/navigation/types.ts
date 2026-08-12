import type {NavigatorScreenParams} from '@react-navigation/native';

export type MainTabParamList = {Plan: undefined; Trips: undefined; Profile: undefined};
export type RootStackParamList = {
  Auth: undefined;
  Main: NavigatorScreenParams<MainTabParamList> | undefined;
  ConversationHistory: undefined;
  Conversation: {prompt?: string; conversationId?: string} | undefined;
  TripMap: {tripId: string};
  TripEditor: {tripId: string; dayId?: string};
};
