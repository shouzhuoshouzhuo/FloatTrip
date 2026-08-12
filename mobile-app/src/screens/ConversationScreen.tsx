import React, {useCallback, useEffect, useRef, useState} from 'react';
import {ActivityIndicator, KeyboardAvoidingView, Platform, Pressable, ScrollView, StyleSheet, Text, TextInput, View} from 'react-native';
import {useSafeAreaInsets} from 'react-native-safe-area-context';
import type {NativeStackScreenProps} from '@react-navigation/native-stack';
import {defaultBrief, demoTrips, thoughtSteps as initialThoughtSteps} from '../data/demo';
import {ApiError, api} from '../services/api';
import {adaptBrief, adaptMessage, adaptRun} from '../services/mappers';
import {RunStream} from '../services/runStream';
import {useAppStore} from '../store/useAppStore';
import type {ConversationMessage, PlanningBrief, Run, RunEvent, ThoughtStep} from '../types';
import type {RootStackParamList} from '../navigation/types';
import {Icon, IconButton, PrimaryButton, ScreenHeader, Tag} from '../components/ui';
import {colors, radii, softShadow, spacing, type} from '../theme';
import {applyPlanningProgress, canSubmitBrief, completeThoughtThrough, getMissingBriefLabels} from '../utils/planning';

type Props = NativeStackScreenProps<RootStackParamList, 'Conversation'>;

const record = (value: unknown): Record<string, unknown> => value && typeof value === 'object' && !Array.isArray(value) ? value as Record<string, unknown> : {};

function mergeMessages(current: ConversationMessage[], incoming: ConversationMessage[]): ConversationMessage[] {
  const rows = new Map(current.map(item => [item.id, item]));
  incoming.forEach(item => rows.set(item.id, item));
  return [...rows.values()].sort((a, b) => (a.sequence ?? Number.MAX_SAFE_INTEGER) - (b.sequence ?? Number.MAX_SAFE_INTEGER));
}

function demoBriefFromPrompt(content: string, current: PlanningBrief | null): PlanningBrief {
  const destination = current?.destination || (/南京/.test(content) ? '南京' : /青岛/.test(content) ? '青岛' : /川西/.test(content) ? '川西' : /杭州/.test(content) ? '杭州' : '目的地待确认');
  const days = current?.days || Number(content.match(/(\d+)\s*天|([一二三四五六七八九十]+)日游/)?.[1] ?? (/三日游/.test(content) ? 3 : 0));
  const fullDate = content.match(/(20\d{2})[-/.年](\d{1,2})[-/.月](\d{1,2}).*?(?:至|到|-).*?(?:(20\d{2})[-/.年])?(\d{1,2})[-/.月](\d{1,2})/);
  const quickDate = content.match(/(\d{1,2})月(\d{1,2})日.*?(?:至|到|-).*?(\d{1,2})月(\d{1,2})日/);
  const year = String(fullDate?.[1] ?? 2026); const pad = (value: string) => value.padStart(2, '0');
  const startDate = fullDate ? `${year}-${pad(fullDate[2])}-${pad(fullDate[3])}` : quickDate ? `2026-${pad(quickDate[1])}-${pad(quickDate[2])}` : current?.startDate ?? '';
  const endDate = fullDate ? `${fullDate[4] ?? year}-${pad(fullDate[5])}-${pad(fullDate[6])}` : quickDate ? `2026-${pad(quickDate[3])}-${pad(quickDate[4])}` : current?.endDate ?? '';
  const missingFields = [destination === '目的地待确认' && 'destination', !startDate && 'start_date', !endDate && 'end_date'].filter(Boolean) as string[];
  return {...defaultBrief, destination, days, startDate, endDate, status: missingFields.length ? 'collecting' : 'ready', missingFields};
}

