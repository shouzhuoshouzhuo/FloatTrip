import React, {useEffect, useMemo, useRef, useState} from 'react';
import {Image, PermissionsAndroid, Platform, Pressable, ScrollView, StyleSheet, Text, View} from 'react-native';
import {useSafeAreaInsets} from 'react-native-safe-area-context';
import type {NativeStackScreenProps} from '@react-navigation/native-stack';
import BottomSheet, {BottomSheetScrollView} from '@gorhom/bottom-sheet';
import {QZAMapView, type QZAMapHandle} from '../native/QZAMapView';
import {useAppStore} from '../store/useAppStore';
import type {Coordinate, MapMarker, RoutePolyline, TripStop} from '../types';
import type {RootStackParamList} from '../navigation/types';
import {Icon, IconButton} from '../components/ui';
import {colors, radii, softShadow, spacing, type} from '../theme';
import {api} from '../services/api';
import {fromLngLatPairs} from '../utils/tripEditor';

type Props = NativeStackScreenProps<RootStackParamList, 'TripMap'>;

export function TripMapScreen({navigation, route}: Props) {
  const insets = useSafeAreaInsets(); const {trips, mode, session} = useAppStore();
  const trip = trips.find(item => item.id === route.params.tripId) ?? trips[0]; const [dayIndex, setDayIndex] = useState(0); const [selectedId, setSelectedId] = useState(trip?.days[0]?.stops[0]?.id ?? '');
  const [sheetIndex, setSheetIndex] = useState(1); const [recommendations, setRecommendations] = useState(true); const mapRef = useRef<QZAMapHandle>(null); const sheetRef = useRef<BottomSheet>(null);
  const [routeCoordinates, setRouteCoordinates] = useState<Coordinate[]>([]); const snapPoints = useMemo(() => ['22%', '54%', '91%'], []); const day = trip?.days[dayIndex];
  useEffect(() => {
    if (Platform.OS === 'android') {void PermissionsAndroid.request(PermissionsAndroid.PERMISSIONS.ACCESS_FINE_LOCATION);}
  }, []);
  useEffect(() => {
    const stops = day?.stops ?? [];
    setRouteCoordinates(stops.map(item => item.coordinate));
    if (mode !== 'online' || !session || stops.length < 2) {return;}
    let cancelled = false;
    Promise.all(stops.slice(0, -1).map((stop, index) => api.walkingRoute(session.token, stop.coordinate, stops[index + 1].coordinate)))
      .then(routes => {
        if (cancelled) {return;}
        setRouteCoordinates(routes.flatMap((item, index) => fromLngLatPairs(index ? item.coords.slice(1) : item.coords)));
      })
      .catch(() => undefined);
    return () => {cancelled = true;};
  }, [day, mode, session]);
  // Native maps open at the simulator's current location by default. Once the
  // day's markers have been committed, frame the itinerary instead.
  useEffect(() => {
    const coordinates = day?.stops.map(stop => stop.coordinate) ?? [];
    if (!coordinates.length) {return;}
    const timer = setTimeout(() => mapRef.current?.fit(coordinates), 180);
    return () => clearTimeout(timer);
  }, [day?.id, day?.stops]);
  const markers: MapMarker[] = (day?.stops ?? []).map((stop, index) => ({id: stop.id, title: stop.name, coordinate: stop.coordinate, index: index + 1, kind: stop.type, selected: stop.id === selectedId}));
  const polylines: RoutePolyline[] = day ? [{id: `route-${day.id}`, coordinates: routeCoordinates, color: colors.mapOrange, width: 7}] : [];
  const chooseDay = (index: number) => {setDayIndex(index); const stops = trip.days[index].stops; setSelectedId(stops[0]?.id ?? ''); setTimeout(() => mapRef.current?.fit(stops.map(item => item.coordinate)), 120);};
  const chooseStop = (stop: TripStop) => {setSelectedId(stop.id); mapRef.current?.moveTo(stop.coordinate, 15); if (sheetIndex === 0) {sheetRef.current?.snapToIndex(1);}};
  if (!trip || !day) {return <View style={styles.root}><Text>行程不存在</Text></View>;}
  return (
    <View style={styles.root}>
      <QZAMapView ref={mapRef} markers={markers} polylines={polylines} selectedMarkerId={selectedId} showsUserLocation mapPaddingBottom={sheetIndex === 0 ? 180 : sheetIndex === 1 ? 430 : 680}
        onMarkerPress={id => {const stop = day.stops.find(item => item.id === id); if (stop) {chooseStop(stop);}}} />
      <View style={[styles.mapHeader, {top: insets.top + 10}]}><IconButton name="arrow-left" label="返回" onPress={navigation.goBack} /><View style={styles.mapHeaderActions}><IconButton name="crosshairs-gps" label="定位" /><IconButton name="dots-horizontal" label="更多" /></View></View>
      <Pressable onPress={() => setRecommendations(value => !value)} style={[styles.recommendToggle, {top: insets.top + 70}]}><View style={[styles.toggleTrack, recommendations && styles.toggleTrackActive]}><View style={[styles.toggleKnob, recommendations && styles.toggleKnobActive]} /></View><Text style={styles.toggleText}>推荐地点</Text></Pressable>
      <BottomSheet ref={sheetRef} index={1} snapPoints={snapPoints} onChange={setSheetIndex} enableDynamicSizing={false} backgroundStyle={styles.sheetBackground} handleIndicatorStyle={styles.handle}>
        <View style={styles.dateTabs}><ScrollView horizontal showsHorizontalScrollIndicator={false} contentContainerStyle={styles.dateTabsInner}>
          <Pressable style={styles.dateTab}><Text style={styles.dateMuted}>总览</Text></Pressable>{trip.days.map((item, index) => <Pressable key={item.id} onPress={() => chooseDay(index)} style={[styles.dateTab, index === dayIndex && styles.dateTabActive]}><Text style={[styles.dateMuted, index === dayIndex && styles.dateActive]}>{item.date}</Text></Pressable>)}
        </ScrollView></View>
        <BottomSheetScrollView contentContainerStyle={[styles.sheetContent, {paddingBottom: insets.bottom + 110}]}>
          <View style={styles.dayHead}><View><Text style={styles.dayTitle}>{day.date}</Text><Text style={styles.dayTheme}>{day.theme}</Text></View><View style={styles.weather}><Icon name="weather-sunny" size={18} color={colors.warning} /><Text style={styles.weatherText}>{day.weather}</Text></View></View>
          {day.stops.map((stop, index) => <React.Fragment key={stop.id}>
            <Pressable onPress={() => chooseStop(stop)} style={[styles.stop, stop.id === selectedId && styles.stopSelected]}>
              <Image source={stop.image} style={styles.stopImage} /><View style={styles.stopBody}><Text style={styles.stopCategory}>{stop.category}</Text><Text style={styles.stopTitle}>{index + 1}. {stop.name}</Text><View style={styles.stopNote}><View style={styles.stopTimeRow}><Text style={styles.stopTime}>{stop.start} - {stop.end}</Text><Icon name="pencil-outline" size={18} color={colors.inkFaint} /></View><Text style={styles.stopDescription}>{stop.note}</Text></View></View>
            </Pressable>
            {index < day.stops.length - 1 && <View style={styles.transport}><Icon name="walk" size={16} color={colors.inkFaint} /><Text style={styles.transportText}>{day.stops[index + 1].transport}</Text><Icon name="chevron-right" size={17} color={colors.inkFaint} /></View>}
          </React.Fragment>)}
        </BottomSheetScrollView>
      </BottomSheet>
      <View style={[styles.actions, {bottom: insets.bottom + 12}]}>
        <Pressable onPress={() => navigation.navigate('Conversation', {prompt: `我想调整${trip.title}的${day.date}`})} style={styles.chat}><Icon name="creation" color={colors.paper} /><Text style={styles.chatText}>给轻舟发消息</Text></Pressable>
        <Pressable testID="open-trip-editor" onPress={() => navigation.navigate('TripEditor', {tripId: trip.id, dayId: day.id})} style={styles.edit}><Icon name="tune-variant" /><Text style={styles.editText}>编辑</Text></Pressable>
        <Pressable onPress={() => navigation.navigate('TripEditor', {tripId: trip.id, dayId: day.id})} style={styles.add}><Icon name="plus" color={colors.paper} size={28} /></Pressable>
      </View>
    </View>
  );
}

