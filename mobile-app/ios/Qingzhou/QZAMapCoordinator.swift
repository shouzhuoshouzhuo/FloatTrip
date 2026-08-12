import Foundation
import UIKit
import CoreLocation
import MapKit

private final class QZAAppleMapDelegate: NSObject, MKMapViewDelegate {
  var onReady: (() -> Void)?
  var onMarkerPress: ((String) -> Void)?
  var onCameraIdle: ((Double, Double, Double) -> Void)?

  func mapViewDidFinishLoadingMap(_ mapView: MKMapView) { onReady?() }
  func mapView(_ mapView: MKMapView, didSelect view: MKAnnotationView) { if let id = view.annotation?.subtitle ?? nil { onMarkerPress?(id) } }
  func mapView(_ mapView: MKMapView, regionDidChangeAnimated animated: Bool) { let center = mapView.centerCoordinate; onCameraIdle?(center.latitude, center.longitude, Double(mapView.region.span.latitudeDelta)) }
  func mapView(_ mapView: MKMapView, rendererFor overlay: MKOverlay) -> MKOverlayRenderer {
    guard let polyline = overlay as? MKPolyline else { return MKOverlayRenderer(overlay: overlay) }
    let renderer = MKPolylineRenderer(polyline: polyline)
    renderer.lineWidth = 6
    renderer.strokeColor = UIColor(red: 0.18, green: 0.70, blue: 0.95, alpha: 1)
    return renderer
  }
  func mapView(_ mapView: MKMapView, viewFor annotation: MKAnnotation) -> MKAnnotationView? {
    if annotation is MKUserLocation { return nil }
    let identifier = "QZAApplePin"
    let pin = (mapView.dequeueReusableAnnotationView(withIdentifier: identifier) as? MKMarkerAnnotationView) ?? MKMarkerAnnotationView(annotation: annotation, reuseIdentifier: identifier)
    pin.annotation = annotation
    pin.canShowCallout = true
    pin.markerTintColor = UIColor(red: 0.18, green: 0.70, blue: 0.95, alpha: 1)
    return pin
  }
}

#if canImport(MAMapKit) && canImport(AMapFoundationKit)
import MAMapKit
import AMapFoundationKit

@objcMembers
final class QZAMapCoordinator: NSObject, MAMapViewDelegate {
  let view: UIView
  // A live MapKit view is always available on iOS. AMap takes precedence when
  // its binary is linked and a valid production key is supplied.
  let isConfigured = true
  var onReady: (() -> Void)?
  var onMarkerPress: ((String) -> Void)?
  var onCameraIdle: ((Double, Double, Double) -> Void)?
  private var mapView: MAMapView?
  private var appleMapView: MKMapView?
  private var appleDelegate: QZAAppleMapDelegate?
  private var markersById: [String: MAPointAnnotation] = [:]
  private var appleMarkersById: [String: MKPointAnnotation] = [:]

  @objc init(apiKey: String) {
    if !apiKey.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty {
      MAMapView.updatePrivacyShow(.didShow, privacyInfo: .didContain)
      MAMapView.updatePrivacyAgree(.didAgree)
      AMapServices.shared().apiKey = apiKey
      AMapServices.shared().enableHTTPS = true
      let map = MAMapView(frame: .zero)
      map.isRotateEnabled = false
      map.isShowsCompass = false
      map.showsScale = false
      map.zoomLevel = 12
      view = map
      mapView = map
    } else {
      let map = MKMapView(frame: .zero)
      map.isRotateEnabled = false
      map.showsCompass = false
      map.showsScale = false
      map.showsUserLocation = true
      view = map
      appleMapView = map
    }
    super.init()
    mapView?.delegate = self
    if let appleMapView {
      let delegate = QZAAppleMapDelegate()
      delegate.onReady = { [weak self] in self?.onReady?() }
      delegate.onMarkerPress = { [weak self] id in self?.onMarkerPress?(id) }
      delegate.onCameraIdle = { [weak self] latitude, longitude, zoom in self?.onCameraIdle?(latitude, longitude, zoom) }
      appleMapView.delegate = delegate
      appleDelegate = delegate
    }
  }

