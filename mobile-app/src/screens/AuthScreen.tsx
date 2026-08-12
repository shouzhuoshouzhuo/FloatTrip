import React, {useState} from 'react';
import {KeyboardAvoidingView, Platform, Pressable, ScrollView, StyleSheet, Text, TextInput, View} from 'react-native';
import {useSafeAreaInsets} from 'react-native-safe-area-context';
import {ApiError, api} from '../services/api';
import {useAppStore} from '../store/useAppStore';
import {BrandMark, Icon, PrimaryButton} from '../components/ui';
import {colors, radii, softShadow, spacing, type} from '../theme';

export function AuthScreen() {
  const insets = useSafeAreaInsets(); const {setSession, startDemo} = useAppStore();
  const [register, setRegister] = useState(false); const [username, setUsername] = useState(''); const [password, setPassword] = useState('');
  const [loading, setLoading] = useState(false); const [error, setError] = useState('');
  const submit = async () => {
    if (!username.trim() || password.length < 4) {setError('请输入用户名和至少 4 位密码'); return;}
    setLoading(true); setError('');
    try {await setSession(register ? await api.register(username.trim(), password) : await api.login(username.trim(), password));}
    catch (reason) {setError(reason instanceof ApiError ? reason.message : '连接服务失败，请稍后再试');}
    finally {setLoading(false);}
  };
  return (
    <KeyboardAvoidingView style={styles.root} behavior={Platform.OS === 'ios' ? 'padding' : undefined}>
      <ScrollView keyboardShouldPersistTaps="handled" contentContainerStyle={[styles.content, {paddingTop: insets.top + 44, paddingBottom: insets.bottom + 24}]}>
        <BrandMark />
        <View style={styles.intro}><Text style={styles.eyebrow}>对话式旅游规划</Text><Text style={styles.hero}>一句话，抵达更好的旅程。</Text><Text style={styles.lead}>轻舟会记住你的旅行偏好，把复杂路线整理成可以继续编辑的计划。</Text></View>
        <View style={styles.card}>
          <View style={styles.switcher}>
            <Pressable onPress={() => setRegister(false)} style={[styles.switchItem, !register && styles.switchActive]}><Text style={[styles.switchText, !register && styles.switchTextActive]}>登录</Text></Pressable>
            <Pressable onPress={() => setRegister(true)} style={[styles.switchItem, register && styles.switchActive]}><Text style={[styles.switchText, register && styles.switchTextActive]}>注册</Text></Pressable>
          </View>
          <View style={styles.inputWrap}><Icon name="account-outline" color={colors.inkMuted} /><TextInput testID="auth-username" value={username} onChangeText={setUsername} placeholder="用户名" placeholderTextColor={colors.inkFaint} autoCapitalize="none" style={styles.input} /></View>
          <View style={styles.inputWrap}><Icon name="lock-outline" color={colors.inkMuted} /><TextInput testID="auth-password" value={password} onChangeText={setPassword} placeholder="密码" placeholderTextColor={colors.inkFaint} secureTextEntry style={styles.input} /></View>
          {error ? <Text style={styles.error}>{error}</Text> : null}
          <PrimaryButton testID="auth-submit" label={register ? '创建轻舟账号' : '进入轻舟'} icon="arrow-right" loading={loading} onPress={submit} />
        </View>
        <Pressable testID="enter-demo" accessibilityRole="button" onPress={startDemo} style={styles.demo}><Text style={styles.demoText}>暂不登录，先体验演示</Text><Icon name="arrow-right" size={18} color={colors.blueDeep} /></Pressable>
        <Text style={styles.legal}>继续即表示你已阅读并同意《用户协议》和《隐私政策》</Text>
      </ScrollView>
    </KeyboardAvoidingView>
  );
}

const styles = StyleSheet.create({
  root: {flex: 1, backgroundColor: colors.canvas}, content: {paddingHorizontal: spacing.lg, flexGrow: 1},
  intro: {marginTop: 56, marginBottom: 36}, eyebrow: {...type.caption, color: colors.blueDeep, fontWeight: '700', letterSpacing: 1.2, marginBottom: 10},
  hero: {...type.hero, color: colors.ink, maxWidth: 320}, lead: {...type.body, color: colors.inkMuted, marginTop: 14, maxWidth: 330},
  card: {...softShadow, backgroundColor: colors.paper, borderRadius: radii.xl, padding: spacing.lg, gap: 14},
  switcher: {flexDirection: 'row', backgroundColor: colors.canvas, padding: 4, borderRadius: radii.pill, marginBottom: 4},
  switchItem: {flex: 1, height: 42, alignItems: 'center', justifyContent: 'center', borderRadius: radii.pill}, switchActive: {backgroundColor: colors.paper},
  switchText: {...type.body, color: colors.inkFaint}, switchTextActive: {color: colors.ink, fontWeight: '700'},
  inputWrap: {height: 56, borderRadius: radii.md, backgroundColor: colors.canvas, borderWidth: 1, borderColor: colors.line, flexDirection: 'row', alignItems: 'center', paddingHorizontal: 16, gap: 10},
  input: {...type.body, color: colors.ink, flex: 1}, error: {...type.caption, color: colors.danger},
  demo: {height: 48, alignItems: 'center', justifyContent: 'center', flexDirection: 'row', gap: 6, marginTop: 18}, demoText: {...type.body, color: colors.blueDeep, fontWeight: '700'},
  legal: {...type.caption, color: colors.inkFaint, textAlign: 'center', marginTop: 'auto', paddingTop: 32},
});