export function ConversationScreen({navigation, route}: Props) {
  const insets = useSafeAreaInsets();
  const {mode, session, memories, setPlanningState, upsertTrip} = useAppStore();
  const [messages, setMessages] = useState<ConversationMessage[]>([]); const [input, setInput] = useState('');
  const [brief, setBrief] = useState<PlanningBrief | null>(null); const [conversationId, setConversationId] = useState(route.params?.conversationId ?? '');
  const [chatRun, setChatRun] = useState<Run | null>(null); const [planningRun, setPlanningRun] = useState<Run | null>(null);
  const [steps, setSteps] = useState<ThoughtStep[]>(initialThoughtSteps); const [expanded, setExpanded] = useState(false);
  const [seconds, setSeconds] = useState(0); const [completedTripId, setCompletedTripId] = useState('');
  const [sending, setSending] = useState(false); const [loading, setLoading] = useState(Boolean(route.params?.conversationId)); const [error, setError] = useState('');
  const streamRef = useRef<RunStream | null>(null); const initialized = useRef(false); const scrollRef = useRef<ScrollView>(null);
  const planning = planningRun?.status === 'queued' || planningRun?.status === 'running';
  const understanding = chatRun?.status === 'queued' || chatRun?.status === 'running';
  const completed = planningRun?.status === 'succeeded' || Boolean(completedTripId);

  const append = useCallback((role: ConversationMessage['role'], content: string) => setMessages(current => [...current, {id: `local-${Date.now()}-${current.length}`, role, content}]), []);
  const syncMessages = useCallback(async (id: string) => {
    if (!session) {return;}
    const rows = await api.getMessages(session.token, id);
    setMessages(rows);
  }, [session]);
  const syncBrief = useCallback(async (id: string) => {
    if (!session) {return null;}
    const value = await api.getBrief(session.token, id).catch(() => null);
    if (value) {
      const hydrated = {...value, memories: memories.filter(item => item.status === 'active').slice(0, 3).map(item => item.value)};
      setBrief(hydrated); setPlanningState(canSubmitBrief(hydrated) ? 'ready' : value.status === 'submitted' ? 'planning' : 'collecting');
      return hydrated;
    }
    return null;
  }, [memories, session, setPlanningState]);

  const finishPlanningRun = useCallback(async (runId: string) => {
    if (!session) {return;}
    const latest = await api.getRun(session.token, runId).catch(() => null); if (!latest) {return;}
    setPlanningRun(latest);
    if (latest.status === 'succeeded' && latest.resultItineraryId) {
      const trip = await api.getTrip(session.token, latest.resultItineraryId);
      upsertTrip(trip); setCompletedTripId(trip.id); setSteps(current => completeThoughtThrough(current, current.length - 1)); setPlanningState('completed'); setExpanded(false);
    } else if (latest.status === 'failed' || latest.status === 'cancelled') {setExpanded(false);}
  }, [session, setPlanningState, upsertTrip]);

  const connectPlanningRun = useCallback((target: Run) => {
    if (!session) {return;}
    streamRef.current?.stop(); setPlanningRun(target); setPlanningState('planning'); setExpanded(true);
    const stream = new RunStream(session.token, target.id, {onEvent: event => {
      const eventKind = String(event.payload.kind ?? ''); const stage = String(event.payload.stage ?? ''); const label = String(event.payload.label ?? '');
      if (event.kind === 'custom' && eventKind === 'planning_run.progress') {setSteps(current => applyPlanningProgress(current, stage, label));}
      if (event.kind === 'end') {void finishPlanningRun(target.id).catch(() => setError('规划已完成，行程同步暂时失败，请稍后重试。'));}
      if (event.kind === 'error') {setPlanningRun(current => current ? {...current, status: 'failed'} : current); setExpanded(false);}
    }, onDisconnected: () => setError('网络波动，规划仍在后台继续，轻舟会自动恢复连接。')});
    streamRef.current = stream; stream.start();
  }, [finishPlanningRun, session, setPlanningState]);

  const handleChatEvent = useCallback((id: string, event: RunEvent) => {
    const eventKind = String(event.payload.kind ?? '');
    if (event.kind === 'custom' && eventKind === 'chat.message.completed') {
      const message = adaptMessage({id: event.payload.message_id, role: 'assistant', content: event.payload.content, sequence: event.payload.sequence, created_at: event.payload.created_at});
      setMessages(current => mergeMessages(current.filter(item => !item.id.startsWith('local-assistant')), [message]));
    }
    if (event.kind === 'custom' && (eventKind === 'planning_brief.updated' || eventKind === 'planning_brief.ready' || eventKind === 'planning_brief.submitted')) {
      const next = adaptBrief({id: event.payload.brief_id, status: event.payload.status, data: event.payload.summary, missing_fields: event.payload.missing_fields, memory_context: event.payload.memory_context});
      setBrief({...next, memories: memories.filter(item => item.status === 'active').slice(0, 3).map(item => item.value)});
      setPlanningState(canSubmitBrief(next) ? 'ready' : next.status === 'submitted' ? 'planning' : 'collecting');
    }
    if (event.kind === 'custom' && eventKind === 'run.created') {
      const created = adaptRun(record(event.payload.run));
      if (created.kind === 'travel_plan' || created.kind === 'revision') {connectPlanningRun(created);}
    }
    if (event.kind === 'end') {
      setChatRun(current => current ? {...current, status: String(event.payload.status ?? 'succeeded') as Run['status']} : current);
      void Promise.all([syncMessages(id), syncBrief(id)]).catch(() => setError('对话结果同步较慢，请稍后重新打开。'));
      if (session) {
        void api.listRuns(session.token, id).then(runs => {
          const active = runs.find(item => (item.kind === 'travel_plan' || item.kind === 'revision') && (item.status === 'queued' || item.status === 'running'));
          const finished = runs.find(item => (item.kind === 'travel_plan' || item.kind === 'revision') && item.status === 'succeeded' && item.resultItineraryId);
          if (active) {connectPlanningRun(active);} else if (finished) {void finishPlanningRun(finished.id);}
        }).catch(() => undefined);
      }
    }
    if (event.kind === 'error') {setChatRun(current => current ? {...current, status: 'failed'} : current);}
  }, [connectPlanningRun, finishPlanningRun, memories, session, setPlanningState, syncBrief, syncMessages]);

  const connectChatRun = useCallback((id: string, target: Run) => {
    if (!session) {return;}
    streamRef.current?.stop(); setChatRun(target);
    const stream = new RunStream(session.token, target.id, {onEvent: event => handleChatEvent(id, event), onDisconnected: () => setError('网络波动，消息已保存，轻舟会自动继续处理。')});
    streamRef.current = stream; stream.start();
  }, [handleChatEvent, session]);

  const restoreConversation = useCallback(async (id: string) => {
    if (mode === 'demo') {
      const demoBrief = id === 'demo-nanjing' ? demoBriefFromPrompt('南京3日游', null) : defaultBrief;
      setBrief(demoBrief); setMessages([{id: 'demo-user', role: 'user', content: id === 'demo-nanjing' ? '南京3日游' : '想规划一周滇西北旅行', sequence: 1}, {id: 'demo-ai', role: 'assistant', content: id === 'demo-nanjing' ? '南京和3天已经记下了。还需要补充具体出发和结束日期。' : '这趟旅行正在后台规划，你可以继续补充要求。', sequence: 2}]);
      if (id === 'demo-yunnan') {setPlanningRun({id: 'demo-run', kind: 'travel_plan', status: 'running', conversationId: id}); setExpanded(true);}
      setLoading(false); return;
    }
    if (!session) {setLoading(false); return;}
    setLoading(true); setError('');
    try {
      const [, rows, latestBrief, runs] = await Promise.all([api.markConversationViewed(session.token, id), api.getMessages(session.token, id), api.getBrief(session.token, id), api.listRuns(session.token, id)]);
      setMessages(rows); if (latestBrief) {setBrief(latestBrief); setPlanningState(canSubmitBrief(latestBrief) ? 'ready' : latestBrief.status === 'submitted' ? 'planning' : 'collecting');}
      const activePlanning = runs.find(item => (item.kind === 'travel_plan' || item.kind === 'revision') && (item.status === 'queued' || item.status === 'running'));
      const activeChat = runs.find(item => item.kind === 'chat' && (item.status === 'queued' || item.status === 'running'));
      const completedPlanning = runs.find(item => (item.kind === 'travel_plan' || item.kind === 'revision') && item.status === 'succeeded' && item.resultItineraryId);
      if (activePlanning) {connectPlanningRun(activePlanning);} else if (activeChat) {connectChatRun(id, activeChat);} else if (completedPlanning) {await finishPlanningRun(completedPlanning.id);}
    } catch {setError('这段历史对话暂时没有加载成功，请返回后重试。');}
    finally {setLoading(false);}
  }, [connectChatRun, connectPlanningRun, finishPlanningRun, mode, session, setPlanningState]);

  const sendOnline = useCallback(async (content: string) => {
    if (!session) {return;}
    setSending(true); setError('');
    try {
      let id = conversationId;
      if (!id) {const created = await api.createConversation(session.token); id = String(created.id); setConversationId(id);}
      const result = await api.sendMessage(session.token, id, content);
      setMessages(current => mergeMessages(current.filter(item => !(item.id.startsWith('local-') && item.role === 'user' && item.content === content)), [result.message]));
      connectChatRun(id, result.run);
    } catch (reason) {setError(reason instanceof ApiError && reason.status === 422 ? '这条消息需要再具体一点，请补充后重试。' : '消息暂时没有送达，内容已为你保留。');}
    finally {setSending(false);}
  }, [connectChatRun, conversationId, session]);

  const send = useCallback((value: string) => {
    const content = value.trim(); if (!content || sending) {return;}
    append('user', content); setInput(''); setPlanningState('collecting');
    if (mode === 'demo') {
      setSending(true);
      setTimeout(() => {
        const next = demoBriefFromPrompt(content, brief); setBrief(next); setPlanningState(canSubmitBrief(next) ? 'ready' : 'collecting');
        append('assistant', canSubmitBrief(next) ? '必要条件已经齐全。请确认摘要，确认后再开始正式规划。' : `已记下目的地和天数。还需要补充：${getMissingBriefLabels(next).join('、')}。`);
        setSending(false);
      }, 450);
    } else {void sendOnline(content);}
  }, [append, brief, mode, sendOnline, sending, setPlanningState]);

  useEffect(() => {
    if (initialized.current) {return;} initialized.current = true;
    const existingId = route.params?.conversationId; const prompt = route.params?.prompt;
    if (existingId) {void restoreConversation(existingId);} else if (prompt) {send(prompt);} else {append('assistant', '你好，我是轻舟。告诉我想去哪里、什么时候出发，以及你希望旅途是什么节奏。');}
  }, [append, restoreConversation, route.params?.conversationId, route.params?.prompt, send]);
  useEffect(() => {setTimeout(() => scrollRef.current?.scrollToEnd({animated: true}), 80);}, [messages, brief, steps, expanded, completed]);
  useEffect(() => {
    if (!planning) {return;}
    const started = Date.now(); const timer = setInterval(() => setSeconds(Math.round((Date.now() - started) / 1000)), 1000);
    return () => clearInterval(timer);
  }, [planning]);
  useEffect(() => () => streamRef.current?.stop(), []);

  const startPlanning = async () => {
    if (!canSubmitBrief(brief)) {setError(`还需要补充：${brief ? getMissingBriefLabels(brief).join('、') : '完整旅行条件'}。`); setPlanningState('collecting'); return;}
    setError(''); setExpanded(true); setSeconds(0); setSteps(initialThoughtSteps);
    if (mode === 'demo') {
      setPlanningState('planning'); setPlanningRun({id: 'demo-run', kind: 'travel_plan', status: 'running', conversationId: conversationId || 'demo'});
      initialThoughtSteps.forEach((_, index) => setTimeout(() => setSteps(current => completeThoughtThrough(current, index)), 1200 + index * 1300));
      setTimeout(() => {setPlanningRun({id: 'demo-run', kind: 'travel_plan', status: 'succeeded', resultItineraryId: demoTrips[0].id}); upsertTrip({...demoTrips[0], status: 'completed'}); setCompletedTripId(demoTrips[0].id); setPlanningState('completed'); setExpanded(false); setSeconds(8);}, 8200);
      return;
    }
    if (!session || !brief?.id || !conversationId) {return;}
    try {
      const latest = await api.getBrief(session.token, conversationId);
      if (!canSubmitBrief(latest)) {if (latest) {setBrief(latest);} setPlanningState('collecting'); setExpanded(false); setError(`还需要补充：${latest ? getMissingBriefLabels(latest).join('、') : '完整旅行条件'}。`); return;}
      if (!latest?.id) {setError('规划摘要尚未同步完成，请稍后再试。'); return;}
      const result = await api.submitBrief(session.token, latest.id); setBrief(result.brief); connectPlanningRun(result.run);
    } catch (reason) {
      setError(reason instanceof ApiError && (reason.status === 409 || reason.status === 422) ? '还有必要条件没有确认，请补充后再开始规划。' : '规划启动失败，请检查网络后重试。');
      setPlanningState(reason instanceof ApiError && (reason.status === 409 || reason.status === 422) ? 'collecting' : 'ready'); setExpanded(false);
    }
  };

  const activeTrip = useAppStore.getState().trips.find(item => item.id === completedTripId) ?? demoTrips[0];
  return (
    <KeyboardAvoidingView style={styles.root} behavior={Platform.OS === 'ios' ? 'padding' : undefined} keyboardVerticalOffset={0}>
      <View style={{paddingTop: insets.top}}><ScreenHeader title={brief?.destination || '新的旅行规划'} subtitle={planning ? '规划在后台持续进行' : '与轻舟对话'} onBack={navigation.goBack} right={<IconButton name="message-text-clock-outline" label="历史对话" onPress={() => navigation.navigate('ConversationHistory')} />} /></View>
      {loading ? <View style={styles.loading}><ActivityIndicator color={colors.blue} /><Text style={styles.loadingText}>正在恢复对话…</Text></View> : <ScrollView ref={scrollRef} keyboardShouldPersistTaps="handled" contentContainerStyle={styles.messages}>
        {messages.map(message => <View key={message.id} style={[styles.messageRow, message.role === 'user' && styles.messageRowUser]}>{message.role !== 'user' && <View style={styles.aiAvatar}><Icon name="sail-boat" size={17} color={colors.paper} /></View>}<View style={[styles.bubble, message.role === 'user' ? styles.userBubble : styles.aiBubble]}><Text style={styles.messageText}>{message.content}</Text></View></View>)}
        {understanding && <View style={styles.understanding}><ActivityIndicator size="small" color={colors.blueDeep} /><Text style={styles.understandingText}>轻舟正在理解需求并检查必要条件…</Text></View>}
        {brief && !planning && !completed && <BriefCard brief={brief} memoryCount={memories.filter(item => item.status === 'active').length} onChange={setBrief} onStart={() => void startPlanning()} />}
        {(planning || completed) && <View style={styles.thoughtBlock}><Pressable testID="thought-status" onPress={() => setExpanded(value => !value)} style={styles.thoughtHeader}><View style={styles.thoughtTitleRow}>{planning && <View style={styles.pulse} />}<Text style={styles.thoughtTitle}>{planning ? `正在深度思考… ${seconds}s` : `深度思考完成 · ${seconds || 8}s`}</Text></View><Icon name={expanded ? 'chevron-up' : 'chevron-down'} color={colors.inkMuted} /></Pressable>{expanded && <View style={styles.timeline}>{steps.map((step, index) => <View key={step.id} style={styles.step}><View style={[styles.stepDot, step.completed && styles.stepDotDone, step.active && styles.stepDotActive]}>{step.completed && <Icon name="check" size={12} color={colors.paper} />}</View><View style={styles.stepCopy}><Text style={[styles.stepTitle, (step.completed || step.active) && styles.stepTitleDone]}>{step.title}</Text><Text style={styles.stepDetail}>{step.detail}</Text></View>{index < steps.length - 1 && <View style={styles.stepLine} />}</View>)}</View>}</View>}
        {completed && <View style={styles.result}><Text style={styles.resultTitle}>行程已经为你整理好了</Text><Text style={styles.resultLead}>我把转场、体力强度和你的旅行画像都放进了这份可编辑计划。</Text><Pressable onPress={() => navigation.navigate('TripMap', {tripId: activeTrip.id})} style={styles.preview}><View><Tag active>7天6晚</Tag><Text style={styles.previewTitle}>{activeTrip.title}</Text><Text style={styles.previewMeta}>{activeTrip.placesCount} 个地点 · {activeTrip.tags.join(' · ')}</Text></View><Icon name="arrow-top-right" size={24} /></Pressable><View style={styles.resultActions}><PrimaryButton testID="open-complete-trip" label="查看完整行程" style={{flex: 1}} onPress={() => navigation.navigate('TripMap', {tripId: activeTrip.id})} /><Pressable onPress={() => setInput('我想调整一下：')} style={styles.adjust}><Text style={styles.adjustText}>继续调整</Text></Pressable></View></View>}
        {error ? <Text style={styles.error}>{error}</Text> : null}
      </ScrollView>}
      <View style={[styles.inputDock, {paddingBottom: Math.max(insets.bottom, 10)}]}><View style={styles.inputPill}><Icon name="plus" /><TextInput value={input} onChangeText={setInput} onSubmitEditing={() => send(input)} placeholder={brief && !canSubmitBrief(brief) ? `请补充${getMissingBriefLabels(brief).join('、')}` : '发消息或继续调整行程'} placeholderTextColor={colors.inkFaint} style={styles.input} /><Pressable onPress={() => send(input)} style={[styles.send, (!input.trim() || sending) && styles.sendDisabled]}><Icon name="arrow-up" color={colors.paper} size={20} /></Pressable></View></View>
    </KeyboardAvoidingView>
  );
}

