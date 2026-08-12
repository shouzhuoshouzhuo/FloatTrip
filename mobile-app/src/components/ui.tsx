import React from 'react';
import {ActivityIndicator, Pressable, StyleSheet, Text, View, type PressableProps, type StyleProp, type ViewStyle} from 'react-native';
import {MaterialDesignIcons} from '@react-native-vector-icons/material-design-icons';
import {colors, radii, softShadow, spacing, type} from '../theme';

type IconName = React.ComponentProps<typeof MaterialDesignIcons>['name'];

export function Icon({name, size = 22, color = colors.ink}: {name: IconName; size?: number; color?: string}) {
  return <MaterialDesignIcons name={name} size={size} color={color} />;
}

export function BrandMark({compact = false}: {compact?: boolean}) {
  return (
    <View style={styles.brandRow}>
      <View style={[styles.brandIcon, compact && styles.brandIconCompact]}><Icon name="sail-boat" size={compact ? 18 : 22} color={colors.paper} /></View>
      {!compact && <Text style={styles.brandText}>轻舟</Text>}
    </View>
  );
}

export function PrimaryButton({label, loading, icon, disabled, style, ...props}: PressableProps & {label: string; loading?: boolean; icon?: IconName; style?: StyleProp<ViewStyle>}) {
  return (
    <Pressable accessibilityRole="button" disabled={disabled || loading} style={({pressed}) => [styles.primary, pressed && styles.pressed, (disabled || loading) && styles.disabled, style]} {...props}>
      {loading ? <ActivityIndicator color={colors.paper} /> : <>{icon && <Icon name={icon} color={colors.paper} size={20} />}<Text style={styles.primaryText}>{label}</Text></>}
    </Pressable>
  );
}

export function IconButton({name, label, tone = 'paper', ...props}: PressableProps & {name: IconName; label: string; tone?: 'paper' | 'dark'}) {
  return (
    <Pressable accessibilityRole="button" accessibilityLabel={label} style={({pressed}) => [styles.iconButton, tone === 'dark' && styles.iconButtonDark, pressed && styles.pressed]} {...props}>
      <Icon name={name} color={tone === 'dark' ? colors.paper : colors.ink} />
    </Pressable>
  );
}

export function Tag({children, active = false}: {children: React.ReactNode; active?: boolean}) {
  return <View style={[styles.tag, active && styles.tagActive]}><Text style={[styles.tagText, active && styles.tagTextActive]}>{children}</Text></View>;
}

export function ScreenHeader({title, subtitle, onBack, right}: {title: string; subtitle?: string; onBack?: () => void; right?: React.ReactNode}) {
  return (
    <View style={styles.header}>
      {onBack ? <IconButton name="arrow-left" label="返回" onPress={onBack} /> : <BrandMark compact />}
      <View style={styles.headerCopy}><Text numberOfLines={1} style={styles.headerTitle}>{title}</Text>{subtitle && <Text numberOfLines={1} style={styles.headerSubtitle}>{subtitle}</Text>}</View>
      <View style={styles.headerRight}>{right}</View>
    </View>
  );
}

export function OfflineBanner() {
  return <View style={styles.offline}><Icon name="cloud-off-outline" size={16} color={colors.inkMuted} /><Text style={styles.offlineText}>当前为只读演示，可随时登录同步真实行程</Text></View>;
}

const styles = StyleSheet.create({
  brandRow: {flexDirection: 'row', alignItems: 'center', gap: 10},
  brandIcon: {width: 40, height: 40, borderRadius: 14, backgroundColor: colors.blue, alignItems: 'center', justifyContent: 'center', transform: [{rotate: '-3deg'}]},
  brandIconCompact: {width: 36, height: 36, borderRadius: 13},
  brandText: {...type.section, color: colors.ink},
  primary: {height: 54, borderRadius: radii.pill, backgroundColor: colors.ink, flexDirection: 'row', alignItems: 'center', justifyContent: 'center', gap: 8, paddingHorizontal: spacing.lg},
  primaryText: {...type.body, color: colors.paper, fontWeight: '700'}, pressed: {opacity: 0.72, transform: [{scale: 0.985}]}, disabled: {opacity: 0.4},
  iconButton: {...softShadow, width: 44, height: 44, borderRadius: 22, backgroundColor: colors.paper, alignItems: 'center', justifyContent: 'center'},
  iconButtonDark: {backgroundColor: colors.ink},
  tag: {paddingHorizontal: 12, paddingVertical: 7, borderRadius: radii.pill, backgroundColor: colors.canvas, borderWidth: 1, borderColor: colors.line},
  tagActive: {backgroundColor: colors.cyanSoft, borderColor: '#B6EDF7'}, tagText: {...type.caption, color: colors.inkMuted}, tagTextActive: {color: colors.blueDeep, fontWeight: '700'},
  header: {height: 64, paddingHorizontal: spacing.md, flexDirection: 'row', alignItems: 'center', gap: 12, backgroundColor: colors.canvas},
  headerCopy: {flex: 1}, headerTitle: {...type.section, fontSize: 18, color: colors.ink}, headerSubtitle: {...type.caption, color: colors.inkMuted}, headerRight: {minWidth: 44, alignItems: 'flex-end'},
  offline: {marginHorizontal: spacing.md, marginBottom: spacing.sm, paddingHorizontal: 14, paddingVertical: 9, borderRadius: radii.md, backgroundColor: '#EEF1F4', flexDirection: 'row', alignItems: 'center', gap: 8},
  offlineText: {...type.caption, color: colors.inkMuted, flex: 1},
});
