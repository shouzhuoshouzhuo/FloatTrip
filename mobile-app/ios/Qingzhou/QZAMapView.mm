#import "QZAMapView.h"
#import <React-RCTAppDelegate/RCTDefaultReactNativeFactoryDelegate.h>
#import <MapKit/MapKit.h>
#import "Qingzhou-Swift.h"

#import <react/renderer/components/QingzhouMapSpec/ComponentDescriptors.h>
#import <react/renderer/components/QingzhouMapSpec/EventEmitters.h>
#import <react/renderer/components/QingzhouMapSpec/Props.h>
#import <react/renderer/components/QingzhouMapSpec/RCTComponentViewHelpers.h>

using namespace facebook::react;

@interface QZAMapView () <RCTQZAMapViewViewProtocol>
@end

@implementation QZAMapView {
  QZAMapCoordinator *_coordinator;
  BOOL _reportedMissingKey;
}

+ (ComponentDescriptorProvider)componentDescriptorProvider
{
  return concreteComponentDescriptorProvider<QZAMapViewComponentDescriptor>();
}

- (instancetype)init
{
  if (self = [super init]) {
    static const auto defaultProps = std::make_shared<const QZAMapViewProps>();
    _props = defaultProps;
    NSString *key = [[NSBundle mainBundle] objectForInfoDictionaryKey:@"AMapAPIKey"] ?: @"";
    _coordinator = [[QZAMapCoordinator alloc] initWithApiKey:key];
    __weak QZAMapView *weakSelf = self;
    _coordinator.onReady = ^{ [weakSelf emitReady]; };
    _coordinator.onMarkerPress = ^(NSString *markerId) { [weakSelf emitMarker:markerId]; };
    _coordinator.onCameraIdle = ^(double latitude, double longitude, double zoom) { [weakSelf emitCameraLatitude:latitude longitude:longitude zoom:zoom]; };
    [self addSubview:_coordinator.view];
  }
  return self;
}

- (void)layoutSubviews
{
  [super layoutSubviews];
  _coordinator.view.frame = self.bounds;
}

- (void)updateProps:(Props::Shared const &)props oldProps:(Props::Shared const &)oldProps
{
  const auto &newProps = *std::static_pointer_cast<QZAMapViewProps const>(props);
  NSMutableArray<NSDictionary *> *markers = [NSMutableArray arrayWithCapacity:newProps.markers.size()];
  for (const auto &marker : newProps.markers) {
    [markers addObject:@{@"id": @(marker.id.c_str()), @"title": @(marker.title.c_str()), @"latitude": @(marker.latitude), @"longitude": @(marker.longitude), @"index": @(marker.index), @"kind": @(marker.kind.c_str()), @"selected": @(marker.selected)}];
  }
  NSMutableArray<NSNumber *> *polyline = [NSMutableArray arrayWithCapacity:newProps.polylineCoordinates.size()];
  for (double value : newProps.polylineCoordinates) { [polyline addObject:@(value)]; }
  [_coordinator updateMarkers:markers selectedId:@(newProps.selectedMarkerId.c_str())];
  [_coordinator updatePolyline:polyline];
  [_coordinator setShowsUserLocation:newProps.showsUserLocation];
  [_coordinator setPaddingWithTop:newProps.mapPaddingTop right:newProps.mapPaddingRight bottom:newProps.mapPaddingBottom left:newProps.mapPaddingLeft];
  [super updateProps:props oldProps:oldProps];
  if (!_coordinator.isConfigured && !_reportedMissingKey) {
    _reportedMissingKey = YES;
    const auto &emitter = static_cast<const QZAMapViewEventEmitter &>(*_eventEmitter);
    emitter.onMapError({"missing_key", "AMAP_IOS_KEY is not configured"});
  }
}

- (void)handleCommand:(const NSString *)commandName args:(const NSArray *)args
{
  RCTQZAMapViewHandleCommand(self, commandName, args);
}
- (void)fitToCoordinates:(NSString *)coordinatesJson padding:(NSInteger)padding animated:(BOOL)animated { [_coordinator fitWithCoordinatesJSON:coordinatesJson padding:padding animated:animated]; }
- (void)moveCamera:(double)latitude longitude:(double)longitude zoom:(double)zoom animated:(BOOL)animated { [_coordinator moveWithLatitude:latitude longitude:longitude zoom:zoom animated:animated]; }
- (void)setSelectedMarker:(NSString *)markerId { [_coordinator selectWithMarkerId:markerId]; }

- (void)emitReady { if (_eventEmitter) { static_cast<const QZAMapViewEventEmitter &>(*_eventEmitter).onMapReady({}); } }
- (void)emitMarker:(NSString *)markerId { if (_eventEmitter) { static_cast<const QZAMapViewEventEmitter &>(*_eventEmitter).onMarkerPress({std::string(markerId.UTF8String)}); } }
- (void)emitCameraLatitude:(double)latitude longitude:(double)longitude zoom:(double)zoom { if (_eventEmitter) { static_cast<const QZAMapViewEventEmitter &>(*_eventEmitter).onCameraIdle({latitude, longitude, zoom}); } }

@end
