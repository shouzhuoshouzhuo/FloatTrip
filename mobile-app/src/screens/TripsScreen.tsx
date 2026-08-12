import React, {useEffect} from 'react';
import {ActivityIndicator, FlatList, Image, Pressable, RefreshControl, StyleSheet, Text, View} from 'react-native';
import {useSafeAreaInsets} from 'react-native-safe-area-context';
import {useQuery} from '@tanstack/react-query';
import type {BottomTabScreenProps} from '@react-navigation/bottom-tabs';
import type {CompositeScreenProps} from '@react-navigation/native';
import type {NativeStackScreenProps} from '@react-navigation/native-stack';
import {api} from '../services/api';
import {useAppStore} from '../store/useAppStore';
import {Icon, IconButton, OfflineBanner, Tag} from '../components/ui';
import {colors, radii, softShadow, spacing, type} from '../theme';
import type {MainTabParamList, RootStackParamList} from '../navigation/types';
import type {TripPlan} from '../types';

type Props = CompositeScreenProps<BottomTabScreenProps<MainTabParamList, 'Trips'>, NativeStackScreenProps<RootStackParamList>>;

export function TripsScreen({navigation}: Props) {
  const insets = useSafeAreaInsets(); const {session, mode, trips, setTrips} = useAppStore();
  const query = useQuery({queryKey: ['trips', session?.userId], queryFn: () => api.listTrips(session!.token), enabled: mode === 'online' && Boolean(session)});
  useEffect(() => {if (query.data) {setTrips(query.data);}}, [query.data, setTrips]);
  const renderTrip = ({item}: {item: TripPlan}) => (
    <Pressable onPress={() => navigation.navigate('TripMap', {tripId: item.id})} style={styles.card}>
      <Image source={item.cover} style={styles.image} />
      <View style={styles.cardBody}><View style={styles.statusRow}><Tag active={item.status === 'planning'}>{item.status === 'planning' ? '正在规划' : '已完成'}</Tag><Icon name="arrow-top-right" color={colors.inkMuted} size={20} /></View>
        <Text style={styles.cardTitle}>{item.title}</Text><Text style={styles.meta}>{item.dateRange}</Text>
        <View style={styles.metrics}><Text style={styles.metric}>{item.daysCount} 天</Text><View style={styles.dot} /><Text style={styles.metric}>{item.placesCount} 个地点</Text></View>
        <View style={styles.tags}>{item.tags.slice(0, 3).map(tag => <Text key={tag} style={styles.smallTag}>{tag}</Text>)}</View>
      </View>
    </Pressable>
  );
  return (
    <View style={styles.root}>
      <View style={[styles.header, {paddingTop: insets.top + 14}]}><View><Text style={styles.eyebrow}>我的旅程</Text><Text style={styles.title}>行程</Text></View><IconButton name="plus" label="新建行程" onPress={() => navigation.navigate('Conversation')} /></View>
      {mode === 'demo' && <OfflineBanner />}
      {query.isLoading && !trips.length ? <ActivityIndicator color={colors.blue} /> : <FlatList data={trips} keyExtractor={item => item.id} renderItem={renderTrip} contentContainerStyle={styles.list}
        refreshControl={<RefreshControl refreshing={query.isRefetching} onRefresh={query.refetch} enabled={mode === 'online'} tintColor={colors.blue} />} ListEmptyComponent={<Text style={styles.empty}>还没有行程，从规划页说出你的想法吧。</Text>} />}
    </View>
  );
}

const styles = StyleSheet.create({
  root: {flex: 1, backgroundColor: colors.canvas}, header: {paddingHorizontal: spacing.lg, paddingBottom: spacing.lg, flexDirection: 'row', justifyContent: 'space-between', alignItems: 'center'},
  eyebrow: {...type.caption, color: colors.blueDeep, fontWeight: '700'}, title: {...type.hero, color: colors.ink}, list: {paddingHorizontal: spacing.md, paddingBottom: 124, gap: 16},
  card: {...softShadow, backgroundColor: colors.paper, borderRadius: radii.xl, overflow: 'hidden'}, image: {width: '100%', height: 162}, cardBody: {padding: spacing.lg},
  statusRow: {flexDirection: 'row', alignItems: 'center', justifyContent: 'space-between'}, cardTitle: {...type.section, color: colors.ink, marginTop: 12}, meta: {...type.caption, color: colors.inkMuted, marginTop: 4},
  metrics: {flexDirection: 'row', alignItems: 'center', gap: 8, marginTop: 12}, metric: {...type.caption, color: colors.inkMuted, fontWeight: '700'}, dot: {width: 3, height: 3, borderRadius: 2, backgroundColor: colors.inkFaint},
  tags: {flexDirection: 'row', gap: 8, marginTop: 14}, smallTag: {...type.caption, color: colors.inkMuted, backgroundColor: colors.canvas, borderRadius: radii.pill, paddingHorizontal: 10, paddingVertical: 6}, empty: {...type.body, color: colors.inkMuted, textAlign: 'center', paddingTop: 80},
});
