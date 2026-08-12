package com.qingzhou.travel.map

import com.facebook.react.BaseReactPackage
import com.facebook.react.bridge.NativeModule
import com.facebook.react.bridge.ReactApplicationContext
import com.facebook.react.module.model.ReactModuleInfo
import com.facebook.react.module.model.ReactModuleInfoProvider
import com.facebook.react.uimanager.ViewManager

class QZAMapPackage : BaseReactPackage() {
  override fun createViewManagers(reactContext: ReactApplicationContext): List<ViewManager<*, *>> = listOf(QZAMapViewManager(reactContext))
  override fun getModule(name: String, reactContext: ReactApplicationContext): NativeModule? = null
  override fun getReactModuleInfoProvider() = ReactModuleInfoProvider {
    mapOf(QZAMapViewManager.REACT_CLASS to ReactModuleInfo(QZAMapViewManager.REACT_CLASS, QZAMapViewManager.REACT_CLASS, false, false, false, true))
  }
}
