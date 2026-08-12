import React, {useEffect, useMemo, useState} from 'react';
import {Image, Modal, Pressable, ScrollView, StyleSheet, Text, TextInput, View} from 'react-native';
import {useSafeAreaInsets} from 'react-native-safe-area-context';
import {useQuery} from '@tanstack/react-query';
import {api} from '../services/api';
import {useAppStore} from '../store/useAppStore';
import type {MemoryCategory, MemoryPolarity, ProfileMemory} from '../types';
import {Icon, IconButton, OfflineBanner, PrimaryButton, Tag} from '../components/ui';
import {colors, radii, softShadow, spacing, type} from '../theme';

const groups: Array<{label: string; polarity: MemoryPolarity; icon: React.ComponentProps<typeof Icon>['name']; color: string}> = [
  {label: '偏好', polarity: 'prefer', icon: 'heart-outline', color: colors.blue},
  {label: '避雷', polarity: 'avoid', icon: 'shield-alert-outline', color: colors.danger},
  {label: '必须满足', polarity: 'require', icon: 'check-decagram-outline', color: colors.green},
  {label: '背景信息', polarity: 'fact', icon: 'account-details-outline', color: colors.lavender},
];
const categoryFor = (polarity: MemoryPolarity): MemoryCategory => polarity === 'prefer' ? 'attraction_preference' : polarity === 'avoid' ? 'other_travel_preference' : polarity === 'require' ? 'schedule_preference' : 'companion_context';