  func updateMarkers(_ payload: [[String: Any]], selectedId: String) {
    if let appleMapView {
      appleMapView.removeAnnotations(appleMapView.annotations.filter { !($0 is MKUserLocation) })
      appleMarkersById.removeAll()
      for item in payload {
        guard let id = item["id"] as? String, let latitude = item["latitude"] as? Double, let longitude = item["longitude"] as? Double else { continue }
        let point = MKPointAnnotation()
        point.coordinate = CLLocationCoordinate2D(latitude: latitude, longitude: longitude)
        point.title = item["title"] as? String
        point.subtitle = id
        appleMarkersById[id] = point
        appleMapView.addAnnotation(point)
        if id == selectedId { appleMapView.selectAnnotation(point, animated: true) }
      }
      return
    }
    guard let mapView else { return }
    let removable = mapView.annotations.filter { !($0 is MAUserLocation) }
    mapView.removeAnnotations(removable)
    markersById.removeAll()
    for item in payload {
      guard let id = item["id"] as? String,
            let latitude = item["latitude"] as? Double,
            let longitude = item["longitude"] as? Double else { continue }
      let point = MAPointAnnotation()
      point.coordinate = CLLocationCoordinate2D(latitude: latitude, longitude: longitude)
      point.title = item["title"] as? String
      point.subtitle = id
      markersById[id] = point
      mapView.addAnnotation(point)
      if id == selectedId { mapView.selectAnnotation(point, animated: true) }
    }
  }

  func updatePolyline(_ values: [NSNumber]) {
    if let appleMapView {
      appleMapView.removeOverlays(appleMapView.overlays)
      var coordinates: [CLLocationCoordinate2D] = []
      var index = 0
      while index + 1 < values.count {
        coordinates.append(CLLocationCoordinate2D(latitude: values[index].doubleValue, longitude: values[index + 1].doubleValue))
        index += 2
      }
      if coordinates.count > 1 { appleMapView.addOverlay(MKPolyline(coordinates: coordinates, count: coordinates.count)) }
      return
    }
    guard let mapView else { return }
    mapView.removeOverlays(mapView.overlays)
    var coordinates: [CLLocationCoordinate2D] = []
    var index = 0
    while index + 1 < values.count {
      coordinates.append(CLLocationCoordinate2D(latitude: values[index].doubleValue, longitude: values[index + 1].doubleValue))
      index += 2
    }
    if coordinates.count > 1, let polyline = MAPolyline(coordinates: &coordinates, count: UInt(coordinates.count)) { mapView.add(polyline) }
  }

