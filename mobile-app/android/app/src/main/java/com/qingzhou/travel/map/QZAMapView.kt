package com.qingzhou.travel.map

import android.content.pm.PackageManager
import android.graphics.Color
import android.os.Bundle
import android.widget.FrameLayout
import com.amap.api.maps.AMap
import com.amap.api.maps.CameraUpdateFactory
import com.amap.api.maps.MapView
import com.amap.api.maps.MapsInitializer
import com.amap.api.maps.model.BitmapDescriptorFactory
import com.amap.api.maps.model.CameraPosition
import com.amap.api.maps.model.LatLng
import com.amap.api.maps.model.LatLngBounds
import com.amap.api.maps.model.Marker
import com.amap.api.maps.model.MarkerOptions
import com.amap.api.maps.model.MyLocationStyle
import com.amap.api.maps.model.PolylineOptions
import com.facebook.react.bridge.Arguments
import com.facebook.react.bridge.LifecycleEventListener
import com.facebook.react.bridge.ReactContext
import com.facebook.react.bridge.ReadableArray
import com.facebook.react.uimanager.UIManagerHelper
import com.facebook.react.uimanager.events.Event
import com.facebook.react.uimanager.ThemedReactContext
import org.json.JSONArray

class QZAMapView(private val reactContext: ThemedReactContext) : FrameLayout(reactContext), LifecycleEventListener {
  private var mapView: MapView? = null
  private var aMap: AMap? = null
  private val nativeMarkers = mutableMapOf<String, Marker>()
  private var markerPayload: ReadableArray? = null
  private var polylinePayload: ReadableArray? = null
  private var selectedMarkerId: String = ""
  private var padding = intArrayOf(0, 0, 0, 0)

  init {
    layoutParams = LayoutParams(LayoutParams.MATCH_PARENT, LayoutParams.MATCH_PARENT)
    reactContext.addLifecycleEventListener(this)
    initializeMap()
  }

  private fun initializeMap() {
    val appInfo = context.packageManager.getApplicationInfo(context.packageName, PackageManager.GET_META_DATA)
    val key = appInfo.metaData?.getString("com.amap.api.v2.apikey").orEmpty()
    if (key.isBlank()) {
      post { emit("onMapError", Arguments.createMap().apply { putString("code", "missing_key"); putString("message", "AMAP_ANDROID_KEY is not configured") }) }
      return
    }
    MapsInitializer.updatePrivacyShow(context.applicationContext, true, true)
    MapsInitializer.updatePrivacyAgree(context.applicationContext, true)
    val view = MapView(context)
    view.onCreate(Bundle())
    addView(view, LayoutParams(LayoutParams.MATCH_PARENT, LayoutParams.MATCH_PARENT))
    mapView = view
    aMap = view.map.apply {
      uiSettings.isRotateGesturesEnabled = false
      uiSettings.isTiltGesturesEnabled = false
      uiSettings.isZoomControlsEnabled = false
      uiSettings.isCompassEnabled = false
      setOnMapLoadedListener { emit("onMapReady", Arguments.createMap()) }
      setOnMarkerClickListener { marker ->
        val markerId = marker.`object` as? String ?: return@setOnMarkerClickListener false
        selectMarker(markerId)
        emit("onMarkerPress", Arguments.createMap().apply { putString("id", markerId) })
        true
      }
      setOnCameraChangeListener(object : AMap.OnCameraChangeListener {
        override fun onCameraChange(position: CameraPosition?) = Unit
        override fun onCameraChangeFinish(position: CameraPosition?) {
          position ?: return
          emit("onCameraIdle", Arguments.createMap().apply { putDouble("latitude", position.target.latitude); putDouble("longitude", position.target.longitude); putDouble("zoom", position.zoom.toDouble()) })
        }
      })
    }
  }

