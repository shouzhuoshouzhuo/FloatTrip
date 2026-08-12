package com.qingzhou.travel.map

import com.facebook.react.bridge.ReactApplicationContext
import com.facebook.react.bridge.ReadableArray
import com.facebook.react.module.annotations.ReactModule
import com.facebook.react.uimanager.SimpleViewManager
import com.facebook.react.uimanager.ThemedReactContext
import com.facebook.react.uimanager.ViewManagerDelegate
import com.facebook.react.viewmanagers.QZAMapViewManagerDelegate
import com.facebook.react.viewmanagers.QZAMapViewManagerInterface

@ReactModule(name = QZAMapViewManager.REACT_CLASS)
class QZAMapViewManager(context: ReactApplicationContext) : SimpleViewManager<QZAMapView>(), QZAMapViewManagerInterface<QZAMapView> {
  private val delegate = QZAMapViewManagerDelegate<QZAMapView, QZAMapViewManager>(this)
  override fun getDelegate(): ViewManagerDelegate<QZAMapView> = delegate
  override fun getName() = REACT_CLASS
  override fun createViewInstance(context: ThemedReactContext) = QZAMapView(context)
  override fun onDropViewInstance(view: QZAMapView) { view.onHostDestroy(); super.onDropViewInstance(view) }
  override fun setMarkers(view: QZAMapView, value: ReadableArray?) = view.setMarkers(value)
  override fun setPolylineCoordinates(view: QZAMapView, value: ReadableArray?) = view.setPolylineCoordinates(value)
  override fun setSelectedMarkerId(view: QZAMapView, value: String?) = view.setSelectedMarkerId(value)
  override fun setShowsUserLocation(view: QZAMapView, value: Boolean) = view.setShowsUserLocation(value)
  override fun setMapPaddingTop(view: QZAMapView, value: Int) = view.setPadding(top = value)
  override fun setMapPaddingRight(view: QZAMapView, value: Int) = view.setPadding(right = value)
  override fun setMapPaddingBottom(view: QZAMapView, value: Int) = view.setPadding(bottom = value)
  override fun setMapPaddingLeft(view: QZAMapView, value: Int) = view.setPadding(left = value)
  override fun fitToCoordinates(view: QZAMapView, coordinatesJson: String, padding: Int, animated: Boolean) = view.fitToCoordinates(coordinatesJson, padding, animated)
  override fun moveCamera(view: QZAMapView, latitude: Double, longitude: Double, zoom: Double, animated: Boolean) = view.moveCamera(latitude, longitude, zoom, animated)
  override fun setSelectedMarker(view: QZAMapView, markerId: String) = view.selectMarker(markerId)
  override fun getExportedCustomBubblingEventTypeConstants(): Map<String, Any> = listOf("onMapReady", "onMapError", "onMarkerPress", "onCameraIdle").associateWith { mapOf("phasedRegistrationNames" to mapOf("bubbled" to it, "captured" to "${it}Capture")) }
  companion object { const val REACT_CLASS = "QZAMapView" }
}