  func setShowsUserLocation(_ value: Bool) { mapView?.showsUserLocation = value; appleMapView?.showsUserLocation = value }
  func setPadding(top: Int, right: Int, bottom: Int, left: Int) {
    mapView?.logoCenter = CGPoint(x: max(64, left + 50), y: max(0, Int(view.bounds.height) - bottom - 20))
    appleMapView?.layoutMargins = UIEdgeInsets(top: CGFloat(top), left: CGFloat(left), bottom: CGFloat(bottom), right: CGFloat(right))
  }
  func fit(coordinatesJSON: String, padding: Int, animated: Bool) {
    guard let data = coordinatesJSON.data(using: .utf8), let list = try? JSONSerialization.jsonObject(with: data) as? [[String: Double]], !list.isEmpty else { return }
    if let appleMapView {
      let coordinates = list.map { CLLocationCoordinate2D(latitude: $0["latitude"] ?? 0, longitude: $0["longitude"] ?? 0) }
      let rect = coordinates.reduce(MKMapRect.null) { $0.union(MKMapRect(origin: MKMapPoint($1), size: MKMapSize(width: 0, height: 0))) }
      appleMapView.setVisibleMapRect(rect, edgePadding: UIEdgeInsets(top: CGFloat(padding), left: CGFloat(padding), bottom: CGFloat(padding), right: CGFloat(padding)), animated: animated)
      return
    }
    guard let mapView else { return }
    var rect = MAMapRectNull
    for point in list {
      let mapPoint = MAMapPointForCoordinate(CLLocationCoordinate2D(latitude: point["latitude"] ?? 0, longitude: point["longitude"] ?? 0))
      rect = MAMapRectUnion(rect, MAMapRectMake(mapPoint.x, mapPoint.y, 0, 0))
    }
    mapView.setVisibleMapRect(rect, edgePadding: UIEdgeInsets(top: CGFloat(padding), left: CGFloat(padding), bottom: CGFloat(padding), right: CGFloat(padding)), animated: animated)
  }
  func move(latitude: Double, longitude: Double, zoom: Double, animated: Bool) {
    if let appleMapView { appleMapView.setCenter(CLLocationCoordinate2D(latitude: latitude, longitude: longitude), animated: animated); return }
    mapView?.setCenter(CLLocationCoordinate2D(latitude: latitude, longitude: longitude), animated: animated); mapView?.setZoomLevel(zoom, animated: animated)
  }
  func select(markerId: String) {
    if let marker = appleMarkersById[markerId] { appleMapView?.selectAnnotation(marker, animated: true); return }
    if let marker = markersById[markerId] { mapView?.selectAnnotation(marker, animated: true) }
  }

  func mapViewDidFinishLoadingMap(_ mapView: MAMapView!) { onReady?() }
  func mapView(_ mapView: MAMapView!, didSelect view: MAAnnotationView!) { if let id = view.annotation.subtitle ?? nil { onMarkerPress?(id) } }
  func mapView(_ mapView: MAMapView!, mapDidMoveByUser wasUserAction: Bool) { let center = mapView.centerCoordinate; onCameraIdle?(center.latitude, center.longitude, mapView.zoomLevel) }
  func mapView(_ mapView: MAMapView!, rendererFor overlay: MAOverlay!) -> MAOverlayRenderer! {
    guard let polyline = overlay as? MAPolyline else { return nil }
    let renderer = MAPolylineRenderer(polyline: polyline)
    renderer?.lineWidth = 7
    renderer?.strokeColor = UIColor(red: 1, green: 0.55, blue: 0.29, alpha: 1)
    return renderer
  }
  func mapView(_ mapView: MAMapView!, viewFor annotation: MAAnnotation!) -> MAAnnotationView! {
    if annotation is MAUserLocation { return nil }
    let identifier = "QZAPin"
    let pin = (mapView.dequeueReusableAnnotationView(withIdentifier: identifier) as? MAPinAnnotationView) ?? MAPinAnnotationView(annotation: annotation, reuseIdentifier: identifier)
    pin?.annotation = annotation
    pin?.canShowCallout = true
    pin?.animatesDrop = false
    pin?.pinColor = .red
    return pin
  }
}
#else
@objcMembers
final class QZAMapCoordinator: NSObject, MKMapViewDelegate {
  let view: UIView
  let isConfigured = true
  var onReady: (() -> Void)?
  var onMarkerPress: ((String) -> Void)?
  var onCameraIdle: ((Double, Double, Double) -> Void)?
  private let mapView: MKMapView
  private var markersById: [String: MKPointAnnotation] = [:]

  @objc init(apiKey: String) {
    mapView = MKMapView(frame: .zero)
    mapView.isRotateEnabled = false
    mapView.showsCompass = false
    mapView.showsScale = false
    mapView.showsUserLocation = true
    view = mapView
    super.init()
    mapView.delegate = self
  }