  fun setMarkers(value: ReadableArray?) { markerPayload = value; renderMarkers() }
  fun setPolylineCoordinates(value: ReadableArray?) { polylinePayload = value; renderPolyline() }
  fun setSelectedMarkerId(value: String?) { selectedMarkerId = value.orEmpty(); renderMarkers() }
  fun setShowsUserLocation(value: Boolean) {
    try {
      aMap?.myLocationStyle = MyLocationStyle().myLocationType(MyLocationStyle.LOCATION_TYPE_LOCATION_ROTATE_NO_CENTER).showMyLocation(value)
      aMap?.isMyLocationEnabled = value
    } catch (_: SecurityException) {
      emit("onMapError", Arguments.createMap().apply { putString("code", "location_denied"); putString("message", "Location permission is not granted") })
    }
  }
  fun setPadding(top: Int? = null, right: Int? = null, bottom: Int? = null, left: Int? = null) {
    if (top != null) padding[0] = top; if (right != null) padding[1] = right; if (bottom != null) padding[2] = bottom; if (left != null) padding[3] = left
    aMap?.setMapTextZIndex(0); aMap?.setPointToCenter((width + padding[3] - padding[1]) / 2, (height + padding[0] - padding[2]) / 2)
  }

  private fun renderMarkers() {
    val map = aMap ?: return
    nativeMarkers.values.forEach { it.remove() }; nativeMarkers.clear()
    val markers = markerPayload ?: return
    for (index in 0 until markers.size()) {
      val item = markers.getMap(index) ?: continue
      val id = item.getString("id").orEmpty(); val selected = id == selectedMarkerId || item.getBoolean("selected")
      val marker = map.addMarker(MarkerOptions().position(LatLng(item.getDouble("latitude"), item.getDouble("longitude"))).title(item.getString("title")).snippet("第 ${item.getInt("index")} 站").icon(BitmapDescriptorFactory.defaultMarker(if (selected) BitmapDescriptorFactory.HUE_AZURE else BitmapDescriptorFactory.HUE_ORANGE)).zIndex(if (selected) 10f else 1f))
      marker.`object` = id; nativeMarkers[id] = marker
    }
  }

  private fun renderPolyline() {
    aMap?.clear(); renderMarkers()
    val values = polylinePayload ?: return
    val points = mutableListOf<LatLng>()
    var index = 0
    while (index + 1 < values.size()) { points.add(LatLng(values.getDouble(index), values.getDouble(index + 1))); index += 2 }
    if (points.size > 1) aMap?.addPolyline(PolylineOptions().addAll(points).width(14f).color(Color.rgb(255, 141, 74)).setDottedLine(false))
  }

  fun fitToCoordinates(json: String, mapPadding: Int, animated: Boolean) {
    val array = JSONArray(json); val bounds = LatLngBounds.builder()
    for (index in 0 until array.length()) { val item = array.getJSONObject(index); bounds.include(LatLng(item.getDouble("latitude"), item.getDouble("longitude"))) }
    if (array.length() > 0) { val update = CameraUpdateFactory.newLatLngBounds(bounds.build(), mapPadding); if (animated) aMap?.animateCamera(update) else aMap?.moveCamera(update) }
  }
  fun moveCamera(latitude: Double, longitude: Double, zoom: Double, animated: Boolean) { val update = CameraUpdateFactory.newLatLngZoom(LatLng(latitude, longitude), zoom.toFloat()); if (animated) aMap?.animateCamera(update) else aMap?.moveCamera(update) }
  fun selectMarker(id: String) { selectedMarkerId = id; renderMarkers(); nativeMarkers[id]?.showInfoWindow() }

  private fun emit(name: String, payload: com.facebook.react.bridge.WritableMap) {
    val surfaceId = UIManagerHelper.getSurfaceId(reactContext)
    UIManagerHelper.getEventDispatcherForReactTag(reactContext, id)?.dispatchEvent(QZAMapEvent(surfaceId, id, name, payload))
  }
  private class QZAMapEvent(surfaceId: Int, viewId: Int, private val name: String, private val payload: com.facebook.react.bridge.WritableMap) : Event<QZAMapEvent>(surfaceId, viewId) {
    override fun getEventName() = name
    override fun getEventData() = payload
  }

  override fun onHostResume() { mapView?.onResume() }
  override fun onHostPause() { mapView?.onPause() }
  override fun onHostDestroy() { mapView?.onDestroy(); reactContext.removeLifecycleEventListener(this) }
}