function BriefCard({brief, memoryCount, onChange, onStart}: {brief: PlanningBrief; memoryCount: number; onChange: (brief: PlanningBrief) => void; onStart: () => void}) {
  const ready = canSubmitBrief(brief); const missing = getMissingBriefLabels(brief);
  return <View style={styles.brief}><View style={styles.briefHead}><View><Text style={styles.briefEyebrow}>{ready ? '规划确认' : '继续补充'}</Text><Text style={styles.briefTitle}>{ready ? '必要条件已齐全' : '还不能开始正式规划'}</Text></View><Icon name={ready ? 'check-decagram' : 'alert-circle-outline'} color={ready ? colors.blue : colors.warning} /></View>
    {!ready && <View style={styles.missing}><Icon name="lock-clock" size={18} color={colors.warning} /><Text style={styles.missingText}>缺少 {missing.join('、')}。请在下方继续告诉轻舟，补齐后才会出现“开始规划”。</Text></View>}
    <View style={styles.briefGrid}><BriefItem icon="map-marker-outline" label="目的地" value={brief.destination} /><BriefItem icon="calendar-range" label="日期" value={brief.startDate && brief.endDate ? `${brief.startDate.slice(5)} — ${brief.endDate.slice(5)}` : ''} /><BriefItem icon="walk" label="节奏" value={brief.pace} /><BriefItem icon="account-group-outline" label="同行" value={brief.companions} /></View>
    <View style={styles.memoryLine}><Icon name="brain" size={18} color={colors.lavender} /><Text style={styles.memoryText}>本次参考 {memoryCount} 条旅行画像</Text></View>
    <View style={styles.briefTags}><Pressable onPress={() => onChange({...brief, pace: brief.pace.includes('轻松') ? '充实高效' : '轻松悠闲'})}><Tag active>{brief.pace}</Tag></Pressable>{brief.interests.slice(0, 2).map(item => <Tag key={item}>{item}</Tag>)}</View>
    {ready && <PrimaryButton testID="start-planning" label="开始规划" icon="creation" onPress={onStart} style={{marginTop: 18}} />}
  </View>;
}