export function ProfileScreen() {
  const insets = useSafeAreaInsets(); const {mode, session, trips, memories, setMemories, logout} = useAppStore();
  const [editing, setEditing] = useState<ProfileMemory | null>(null); const [sheetOpen, setSheetOpen] = useState(false);
  const [value, setValue] = useState(''); const [polarity, setPolarity] = useState<MemoryPolarity>('prefer'); const [busy, setBusy] = useState(false);
  const query = useQuery({queryKey: ['profile', session?.userId], queryFn: () => api.getProfile(session!.token), enabled: mode === 'online' && Boolean(session)});
  useEffect(() => {if (query.data) {setMemories(query.data.memories);}}, [query.data, setMemories]);
  const stats = useMemo(() => ({trips: trips.length, cities: new Set(trips.map(item => item.destination)).size, memories: memories.filter(item => item.status === 'active').length}), [memories, trips]);
  const open = (memory?: ProfileMemory, preset: MemoryPolarity = 'prefer') => {setEditing(memory ?? null); setValue(memory?.value ?? ''); setPolarity(memory?.polarity ?? preset); setSheetOpen(true);};
  const save = async () => {
    if (!value.trim()) {return;} setBusy(true);
    try {
      if (mode === 'demo' || !session) {
        const next: ProfileMemory = editing ? {...editing, value: value.trim(), polarity, category: categoryFor(polarity)} : {id: `local-${Date.now()}`, value: value.trim(), polarity, category: categoryFor(polarity), status: 'active', scopeType: 'global'};
        setMemories([next, ...memories.filter(item => item.id !== next.id)]);
      } else {
        const next = editing ? await api.updateMemory(session.token, editing.id, {value: value.trim(), polarity, category: categoryFor(polarity)}) : await api.createMemory(session.token, {value: value.trim(), polarity, category: categoryFor(polarity)});
        setMemories([next, ...memories.filter(item => item.id !== next.id)]);
      }
      setSheetOpen(false);
    } finally {setBusy(false);}
  };
  const remove = async (memory: ProfileMemory) => {if (mode === 'online' && session) {await api.deleteMemory(session.token, memory.id).catch(() => null);} setMemories(memories.filter(item => item.id !== memory.id));};
  const approve = async (memory: ProfileMemory) => {
    const next = mode === 'online' && session ? await api.approveMemory(session.token, memory.id).catch(() => ({...memory, status: 'active' as const})) : {...memory, status: 'active' as const};
    setMemories(memories.map(item => item.id === memory.id ? next : item));
  };
  const candidates = memories.filter(item => item.status === 'candidate');
  return (
    <View style={styles.root}>
      <ScrollView contentContainerStyle={[styles.content, {paddingTop: insets.top + 16}]}>
        <View style={styles.top}><View><Text style={styles.eyebrow}>旅行画像</Text><Text style={styles.title}>我的</Text></View><IconButton name="cog-outline" label="设置" onPress={() => void logout()} /></View>
        {mode === 'demo' && <OfflineBanner />}
        <View style={styles.profileCard}>
          <Image source={require('../assets/images/avatar.png')} style={styles.avatar} /><View style={styles.identity}><Text style={styles.name}>{session?.username || '轻舟旅人'}</Text><Text style={styles.bio}>让每次出发，都更像你。</Text></View>
          <View style={styles.stats}><Stat value={stats.trips} label="旅程" /><Stat value={stats.cities} label="城市" /><Stat value={stats.memories} label="记忆" /></View>
        </View>
        {candidates.length > 0 && <View style={styles.candidateBox}><View style={styles.candidateHead}><View><Text style={styles.candidateEyebrow}>待你确认</Text><Text style={styles.candidateTitle}>轻舟推断了新的偏好</Text></View><Icon name="brain" color={colors.lavender} /></View>
          {candidates.map(item => <View key={item.id} style={styles.candidateItem}><Text style={styles.memoryText}>{item.value}</Text><View style={styles.candidateActions}><Pressable onPress={() => void remove(item)} style={styles.smallAction}><Icon name="close" size={18} color={colors.inkMuted} /><Text style={styles.reject}>不是这样</Text></Pressable><Pressable onPress={() => void approve(item)} style={[styles.smallAction, styles.approve]}><Icon name="check" size={18} color={colors.paper} /><Text style={styles.approveText}>确认</Text></Pressable></View></View>)}
        </View>}
        <View style={styles.sectionHead}><View><Text style={styles.sectionTitle}>轻舟记得这些</Text><Text style={styles.sectionSubtitle}>规划时会自动参考，你可以随时修改。</Text></View><IconButton name="plus" label="新增记忆" onPress={() => open()} /></View>
        {groups.map(group => {
          const items = memories.filter(item => item.status === 'active' && item.polarity === group.polarity);
          return <View key={group.polarity} style={styles.group}><View style={styles.groupHead}><View style={[styles.groupIcon, {backgroundColor: `${group.color}18`}]}><Icon name={group.icon} size={19} color={group.color} /></View><Text style={styles.groupTitle}>{group.label}</Text><Text style={styles.groupCount}>{items.length}</Text></View>
            {items.map(item => <Pressable key={item.id} onPress={() => open(item)} style={styles.memoryRow}><Text style={styles.memoryText}>{item.value}</Text><Icon name="pencil-outline" size={18} color={colors.inkFaint} /></Pressable>)}
            {!items.length && <Pressable onPress={() => open(undefined, group.polarity)} style={styles.emptyRow}><Text style={styles.emptyText}>添加一条{group.label}记忆</Text><Icon name="plus" size={18} color={colors.inkFaint} /></Pressable>}
          </View>;
        })}
        <Pressable onPress={() => void logout()} style={styles.logout}><Icon name="logout" color={colors.danger} /><Text style={styles.logoutText}>{session ? '退出登录' : '退出演示'}</Text></Pressable>
      </ScrollView>
      <Modal visible={sheetOpen} transparent animationType="slide" onRequestClose={() => setSheetOpen(false)}>
        <Pressable style={styles.scrim} onPress={() => setSheetOpen(false)} />
        <View style={[styles.sheet, {paddingBottom: Math.max(insets.bottom, 18)}]}><View style={styles.sheetHandle} /><View style={styles.sheetHead}><Text style={styles.sheetTitle}>{editing ? '编辑旅行记忆' : '新增旅行记忆'}</Text><IconButton name="close" label="关闭" onPress={() => setSheetOpen(false)} /></View>
          <TextInput value={value} onChangeText={setValue} multiline autoFocus placeholder="例如：不喜欢一天换很多家酒店" placeholderTextColor={colors.inkFaint} style={styles.sheetInput} />
          <Text style={styles.fieldLabel}>归类为</Text><View style={styles.polarities}>{groups.map(group => <Pressable key={group.polarity} onPress={() => setPolarity(group.polarity)}><Tag active={polarity === group.polarity}>{group.label}</Tag></Pressable>)}</View>
          <View style={styles.sheetActions}>{editing && <Pressable onPress={() => {void remove(editing); setSheetOpen(false);}} style={styles.delete}><Icon name="trash-can-outline" color={colors.danger} /><Text style={styles.deleteText}>删除</Text></Pressable>}<PrimaryButton label="保存记忆" loading={busy} onPress={() => void save()} style={{flex: 1}} /></View>
        </View>
      </Modal>
    </View>
  );
}

function Stat({value, label}: {value: number; label: string}) {return <View style={styles.stat}><Text style={styles.statValue}>{value}</Text><Text style={styles.statLabel}>{label}</Text></View>;}

