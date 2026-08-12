import React, {useState} from 'react';
import {Image, Modal, Pressable, StyleSheet, Text, TextInput, View} from 'react-native';
import {useSafeAreaInsets} from 'react-native-safe-area-context';
import type {NativeStackScreenProps} from '@react-navigation/native-stack';
import DraggableFlatList, {ScaleDecorator, type RenderItemParams} from 'react-native-draggable-flatlist';
import {api} from '../services/api';
import {candidateStops} from '../data/demo';
import {useAppStore} from '../store/useAppStore';
import type {TripPlan, TripStop} from '../types';
import type {RootStackParamList} from '../navigation/types';
import {Icon, IconButton, PrimaryButton, ScreenHeader} from '../components/ui';
import {colors, radii, softShadow, spacing, type} from '../theme';
import {optimizeStopOrder, removeStop} from '../utils/tripEditor';

type Props = NativeStackScreenProps<RootStackParamList, 'TripEditor'>;

export function TripEditorScreen({navigation, route}: Props) {
  const insets = useSafeAreaInsets(); const {trips, mode, session, upsertTrip} = useAppStore();
  const original = trips.find(item => item.id === route.params.tripId) ?? trips[0]; const initialIndex = Math.max(0, original.days.findIndex(item => item.id === route.params.dayId));
  const [trip, setTrip] = useState<TripPlan>(original); const [dayIndex, setDayIndex] = useState(initialIndex); const [undo, setUndo] = useState<TripPlan[]>([]); const [redo, setRedo] = useState<TripPlan[]>([]);
  const [pickerOpen, setPickerOpen] = useState(false); const [replaceId, setReplaceId] = useState<string | null>(null); const [saving, setSaving] = useState(false); const [message, setMessage] = useState('');
  const day = trip.days[dayIndex]; const canUndo = undo.length > 0; const canRedo = redo.length > 0;
  const commit = (next: TripPlan) => {setUndo(stack => [...stack, trip]); setRedo([]); setTrip(next); setMessage('');};
  const updateStops = (stops: TripStop[]) => commit({...trip, days: trip.days.map((item, index) => index === dayIndex ? {...item, stops} : item), placesCount: trip.days.reduce((sum, item, index) => sum + (index === dayIndex ? stops.length : item.stops.length), 0)});
  const patchStop = (id: string, patch: Partial<TripStop>) => updateStops(day.stops.map(item => item.id === id ? {...item, ...patch} : item));
  const doUndo = () => {const previous = undo.at(-1); if (!previous) {return;} setRedo(stack => [trip, ...stack]); setTrip(previous); setUndo(stack => stack.slice(0, -1));};
  const doRedo = () => {const next = redo[0]; if (!next) {return;} setUndo(stack => [...stack, trip]); setTrip(next); setRedo(stack => stack.slice(1));};
  const optimize = () => {updateStops(optimizeStopOrder(day.stops)); setMessage('已按地理位置优化顺序，可点击撤销恢复。');};
  const chooseCandidate = (candidate: TripStop) => {const newStop = {...candidate, id: `${candidate.id}-${Date.now()}`}; updateStops(replaceId ? day.stops.map(item => item.id === replaceId ? newStop : item) : [...day.stops, newStop]); setPickerOpen(false); setReplaceId(null);};
  const save = async () => {
    setSaving(true); upsertTrip(trip);
    try {if (mode === 'online' && session) {upsertTrip(await api.saveTimeline(session.token, trip));} setMessage('行程已保存'); setTimeout(() => navigation.goBack(), 550);}
    catch {upsertTrip(original); setTrip(original); setMessage('保存失败，已恢复到修改前版本。');}
    finally {setSaving(false);}
  };
  const renderItem = ({item, drag, isActive, getIndex}: RenderItemParams<TripStop>) => <ScaleDecorator><View style={[styles.stopCard, isActive && styles.stopActive]}>
    <Pressable accessibilityLabel="拖动排序" onLongPress={drag} disabled={isActive} style={styles.drag}><Icon name="drag-vertical" color={colors.inkFaint} /></Pressable><Image source={item.image} style={styles.image} />
    <View style={styles.stopContent}><Text style={styles.stopIndex}>{(getIndex?.() ?? 0) + 1}. {item.name}</Text><View style={styles.timeRow}><TextInput value={item.start} onChangeText={value => patchStop(item.id, {start: value})} style={styles.timeInput} maxLength={5} keyboardType="numbers-and-punctuation" /><Text style={styles.dash}>—</Text><TextInput value={item.end} onChangeText={value => patchStop(item.id, {end: value})} style={styles.timeInput} maxLength={5} keyboardType="numbers-and-punctuation" /></View><Text numberOfLines={2} style={styles.note}>{item.note}</Text>
      <View style={styles.stopActions}><Pressable onPress={() => {setReplaceId(item.id); setPickerOpen(true);}} style={styles.link}><Icon name="swap-horizontal" size={17} color={colors.blueDeep} /><Text style={styles.linkText}>替换</Text></Pressable><Pressable onPress={() => updateStops(removeStop(day.stops, item.id))} style={styles.link}><Icon name="trash-can-outline" size={17} color={colors.danger} /><Text style={styles.deleteText}>删除</Text></Pressable></View>
    </View>
  </View></ScaleDecorator>;
  const headerRight = <View style={styles.history}><IconButton name="undo" label="撤销" disabled={!canUndo} onPress={doUndo} /><IconButton name="redo" label="重做" disabled={!canRedo} onPress={doRedo} /></View>;
  return (
    <View style={styles.root}>
      <View style={{paddingTop: insets.top}}><ScreenHeader title="编辑行程" subtitle={day.date} onBack={navigation.goBack} right={headerRight} /></View>
      <View style={styles.dayTabs}>{trip.days.map((item, index) => <Pressable key={item.id} onPress={() => setDayIndex(index)} style={[styles.dayTab, dayIndex === index && styles.dayTabActive]}><Text style={[styles.dayTabText, dayIndex === index && styles.dayTabTextActive]}>D{item.day}</Text></Pressable>)}</View>
      <View style={styles.tools}><Pressable testID="optimize-route" onPress={optimize} style={styles.tool}><Icon name="creation" color={colors.lavender} /><Text style={styles.toolText}>路线优化</Text></Pressable><Pressable testID="add-stop" onPress={() => {setReplaceId(null); setPickerOpen(true);}} style={styles.tool}><Icon name="map-marker-plus-outline" color={colors.blueDeep} /><Text style={styles.toolText}>添加地点</Text></Pressable></View>
      {message ? <Text style={styles.message}>{message}</Text> : null}
      <DraggableFlatList data={day.stops} keyExtractor={item => item.id} renderItem={renderItem} onDragEnd={({data}) => updateStops(data)} contentContainerStyle={styles.list} />
      <View style={[styles.footer, {paddingBottom: Math.max(insets.bottom, 12)}]}><Pressable onPress={navigation.goBack} style={styles.cancel}><Text style={styles.cancelText}>取消</Text></Pressable><PrimaryButton testID="save-trip" label="保存修改" loading={saving} icon="check" onPress={() => void save()} style={{flex: 1}} /></View>
      <Modal visible={pickerOpen} transparent animationType="slide" onRequestClose={() => setPickerOpen(false)}><Pressable style={styles.scrim} onPress={() => setPickerOpen(false)} /><View style={[styles.sheet, {paddingBottom: Math.max(insets.bottom, 18)}]}><View style={styles.handle} /><View style={styles.sheetHead}><View><Text style={styles.sheetTitle}>{replaceId ? '替换地点' : '添加地点'}</Text><Text style={styles.sheetSubtitle}>来自轻舟为当天筛选的候选地点</Text></View><IconButton name="close" label="关闭" onPress={() => setPickerOpen(false)} /></View>
        {candidateStops.map(candidate => <Pressable key={candidate.id} onPress={() => chooseCandidate(candidate)} style={styles.candidate}><Image source={candidate.image} style={styles.candidateImage} /><View style={styles.candidateCopy}><Text style={styles.candidateName}>{candidate.name}</Text><Text numberOfLines={2} style={styles.candidateNote}>{candidate.note}</Text></View><Icon name="plus-circle" color={colors.blue} size={26} /></Pressable>)}
      </View></Modal>
    </View>
  );
}