const styles = StyleSheet.create({
  root: {flex: 1, backgroundColor: colors.canvas}, mapHeader: {position: 'absolute', left: 16, right: 16, flexDirection: 'row', alignItems: 'center', justifyContent: 'space-between'}, mapHeaderActions: {flexDirection: 'row', gap: 8},
  recommendToggle: {...softShadow, position: 'absolute', left: 16, backgroundColor: colors.paper, borderRadius: radii.pill, paddingHorizontal: 13, height: 42, flexDirection: 'row', alignItems: 'center', gap: 9}, toggleTrack: {width: 34, height: 20, borderRadius: 10, backgroundColor: colors.line, padding: 2}, toggleTrackActive: {backgroundColor: colors.blue}, toggleKnob: {width: 16, height: 16, borderRadius: 8, backgroundColor: colors.paper}, toggleKnobActive: {transform: [{translateX: 14}]}, toggleText: {...type.caption, color: colors.ink},
  sheetBackground: {backgroundColor: colors.paper, borderTopLeftRadius: 30, borderTopRightRadius: 30}, handle: {width: 42, height: 5, backgroundColor: '#C9CDD2'}, dateTabs: {height: 64, borderBottomWidth: 1, borderBottomColor: colors.line}, dateTabsInner: {paddingHorizontal: 8}, dateTab: {height: 64, paddingHorizontal: 14, justifyContent: 'center', borderBottomWidth: 3, borderBottomColor: 'transparent'}, dateTabActive: {borderBottomColor: colors.blue}, dateMuted: {...type.body, color: colors.inkFaint, fontWeight: '700'}, dateActive: {color: colors.ink},
  sheetContent: {paddingHorizontal: spacing.lg, paddingTop: 18}, dayHead: {flexDirection: 'row', justifyContent: 'space-between', alignItems: 'flex-start', marginBottom: 18}, dayTitle: {...type.title, color: colors.ink}, dayTheme: {...type.body, color: colors.ink, fontWeight: '700', marginTop: 4}, weather: {flexDirection: 'row', alignItems: 'center', gap: 5, backgroundColor: '#FFF7E9', borderRadius: radii.pill, paddingHorizontal: 10, paddingVertical: 7}, weatherText: {...type.caption, color: colors.inkMuted},
  stop: {flexDirection: 'row', gap: 14, padding: 8, borderRadius: radii.lg}, stopSelected: {backgroundColor: '#F4FBFE'}, stopImage: {width: 78, height: 78, borderRadius: 22}, stopBody: {flex: 1}, stopCategory: {...type.caption, color: colors.green, fontWeight: '700'}, stopTitle: {...type.section, color: colors.ink, marginTop: 2}, stopNote: {marginTop: 10, borderRadius: radii.md, backgroundColor: colors.canvas, padding: 12}, stopTimeRow: {flexDirection: 'row', alignItems: 'center', justifyContent: 'space-between'}, stopTime: {...type.body, color: colors.ink}, stopDescription: {...type.body, color: colors.inkMuted, marginTop: 4},
  transport: {height: 52, marginLeft: 101, flexDirection: 'row', alignItems: 'center', gap: 6}, transportText: {...type.caption, color: colors.inkFaint},
  actions: {position: 'absolute', left: 18, right: 18, flexDirection: 'row', alignItems: 'center', gap: 10}, chat: {...softShadow, height: 54, borderRadius: radii.pill, backgroundColor: colors.blue, paddingHorizontal: 18, flex: 1, flexDirection: 'row', alignItems: 'center', gap: 8}, chatText: {...type.body, color: colors.paper, fontWeight: '700'}, edit: {...softShadow, height: 54, borderRadius: radii.pill, backgroundColor: colors.paper, paddingHorizontal: 18, flexDirection: 'row', alignItems: 'center', gap: 7}, editText: {...type.body, color: colors.ink, fontWeight: '700'}, add: {...softShadow, width: 54, height: 54, borderRadius: 27, backgroundColor: colors.ink, alignItems: 'center', justifyContent: 'center'},
});