const styles = StyleSheet.create({
  root: {flex: 1, backgroundColor: colors.canvas}, content: {paddingBottom: 126}, top: {paddingHorizontal: spacing.lg, paddingBottom: 18, flexDirection: 'row', alignItems: 'center', justifyContent: 'space-between'}, eyebrow: {...type.caption, color: colors.blueDeep, fontWeight: '700'}, title: {...type.hero, color: colors.ink},
  profileCard: {...softShadow, marginHorizontal: spacing.md, backgroundColor: colors.paper, borderRadius: radii.xl, padding: spacing.lg, flexDirection: 'row', alignItems: 'center', flexWrap: 'wrap'}, avatar: {width: 68, height: 68, borderRadius: 23}, identity: {marginLeft: 14, flex: 1}, name: {...type.section, color: colors.ink}, bio: {...type.caption, color: colors.inkMuted, marginTop: 2}, stats: {width: '100%', flexDirection: 'row', marginTop: 20, paddingTop: 16, borderTopWidth: 1, borderTopColor: colors.line}, stat: {flex: 1, alignItems: 'center'}, statValue: {...type.section, color: colors.ink}, statLabel: {...type.caption, color: colors.inkFaint},
  candidateBox: {margin: spacing.md, backgroundColor: '#F3EEFF', borderRadius: radii.xl, padding: spacing.lg}, candidateHead: {flexDirection: 'row', justifyContent: 'space-between'}, candidateEyebrow: {...type.caption, color: colors.lavender, fontWeight: '700'}, candidateTitle: {...type.section, color: colors.ink, marginTop: 3}, candidateItem: {marginTop: 16, borderTopWidth: 1, borderTopColor: '#DED4F6', paddingTop: 14}, candidateActions: {flexDirection: 'row', justifyContent: 'flex-end', gap: 8, marginTop: 12}, smallAction: {height: 38, borderRadius: radii.pill, paddingHorizontal: 12, flexDirection: 'row', alignItems: 'center', gap: 5}, reject: {...type.caption, color: colors.inkMuted}, approve: {backgroundColor: colors.lavender}, approveText: {...type.caption, color: colors.paper, fontWeight: '700'},
  sectionHead: {paddingHorizontal: spacing.lg, marginTop: 24, marginBottom: 14, flexDirection: 'row', alignItems: 'center', justifyContent: 'space-between'}, sectionTitle: {...type.section, color: colors.ink}, sectionSubtitle: {...type.caption, color: colors.inkMuted, marginTop: 3},
  group: {marginHorizontal: spacing.md, marginBottom: 12, padding: spacing.md, borderRadius: radii.lg, backgroundColor: colors.paper}, groupHead: {flexDirection: 'row', alignItems: 'center', gap: 9, marginBottom: 8}, groupIcon: {width: 34, height: 34, borderRadius: 12, alignItems: 'center', justifyContent: 'center'}, groupTitle: {...type.body, color: colors.ink, fontWeight: '700'}, groupCount: {...type.caption, color: colors.inkFaint, marginLeft: 'auto'},
  memoryRow: {minHeight: 52, borderTopWidth: 1, borderTopColor: colors.line, flexDirection: 'row', alignItems: 'center', gap: 12}, memoryText: {...type.body, color: colors.ink, flex: 1}, emptyRow: {minHeight: 50, borderTopWidth: 1, borderTopColor: colors.line, flexDirection: 'row', alignItems: 'center', justifyContent: 'space-between'}, emptyText: {...type.caption, color: colors.inkFaint},
  logout: {marginHorizontal: spacing.lg, height: 52, flexDirection: 'row', alignItems: 'center', justifyContent: 'center', gap: 8}, logoutText: {...type.body, color: colors.danger, fontWeight: '700'},
  scrim: {position: 'absolute', inset: 0, backgroundColor: 'rgba(17,19,24,0.36)'}, sheet: {position: 'absolute', left: 0, right: 0, bottom: 0, backgroundColor: colors.paper, borderTopLeftRadius: 32, borderTopRightRadius: 32, padding: spacing.lg}, sheetHandle: {width: 42, height: 5, borderRadius: 3, backgroundColor: colors.line, alignSelf: 'center', marginBottom: 16}, sheetHead: {flexDirection: 'row', alignItems: 'center', justifyContent: 'space-between'}, sheetTitle: {...type.title, fontSize: 22, color: colors.ink},
  sheetInput: {...type.body, minHeight: 112, marginTop: 18, backgroundColor: colors.canvas, borderRadius: radii.lg, padding: 16, color: colors.ink, textAlignVertical: 'top'}, fieldLabel: {...type.caption, color: colors.inkMuted, fontWeight: '700', marginTop: 18, marginBottom: 10}, polarities: {flexDirection: 'row', flexWrap: 'wrap', gap: 8}, sheetActions: {flexDirection: 'row', gap: 10, marginTop: 22}, delete: {height: 54, borderRadius: radii.pill, paddingHorizontal: 16, flexDirection: 'row', alignItems: 'center', gap: 6, backgroundColor: '#FFF1F2'}, deleteText: {...type.body, color: colors.danger, fontWeight: '700'},
});
