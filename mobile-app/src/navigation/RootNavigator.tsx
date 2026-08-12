import React, {useEffect} from 'react';
import {ActivityIndicator, StyleSheet, View} from 'react-native';
import {NavigationContainer, DefaultTheme} from '@react-navigation/native';
import {createNativeStackNavigator} from '@react-navigation/native-stack';
import {createBottomTabNavigator} from '@react-navigation/bottom-tabs';
import {enableScreens} from 'react-native-screens';
import {Icon} from '../components/ui';
import {colors} from '../theme';
import {useAppStore} from '../store/useAppStore';
import {AuthScreen} from '../screens/AuthScreen';
import {PlanHomeScreen} from '../screens/PlanHomeScreen';
import {TripsScreen} from '../screens/TripsScreen';
import {ProfileScreen} from '../screens/ProfileScreen';
import {ConversationScreen} from '../screens/ConversationScreen';
import {ConversationHistoryScreen} from '../screens/ConversationHistoryScreen';
import {TripMapScreen} from '../screens/TripMapScreen';
import {TripEditorScreen} from '../screens/TripEditorScreen';
import {setUnauthorizedHandler} from '../services/api';
import type {MainTabParamList, RootStackParamList} from './types';

enableScreens(true);
const Stack = createNativeStackNavigator<RootStackParamList>();
const Tabs = createBottomTabNavigator<MainTabParamList>();

function MainTabs() {
  return (
    <Tabs.Navigator screenOptions={({route}) => ({headerShown: false, tabBarActiveTintColor: colors.ink, tabBarInactiveTintColor: colors.inkFaint,
      tabBarStyle: styles.tabBar, tabBarLabelStyle: styles.tabLabel,
      tabBarIcon: ({color, size}) => <Icon name={route.name === 'Plan' ? 'message-processing-outline' : route.name === 'Trips' ? 'map-marker-path' : 'account-circle-outline'} color={color} size={size + 2} />})}>
      <Tabs.Screen name="Plan" component={PlanHomeScreen} options={{title: '规划'}} />
      <Tabs.Screen name="Trips" component={TripsScreen} options={{title: '行程'}} />
      <Tabs.Screen name="Profile" component={ProfileScreen} options={{title: '我的'}} />
    </Tabs.Navigator>
  );
}

export function RootNavigator() {
  const {hydrated, session, mode, hydrate} = useAppStore();
  useEffect(() => {void hydrate();}, [hydrate]);
  useEffect(() => {
    setUnauthorizedHandler(() => {useAppStore.getState().logout().catch(() => undefined);});
    return () => setUnauthorizedHandler(undefined);
  }, []);
  if (!hydrated) {return <View style={styles.loading}><ActivityIndicator color={colors.blue} /></View>;}
  const entered = Boolean(session) || mode === 'demo';
  return (
    <NavigationContainer theme={{...DefaultTheme, colors: {...DefaultTheme.colors, background: colors.canvas, card: colors.canvas, border: colors.line}}}>
      <Stack.Navigator screenOptions={{headerShown: false, animation: 'slide_from_right'}}>
        {!entered ? <Stack.Screen name="Auth" component={AuthScreen} /> : <>
          <Stack.Screen name="Main" component={MainTabs} />
          <Stack.Screen name="ConversationHistory" component={ConversationHistoryScreen} />
          <Stack.Screen name="Conversation" component={ConversationScreen} />
          <Stack.Screen name="TripMap" component={TripMapScreen} options={{animation: 'fade'}} />
          <Stack.Screen name="TripEditor" component={TripEditorScreen} />
        </>}
      </Stack.Navigator>
    </NavigationContainer>
  );
}

const styles = StyleSheet.create({
  loading: {flex: 1, alignItems: 'center', justifyContent: 'center', backgroundColor: colors.canvas},
  tabBar: {position: 'absolute', left: 24, right: 24, bottom: 16, height: 70, borderRadius: 30, backgroundColor: colors.paper, borderTopWidth: 0, paddingTop: 8, paddingBottom: 10, marginHorizontal: 20},
  tabLabel: {fontSize: 12, fontWeight: '700'},
});