function BriefItem({icon, label, value}: {icon: React.ComponentProps<typeof Icon>['name']; label: string; value: string}) {return <View style={styles.briefItem}><Icon name={icon} size={18} color={colors.inkMuted} /><View><Text style={styles.briefLabel}>{label}</Text><Text numberOfLines={1} style={styles.briefValue}>{value || '待确认'}</Text></View></View>;}

const styles = StyleSheet.create({
  root: {flex: 1, backgroundColor: colors.canvas}, loading: {flex: 1, alignItems: 'center', justifyContent: 'center', gap: 10}, loadingText: {...type.caption, color: colors.inkMuted}, messages: {padding: spacing.md, paddingBottom: 30, gap: 16}, messageRow: {flexDirection: 'row', alignItems: 'flex-end', gap: 8, maxWidth: '92%'}, messageRowUser: {alignSelf: 'flex-end', justifyContent: 'flex-end'},
  aiAvatar: {width: 30, height: 30, borderRadius: 11, backgroundColor: colors.blue, alignItems: 'center', justifyContent: 'center'}, bubble: {paddingHorizontal: 16, paddingVertical: 12, borderRadius: 20}, aiBubble: {backgroundColor: colors.paper, borderBottomLeftRadius: 6}, userBubble: {backgroundColor: colors.cyanBubble, borderBottomRightRadius: 6}, messageText: {...type.body, color: colors.ink},
  understanding: {marginLeft: 38, flexDirection: 'row', alignItems: 'center', gap: 9, paddingHorizontal: 14, minHeight: 44}, understandingText: {...type.caption, color: colors.inkMuted},
  brief: {...softShadow, backgroundColor: colors.paper, borderRadius: radii.xl, padding: spacing.lg}, briefHead: {flexDirection: 'row', justifyContent: 'space-between', alignItems: 'flex-start'}, briefEyebrow: {...type.caption, color: colors.blueDeep, fontWeight: '700'}, briefTitle: {...type.section, color: colors.ink, marginTop: 4}, missing: {backgroundColor: '#FFF5EA', borderRadius: radii.md, padding: 12, marginTop: 14, flexDirection: 'row', alignItems: 'flex-start', gap: 8}, missingText: {...type.caption, color: '#98602D', flex: 1},
  briefGrid: {flexDirection: 'row', flexWrap: 'wrap', marginTop: 18, gap: 10}, briefItem: {width: '48%', minHeight: 64, borderRadius: radii.md, backgroundColor: colors.canvas, padding: 12, flexDirection: 'row', gap: 8, alignItems: 'center'}, briefLabel: {...type.caption, fontSize: 11, color: colors.inkFaint}, briefValue: {...type.caption, color: colors.ink, fontWeight: '700', maxWidth: 100},
  memoryLine: {flexDirection: 'row', alignItems: 'center', gap: 8, marginTop: 16}, memoryText: {...type.caption, color: colors.lavender, fontWeight: '700'}, briefTags: {flexDirection: 'row', flexWrap: 'wrap', gap: 8, marginTop: 12},
  thoughtBlock: {paddingVertical: 6}, thoughtHeader: {height: 46, flexDirection: 'row', alignItems: 'center', justifyContent: 'space-between'}, thoughtTitleRow: {flexDirection: 'row', alignItems: 'center', gap: 10}, thoughtTitle: {...type.section, fontSize: 17, color: colors.ink}, pulse: {width: 9, height: 9, borderRadius: 5, backgroundColor: colors.blue},
  timeline: {paddingLeft: 4, paddingTop: 4}, step: {flexDirection: 'row', gap: 12, minHeight: 66, position: 'relative'}, stepDot: {width: 22, height: 22, borderRadius: 11, borderWidth: 2, borderColor: colors.line, backgroundColor: colors.paper, alignItems: 'center', justifyContent: 'center', zIndex: 2}, stepDotDone: {backgroundColor: colors.blue, borderColor: colors.blue}, stepDotActive: {borderColor: colors.blue, borderWidth: 6}, stepLine: {position: 'absolute', width: 2, backgroundColor: colors.line, left: 10, top: 22, bottom: 0}, stepCopy: {flex: 1}, stepTitle: {...type.body, color: colors.inkMuted, fontWeight: '700'}, stepTitleDone: {color: colors.ink}, stepDetail: {...type.caption, color: colors.inkFaint, marginTop: 2},
  result: {backgroundColor: colors.paper, borderRadius: radii.xl, padding: spacing.lg}, resultTitle: {...type.section, color: colors.ink}, resultLead: {...type.body, color: colors.inkMuted, marginTop: 6}, preview: {backgroundColor: colors.limeSoft, borderRadius: radii.lg, padding: 18, marginTop: 16, flexDirection: 'row', justifyContent: 'space-between', alignItems: 'center'}, previewTitle: {...type.section, color: colors.ink, marginTop: 12}, previewMeta: {...type.caption, color: colors.inkMuted, marginTop: 4}, resultActions: {flexDirection: 'row', alignItems: 'center', gap: 12, marginTop: 16}, adjust: {height: 54, paddingHorizontal: 12, justifyContent: 'center'}, adjustText: {...type.body, fontWeight: '700', color: colors.ink},
  error: {...type.caption, color: colors.danger, textAlign: 'center'}, inputDock: {backgroundColor: colors.canvas, paddingHorizontal: spacing.md, paddingTop: 8}, inputPill: {...softShadow, minHeight: 58, borderRadius: radii.pill, backgroundColor: colors.paper, flexDirection: 'row', alignItems: 'center', paddingHorizontal: 16, gap: 10}, input: {...type.body, flex: 1, color: colors.ink}, send: {width: 38, height: 38, borderRadius: 19, backgroundColor: colors.ink, alignItems: 'center', justifyContent: 'center'}, sendDisabled: {opacity: 0.3},
});
