# 轻舟移动端

`mobile-app/` 是轻舟的独立企业级移动客户端。它使用 Bare React Native 0.86.2、TypeScript、Hermes 与 New Architecture，保留仓库现有 Web 前端和 `mobile-prototype/`，并直接复用同仓库 FastAPI 协议。

## 已实现

- 登录/注册、Bearer Token 安全存储和 401 统一退出。
- “规划 / 行程 / 我的”三入口，以及沉浸式对话、地图详情和行程编辑页。
- Planning Brief、连续 SSE、事件序号、`Last-Event-ID`、指数退避和前后台恢复。
- 一行式“深度思考”状态，运行中展开、完成后收起，支持手动切换。
- 全屏高德地图 + 三段式 Bottom Sheet；Marker、日期、地点联动。
- 行程排序、改时间、删除、添加、替换、路线优化、撤销/重做及失败回滚。
- 画像记忆新增、修改、删除和候选记忆确认/拒绝。
- 服务端不可用时的本地演示模式，数据写入 MMKV。
- Android Kotlin 与 iOS Objective-C++/Swift 的 `QZAMapView` Fabric 原生组件。

## 目录

```text
src/api/          OpenAPI 生成类型
src/data/         演示数据
src/native/       QZAMapView TypeScript Codegen 规范与包装
src/navigation/   Native Stack / Bottom Tabs
src/screens/      登录、规划、行程地图、编辑、画像
src/services/     API、SSE、安全存储、领域适配
src/store/        Zustand 本地会话状态
android/.../map/  高德 Android SDK Fabric 实现
ios/Qingzhou/     高德 iOS SDK Fabric 实现
.maestro/         核心端到端流程
```

## 本地环境

需要 Node.js 22、JDK 17、Android Studio/SDK、完整 Xcode、CocoaPods 和 Watchman。先检查当前机器：

```bash
cd mobile-app
npm ci
npm run doctor
```

Android 最低 API 26；iOS 使用 React Native 0.86 模板支持的最低版本。应用 ID 和 Bundle ID 均为 `com.qingzhou.travel`。

## 高德 Key

Key 必须在高德控制台分别绑定 Android 包名/签名和 iOS Bundle ID。不要把真实 Key 提交到仓库，也不要放进聊天记录。

Android：

```bash
cp android/local.properties.example android/local.properties
# 填写 sdk.dir 和 AMAP_ANDROID_KEY
```

iOS：

```bash
cp ios/Config/Secrets.xcconfig.example ios/Config/Secrets.xcconfig
# 填写 AMAP_IOS_KEY
```

未配置 Key 时，地图区域会明确提示并显示静态路线预览；行程内容仍可浏览。原生组件在创建地图前调用高德隐私合规 API，仅申请“使用 App 时定位”，拒绝权限不会影响路线浏览。

## 运行

后端默认监听 `8000`。开发环境会从 Metro 地址推断主机：Android 模拟器使用 Metro 主机，iOS 模拟器使用本机。生产地址目前集中在 `src/services/api.ts`，发布前替换为正式 API 域名。

```bash
# 仓库根目录启动 FastAPI
./.venv/bin/uvicorn app.main:app --reload --port 8000

# mobile-app 目录
npm start
npm run android

# iOS 首次或依赖变化后
bundle install
cd ios && bundle exec pod install && cd ..
npm run ios
```

默认 Pod 安装不链接高德厂商二进制，因此 Apple Silicon 模拟器可直接运行并显示静态路线预览。真机或发布构建需要高德地图时执行：

```bash
cd ios
QINGZHOU_ENABLE_AMAP=1 bundle exec pod install
cd ..
```

## 合约与验证

```bash
npm run generate:api   # 从同仓库 FastAPI /openapi.json 重新生成类型
npm run typecheck
npm run lint
npm test
npm run bundle:check
```

Maestro 流程位于 `.maestro/`，在已启动的模拟器或真机上执行：

```bash
maestro test .maestro
```

CI 位于仓库根目录 `.github/workflows/mobile-ci.yml`，覆盖 API 类型漂移、JS 检查、Android Debug 和 iOS Simulator 构建。正式发布前还需要配置高德商业授权、隐私政策第三方 SDK 清单、Android Release Keystore 与 Apple Developer 签名。

## 当前边界

首版不包含逐向导航、离线地图、后台持续定位、语音识别、社交分享和商店正式签名。POI 与步行路线继续由服务端调用高德 Web Service，客户端只接收 GCJ-02 坐标并绘制，避免暴露 Web Service Key。
