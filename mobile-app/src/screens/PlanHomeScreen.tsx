import React, {useState} from 'react';
import {Image, Pressable, ScrollView, StyleSheet, Text, TextInput, View} from 'react-native';
import {useSafeAreaInsets} from 'react-native-safe-area-context';
import type {BottomTabScreenProps} from '@react-navigation/bottom-tabs';
import type {CompositeScreenProps} from '@react-navigation/native';
import type {NativeStackScreenProps} from '@react-navigation/native-stack';
import {BrandMark, Icon, IconButton, OfflineBanner, Tag} from '../components/ui';
import {colors, radii, softShadow, spacing, type} from '../theme';
import {useAppStore} from '../store/useAppStore';
import type {MainTabParamList, RootStackParamList} from '../navigation/types';

type Props = CompositeScreenProps<BottomTabScreenProps<MainTabParamList, 'Plan'>, NativeStackScreenProps<RootStackParamList>>;
const examples = ['9月带父母去青岛，节奏慢一点', '国庆去川西看秋色，7天自驾', '周末杭州两天，不走网红路线'];

export function PlanHomeScreen({navigation}: Props) {
  const insets = useSafeAreaInsets(); const {mode, trips} = useAppStore(); const [prompt, setPrompt] = useState('');
  const begin = (value = prompt) => {if (value.trim()) {navigation.navigate('Conversation', {prompt: value.trim()});}};
  const recent = trips[0];
  return (
    <View style={styles.root}>
      <ScrollView keyboardShouldPersistTaps="handled" contentContainerStyle={[styles.content, {paddingTop: insets.top + 18}]}>
        <View style={styles.top}><BrandMark /><View style={styles.topActions}><IconButton name="message-text-clock-outline" label="历史对话" onPress={() => navigation.navigate('ConversationHistory')} /><IconButton name="plus" label="新建规划" onPress={() => {setPrompt(''); navigation.navigate('Conversation');}} /></View></View>
        {mode === 'demo' && <OfflineBanner />}
        <View style={styles.hero}><Text style={styles.kicker}>下一站，交给轻舟</Text><Text style={styles.title}>这次想去哪儿？</Text><Text style={styles.subtitle}>告诉我目的地、时间和同行的人，其余复杂工作交给我。</Text></View>
        <View style={styles.composer}>
          <TextInput testID="plan-prompt" value={prompt} onChangeText={setPrompt} placeholder="例如：8月底两个人去滇西北，想慢慢玩7天…" placeholderTextColor={colors.inkFaint} multiline style={styles.textarea} />
          <View style={styles.composerFooter}><Pressable style={styles.attach}><Icon name="plus" size={20} /><Text style={styles.attachText}>补充条件</Text></Pressable><Pressable testID="plan-send" accessibilityRole="button" onPress={() => begin()} style={[styles.send, !prompt.trim() && styles.sendDisabled]}><Icon name="arrow-up" color={colors.paper} /></Pressable></View>
        </View>
        <ScrollView horizontal showsHorizontalScrollIndicator={false} contentContainerStyle={styles.examples}>
          {examples.map(item => <Pressable key={item} onPress={() => {setPrompt(item); begin(item);}} style={styles.example}><Text numberOfLines={2} style={styles.exampleText}>{item}</Text><Icon name="arrow-top-right" color={colors.inkMuted} size={18} /></Pressable>)}
        </ScrollView>
        {recent && <View style={styles.recentSection}>
          <View style={styles.sectionHead}><Text style={styles.sectionTitle}>最近行程</Text><Pressable onPress={() => navigation.navigate('Trips')} style={styles.all}><Text style={styles.allText}>全部</Text><Icon name="chevron-right" size={18} color={colors.inkMuted} /></Pressable></View>
          <Pressable onPress={() => navigation.navigate('TripMap', {tripId: recent.id})} style={styles.tripCard}>
            <View style={styles.tripCopy}><Tag active>{recent.status === 'planning' ? '规划中' : '已完成'}</Tag><Text style={styles.tripTitle}>{recent.title}</Text><Text style={styles.tripMeta}>{recent.dateRange}</Text><View style={styles.tripTags}>{recent.tags.slice(0, 2).map(tag => <Text key={tag} style={styles.tripTag}>{tag}</Text>)}</View></View>
            <Image source={recent.cover} style={styles.cover} />
          </Pressable>
        </View>}
      </ScrollView>
    </View>
  );
}

const styles = StyleSheet.create({
  root: {flex: 1, backgroundColor: colors.canvas}, content: {paddingBottom: 126}, top: {paddingHorizontal: spacing.lg, flexDirection: 'row', justifyContent: 'space-between', alignItems: 'center'},
  topActions: {flexDirection: 'row', gap: 10}, hero: {paddingHorizontal: spacing.lg, paddingTop: 54, paddingBottom: 24}, kicker: {...type.caption, color: colors.blueDeep, fontWeight: '700', marginBottom: 8},
  title: {...type.hero, color: colors.ink}, subtitle: {...type.body, color: colors.inkMuted, marginTop: 10, maxWidth: 330},
  composer: {...softShadow, marginHorizontal: spacing.md, minHeight: 166, borderRadius: radii.xl, backgroundColor: colors.paper, padding: spacing.md},
  textarea: {...type.body, flex: 1, minHeight: 86, color: colors.ink, textAlignVertical: 'top'}, composerFooter: {flexDirection: 'row', justifyContent: 'space-between', alignItems: 'center'},
  attach: {flexDirection: 'row', alignItems: 'center', gap: 6, padding: 8}, attachText: {...type.caption, color: colors.inkMuted}, send: {width: 44, height: 44, borderRadius: 22, backgroundColor: colors.ink, alignItems: 'center', justifyContent: 'center'}, sendDisabled: {opacity: 0.25},
  examples: {paddingHorizontal: spacing.md, paddingVertical: spacing.md, gap: 10}, example: {width: 180, minHeight: 72, borderRadius: radii.md, backgroundColor: colors.paper, borderWidth: 1, borderColor: colors.line, padding: 13, flexDirection: 'row', alignItems: 'flex-start', gap: 4},
  exampleText: {...type.caption, color: colors.ink, flex: 1}, recentSection: {paddingHorizontal: spacing.md, marginTop: 18}, sectionHead: {flexDirection: 'row', justifyContent: 'space-between', alignItems: 'center', marginBottom: 14},
  sectionTitle: {...type.section, color: colors.ink}, all: {flexDirection: 'row', alignItems: 'center'}, allText: {...type.caption, color: colors.inkMuted},
  tripCard: {height: 210, borderRadius: radii.xl, backgroundColor: colors.limeSoft, overflow: 'hidden', flexDirection: 'row'}, tripCopy: {flex: 1, padding: spacing.lg, alignItems: 'flex-start', zIndex: 2},
  tripTitle: {...type.section, color: colors.ink, marginTop: 14}, tripMeta: {...type.caption, color: colors.inkMuted, fontWeight: '700', marginTop: 6}, tripTags: {flexDirection: 'row', gap: 8, marginTop: 16}, tripTag: {...type.caption, color: '#6D7338'},
  cover: {width: 150, height: 150, borderRadius: 30, position: 'absolute', right: -18, bottom: -10, transform: [{rotate: '-8deg'}]},
});
