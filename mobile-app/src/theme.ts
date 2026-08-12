import {Platform, TextStyle, ViewStyle} from 'react-native';

export const colors = {
  ink: '#111318',
  inkMuted: '#626A73',
  inkFaint: '#9EA5AD',
  canvas: '#F7F8FA',
  paper: '#FFFFFF',
  line: '#E9EBEF',
  blue: '#26B7EE',
  blueDeep: '#0099D6',
  cyanSoft: '#DDF8FF',
  cyanBubble: '#C8F7FB',
  limeSoft: '#F3F6BC',
  green: '#39C887',
  greenSoft: '#EAFBF3',
  warning: '#FF9A4D',
  danger: '#EA5A62',
  lavender: '#8557E8',
  shadow: '#202A35',
  mapOrange: '#FF8D4A',
} as const;

export const radii = {sm: 12, md: 18, lg: 24, xl: 30, pill: 999} as const;
export const spacing = {xs: 6, sm: 10, md: 16, lg: 22, xl: 30, xxl: 40} as const;

export const type: Record<'hero' | 'title' | 'section' | 'body' | 'caption', TextStyle> = {
  hero: {fontSize: 32, lineHeight: 40, fontWeight: '700', letterSpacing: -0.8},
  title: {fontSize: 24, lineHeight: 32, fontWeight: '700', letterSpacing: -0.4},
  section: {fontSize: 19, lineHeight: 26, fontWeight: '700'},
  body: {fontSize: 16, lineHeight: 24, fontWeight: '400'},
  caption: {fontSize: 13, lineHeight: 19, fontWeight: '400'},
};

export const softShadow: ViewStyle = Platform.select({
  ios: {shadowColor: colors.shadow, shadowOpacity: 0.08, shadowRadius: 18, shadowOffset: {width: 0, height: 8}},
  android: {elevation: 3},
  default: {},
}) as ViewStyle;
