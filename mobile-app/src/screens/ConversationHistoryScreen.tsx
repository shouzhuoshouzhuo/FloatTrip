import React, {useCallback} from 'react';
import {ActivityIndicator, Pressable, RefreshControl, ScrollView, StyleSheet, Text, View} from 'react-native';
import {useFocusEffect} from '@react-navigation/native';
import {useQuery} from '@tanstack/react-query';
import {useSafeAreaInsets} from 'react-native-safe-area-context';
import type {NativeStackScreenProps} from '@react-navigation/native-stack';
import {Icon, PrimaryButton, ScreenHeader} from '../components/ui';
import type {RootStackParamList} from '../navigation/types';
import {api} from '../services/api';
import {useAppStore} from '../store/useAppStore';
import type {ConversationSummary} from '../types';
import {colors, radii, spacing, type} from '../theme';

type Props = NativeStackScreenProps<RootStackParamList, 'ConversationHistory'>;

const demoHistory: ConversationSummary[] = [
  {id: 'demo-nanjing', title: '南京3日游', status: 'active', createdAt: '2026-08-12', updatedAt: '2026-08-12', hasActivePlanning: false, hasWaitingUser: false, hasReadyBrief: false, hasUnreadCompleted: false},
  {id: 'demo-yunnan', title: '滇西北一周深度漫游', status: 'active', createdAt: '2026-08-11', updatedAt: '2026-08-11', hasActivePlanning: true, hasWaitingUser: false, hasReadyBrief: false, hasUnreadCompleted: false},
];

function statusFor(item: ConversationSummary): {label: string; color: string; icon: React.ComponentProps<typeof Icon>['name']} {
  if (item.hasActivePlanning) {return {label: '后台规划中', color: colors.blueDeep, icon: 'creation'};}
  if (item.hasWaitingUser) {return {label: '等待你的确认', color: colors.warning, icon: 'message-question-outline'};}
  if (item.hasReadyBrief) {return {label: '条件已齐全', color: colors.green, icon: 'check-circle-outline'};}
  if (item.hasUnreadCompleted) {return {label: '新行程已完成', color: colors.green, icon: 'bell-badge-outline'};}
  return {label: '可继续对话', color: colors.inkMuted, icon: 'message-text-outline'};
}

function formatDate(value: string): string {
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) {return value.slice(0, 10);}
  return new Intl.DateTimeFormat('zh-CN', {month: 'numeric', day: 'numeric'}).format(date);
}

export function ConversationHistoryScreen({navigation}: Props) {
  const insets = useSafeAreaInsets();
  const {mode, session} = useAppStore();
  const conversations = useQuery({
    queryKey: ['conversations', session?.userId],
    queryFn: () => session ? api.listConversations(session.token) : Promise.resolve(demoHistory),
    enabled: mode === 'demo' || Boolean(session),
    refetchInterval: mode === 'online' ? 4000 : false,
  });

  const refetch = conversations.refetch;
  useFocusEffect(useCallback(() => {refetch().catch(() => undefined);}, [refetch]));
  const rows = mode === 'demo' ? demoHistory : conversations.data ?? [];
  return (
    <View style={styles.root}>
      <View style={{paddingTop: insets.top}}><ScreenHeader title="历史对话" subtitle="规划会在后台继续" onBack={navigation.goBack} right={<Pressable accessibilityRole="button" accessibilityLabel="新建对话" onPress={() => navigation.navigate('Conversation')} style={styles.add}><Icon name="plus" /></Pressable>} /></View>
      <ScrollView refreshControl={<RefreshControl refreshing={conversations.isRefetching} onRefresh={() => void conversations.refetch()} tintColor={colors.blue} />} contentContainerStyle={styles.content}>
        <View style={styles.intro}><Icon name="cloud-sync-outline" color={colors.blueDeep} /><Text style={styles.introText}>离开规划页不会中断任务。你可以从这里随时回到原对话，查看进度或继续补充条件。</Text></View>
        {conversations.isLoading && mode === 'online' ? <ActivityIndicator color={colors.blue} style={styles.loading} /> : rows.map(item => {
          const status = statusFor(item);
          return <Pressable key={item.id} onPress={() => navigation.navigate('Conversation', {conversationId: item.id})} style={({pressed}) => [styles.row, pressed && styles.pressed]}>
            <View style={styles.rowTop}><View style={[styles.statusIcon, {backgroundColor: `${status.color}18`}]}><Icon name={status.icon} color={status.color} size={20} /></View><View style={styles.rowCopy}><Text numberOfLines={1} style={styles.title}>{item.title || '新的旅行对话'}</Text><View style={styles.statusLine}><Text style={[styles.status, {color: status.color}]}>{status.label}</Text><Text style={styles.date}>{formatDate(item.updatedAt)}</Text></View></View><Icon name="chevron-right" color={colors.inkFaint} /></View>
          </Pressable>;
        })}
        {!conversations.isLoading && rows.length === 0 && <View style={styles.empty}><Icon name="message-text-clock-outline" size={34} color={colors.inkFaint} /><Text style={styles.emptyTitle}>还没有历史对话</Text><Text style={styles.emptyText}>发出第一条旅行需求后，对话会自动保存在这里。</Text><PrimaryButton label="开始一次规划" onPress={() => navigation.navigate('Conversation')} style={styles.emptyButton} /></View>}
        {conversations.isError && <Text style={styles.error}>历史对话暂时没有同步成功，下拉可以重试。</Text>}
      </ScrollView>
    </View>
  );
}

const styles = StyleSheet.create({
  root: {flex: 1, backgroundColor: colors.canvas}, content: {padding: spacing.md, paddingBottom: 40, gap: 10},
  add: {width: 44, height: 44, borderRadius: 22, backgroundColor: colors.paper, alignItems: 'center', justifyContent: 'center'},
  intro: {backgroundColor: colors.cyanSoft, borderRadius: radii.md, padding: 14, flexDirection: 'row', alignItems: 'flex-start', gap: 10, marginBottom: 6}, introText: {...type.caption, color: colors.inkMuted, flex: 1},
  row: {backgroundColor: colors.paper, borderRadius: radii.lg, padding: 16, borderWidth: 1, borderColor: colors.line}, pressed: {opacity: 0.7}, rowTop: {flexDirection: 'row', alignItems: 'center', gap: 12},
  statusIcon: {width: 42, height: 42, borderRadius: 15, alignItems: 'center', justifyContent: 'center'}, rowCopy: {flex: 1}, title: {...type.body, color: colors.ink, fontWeight: '700'}, statusLine: {flexDirection: 'row', gap: 9, alignItems: 'center', marginTop: 4}, status: {...type.caption, fontWeight: '700'}, date: {...type.caption, color: colors.inkFaint},
  loading: {marginTop: 60}, empty: {alignItems: 'center', paddingTop: 72, paddingHorizontal: 26}, emptyTitle: {...type.section, color: colors.ink, marginTop: 14}, emptyText: {...type.caption, color: colors.inkMuted, textAlign: 'center', marginTop: 6}, emptyButton: {marginTop: 22, alignSelf: 'stretch'}, error: {...type.caption, color: colors.danger, textAlign: 'center', padding: 18},
});
