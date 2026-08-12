import React, {forwardRef, useImperativeHandle, useRef, useState} from 'react';
import {ImageBackground, StyleSheet, Text, View} from 'react-native';
import type {Coordinate, MapMarker, RoutePolyline} from '../types';
import {colors, type} from '../theme';
import NativeMap, {Commands} from './specs/QZAMapViewNativeComponent';

export type QZAMapHandle = {fit: (coordinates: Coordinate[]) => void; moveTo: (coordinate: Coordinate, zoom?: number) => void};
type Props = {markers: MapMarker[]; polylines: RoutePolyline[]; selectedMarkerId?: string; showsUserLocation?: boolean; mapPaddingBottom?: number; onMarkerPress?: (id: string) => void};

export const QZAMapView = forwardRef<QZAMapHandle, Props>(function QingzhouNativeMap({markers, polylines, selectedMarkerId = '', showsUserLocation = false, mapPaddingBottom = 260, onMarkerPress}, ref) {
  const nativeRef = useRef<React.ElementRef<typeof NativeMap> | null>(null);
  const [failed, setFailed] = useState(false);
  const flatPolyline = polylines.flatMap(line => line.coordinates.flatMap(point => [point.latitude, point.longitude]));
  useImperativeHandle(ref, () => ({
    fit: coordinates => nativeRef.current && Commands.fitToCoordinates(nativeRef.current, JSON.stringify(coordinates), 48, true),
    moveTo: (coordinate, zoom = 14) => nativeRef.current && Commands.moveCamera(nativeRef.current, coordinate.latitude, coordinate.longitude, zoom, true),
  }));

  if (failed) {
    return (
      <ImageBackground source={require('../assets/images/dali-route-map-portrait.png')} style={styles.fallback} resizeMode="cover">
        <View style={styles.fallbackBadge}><Text style={styles.fallbackText}>地图暂不可用，当前显示路线预览</Text></View>
      </ImageBackground>
    );
  }
  return (
    <NativeMap ref={nativeRef} style={StyleSheet.absoluteFill} markers={markers.map(item => ({...item.coordinate, id: item.id, title: item.title, index: item.index, kind: item.kind, selected: item.selected}))}
      polylineCoordinates={flatPolyline} selectedMarkerId={selectedMarkerId} showsUserLocation={showsUserLocation}
      mapPaddingTop={80} mapPaddingRight={20} mapPaddingBottom={mapPaddingBottom} mapPaddingLeft={20}
      onMapError={event => setFailed(event.nativeEvent.code === 'missing_key')} onMarkerPress={event => onMarkerPress?.(event.nativeEvent.id)} />
  );
});

const styles = StyleSheet.create({
  fallback: {flex: 1, justifyContent: 'flex-end', alignItems: 'center', paddingBottom: 300},
  fallbackBadge: {backgroundColor: 'rgba(255,255,255,0.92)', borderRadius: 999, paddingHorizontal: 14, paddingVertical: 9},
  fallbackText: {...type.caption, color: colors.inkMuted},
});