const styles = StyleSheet.create({
  root: {flex: 1, backgroundColor: colors.canvas}, history: {flexDirection: 'row', gap: 6}, dayTabs: {height: 54, flexDirection: 'row', paddingHorizontal: spacing.md, gap: 8, alignItems: 'center'}, dayTab: {width: 42, height: 36, borderRadius: radii.pill, alignItems: 'center', justifyContent: 'center', backgroundColor: colors.paper}, dayTabActive: {backgroundColor: colors.ink}, dayTabText: {...type.caption, color: colors.inkMuted, fontWeight: '700'}, dayTabTextActive: {color: colors.paper},
  tools: {flexDirection: 'row', gap: 10, paddingHorizontal: spacing.md, marginBottom: 8}, tool: {flex: 1, height: 48, borderRadius: radii.md, backgroundColor: colors.paper, borderWidth: 1, borderColor: colors.line, flexDirection: 'row', alignItems: 'center', justifyContent: 'center', gap: 7}, toolText: {...type.caption, color: colors.ink, fontWeight: '700'}, message: {...type.caption, color: colors.green, textAlign: 'center', paddingBottom: 6}, list: {paddingHorizontal: spacing.md, paddingBottom: 120},
  stopCard: {...softShadow, backgroundColor: colors.paper, borderRadius: radii.lg, padding: 12, marginBottom: 12, flexDirection: 'row', gap: 10}, stopActive: {opacity: 0.92, transform: [{scale: 1.02}]}, drag: {width: 24, alignItems: 'center', justifyContent: 'center'}, image: {width: 66, height: 66, borderRadius: 18}, stopContent: {flex: 1}, stopIndex: {...type.body, color: colors.ink, fontWeight: '700'}, timeRow: {flexDirection: 'row', alignItems: 'center', gap: 6, marginTop: 8}, timeInput: {...type.caption, color: colors.ink, fontWeight: '700', borderWidth: 1, borderColor: colors.line, backgroundColor: colors.canvas, borderRadius: 10, paddingHorizontal: 8, paddingVertical: 6, width: 58, textAlign: 'center'}, dash: {color: colors.inkFaint}, note: {...type.caption, color: colors.inkMuted, marginTop: 8}, stopActions: {flexDirection: 'row', gap: 18, marginTop: 10}, link: {flexDirection: 'row', alignItems: 'center', gap: 4}, linkText: {...type.caption, color: colors.blueDeep, fontWeight: '700'}, deleteText: {...type.caption, color: colors.danger, fontWeight: '700'},
  footer: {position: 'absolute', left: 0, right: 0, bottom: 0, paddingHorizontal: spacing.md, paddingTop: 10, backgroundColor: colors.canvas, flexDirection: 'row', gap: 10}, cancel: {height: 54, paddingHorizontal: 22, alignItems: 'center', justifyContent: 'center', borderRadius: radii.pill, backgroundColor: colors.paper}, cancelText: {...type.body, color: colors.ink, fontWeight: '700'},
  scrim: {position: 'absolute', inset: 0, backgroundColor: 'rgba(17,19,24,0.36)'}, sheet: {position: 'absolute', left: 0, right: 0, bottom: 0, backgroundColor: colors.paper, borderTopLeftRadius: 32, borderTopRightRadius: 32, padding: spacing.lg}, handle: {width: 42, height: 5, borderRadius: 3, backgroundColor: colors.line, alignSelf: 'center', marginBottom: 16}, sheetHead: {flexDirection: 'row', justifyContent: 'space-between', alignItems: 'center'}, sheetTitle: {...type.title, fontSize: 22, color: colors.ink}, sheetSubtitle: {...type.caption, color: colors.inkMuted}, candidate: {minHeight: 94, borderTopWidth: 1, borderTopColor: colors.line, flexDirection: 'row', alignItems: 'center', gap: 12}, candidateImage: {width: 62, height: 62, borderRadius: 18}, candidateCopy: {flex: 1}, candidateName: {...type.body, color: colors.ink, fontWeight: '700'}, candidateNote: {...type.caption, color: colors.inkMuted, marginTop: 3},
});