  func updateMarkers(_ payload: [[String: Any]], selectedId: String) {
    mapView.removeAnnotations(mapView.annotations.filter { !($0 is MKUserLocation) })
    markersById.removeAll()
    for item in payload {
      guard let id = item["id"] as? String, let latitude = item["latitude"] as? Double, let longitude = item["longitude"] as? Double else { continue }
      let point = MKPointAnnotation(); point.coordinate = CLLocationCoordinate2D(latitude: latitude, longitude: longitude); point.title = item["title"] as? String; point.subtitle = id
      markersById[id] = point; mapView.addAnnotation(point)
      if id == selectedId { mapView.selectAnnotation(point, animated: true) }
    }
  }
  func updatePolyline(_ values: [NSNumber]) {
    mapView.removeOverlays(mapView.overlays)
    var coordinates: [CLLocationCoordinate2D] = []; var index = 0
    while index + 1 < values.count { coordinates.append(CLLocationCoordinate2D(latitude: values[index].doubleValue, longitude: values[index + 1].doubleValue)); index += 2 }
    if coordinates.count > 1 { mapView.addOverlay(MKPolyline(coordinates: coordinates, count: coordinates.count)) }
  }
  func setShowsUserLocation(_ value: Bool) { mapView.showsUserLocation = value }
  func setPadding(top: Int, right: Int, bottom: Int, left: Int) { mapView.layoutMargins = UIEdgeInsets(top: CGFloat(top), left: CGFloat(left), bottom: CGFloat(bottom), right: CGFloat(right)) }
  func fit(coordinatesJSON: String, padding: Int, animated: Bool) {
    guard let data = coordinatesJSON.data(using: .utf8), let list = try? JSONSerialization.jsonObject(with: data) as? [[String: Double]], !list.isEmpty else { return }
    let rect = list.map { CLLocationCoordinate2D(latitude: $0["latitude"] ?? 0, longitude: $0["longitude"] ?? 0) }.reduce(MKMapRect.null) { $0.union(MKMapRect(origin: MKMapPoint($1), size: MKMapSize(width: 0, height: 0))) }
    mapView.setVisibleMapRect(rect, edgePadding: UIEdgeInsets(top: CGFloat(padding), left: CGFloat(padding), bottom: CGFloat(padding), right: CGFloat(padding)), animated: animated)
  }
  func move(latitude: Double, longitude: Double, zoom: Double, animated: Bool) { mapView.setCenter(CLLocationCoordinate2D(latitude: latitude, longitude: longitude), animated: animated) }
  func select(markerId: String) { if let marker = markersById[markerId] { mapView.selectAnnotation(marker, animated: true) } }
  func mapViewDidFinishLoadingMap(_ mapView: MKMapView) { onReady?() }
  func mapView(_ mapView: MKMapView, didSelect view: MKAnnotationView) { if let id = view.annotation?.subtitle ?? nil { onMarkerPress?(id) } }
  func mapView(_ mapView: MKMapView, regionDidChangeAnimated animated: Bool) { let center = mapView.centerCoordinate; onCameraIdle?(center.latitude, center.longitude, Double(mapView.region.span.latitudeDelta)) }
  func mapView(_ mapView: MKMapView, rendererFor overlay: MKOverlay) -> MKOverlayRenderer { guard let polyline = overlay as? MKPolyline else { return MKOverlayRenderer(overlay: overlay) }; let renderer = MKPolylineRenderer(polyline: polyline); renderer.lineWidth = 6; renderer.strokeColor = UIColor(red: 0.18, green: 0.70, blue: 0.95, alpha: 1); return renderer }
  func mapView(_ mapView: MKMapView, viewFor annotation: MKAnnotation) -> MKAnnotationView? { if annotation is MKUserLocation { return nil }; let identifier = "QZAApplePin"; let pin = (mapView.dequeueReusableAnnotationView(withIdentifier: identifier) as? MKMarkerAnnotationView) ?? MKMarkerAnnotationView(annotation: annotation, reuseIdentifier: identifier); pin.annotation = annotation; pin.canShowCallout = true; pin.markerTintColor = UIColor(red: 0.18, green: 0.70, blue: 0.95, alpha: 1); return pin }
}
#endif
