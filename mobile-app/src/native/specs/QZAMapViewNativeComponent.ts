import type {HostComponent, ViewProps} from 'react-native';
import type {BubblingEventHandler, Double, Int32} from 'react-native/Libraries/Types/CodegenTypes';
import codegenNativeComponent from 'react-native/Libraries/Utilities/codegenNativeComponent';
import codegenNativeCommands from 'react-native/Libraries/Utilities/codegenNativeCommands';

export type NativeMapMarker = Readonly<{
  id: string; title: string; latitude: Double; longitude: Double; index: Int32; kind: string; selected: boolean;
}>;
type MarkerPressEvent = Readonly<{id: string}>;
type MapErrorEvent = Readonly<{code: string; message: string}>;
type CameraIdleEvent = Readonly<{latitude: Double; longitude: Double; zoom: Double}>;

export interface NativeProps extends ViewProps {
  markers: ReadonlyArray<NativeMapMarker>;
  polylineCoordinates: ReadonlyArray<Double>;
  selectedMarkerId?: string;
  showsUserLocation?: boolean;
  mapPaddingTop?: Int32;
  mapPaddingRight?: Int32;
  mapPaddingBottom?: Int32;
  mapPaddingLeft?: Int32;
  onMapReady?: BubblingEventHandler<Readonly<{}>>;
  onMapError?: BubblingEventHandler<MapErrorEvent>;
  onMarkerPress?: BubblingEventHandler<MarkerPressEvent>;
  onCameraIdle?: BubblingEventHandler<CameraIdleEvent>;
}

interface NativeCommands {
  fitToCoordinates: (viewRef: React.ElementRef<HostComponent<NativeProps>>, coordinatesJson: string, padding: Int32, animated: boolean) => void;
  moveCamera: (viewRef: React.ElementRef<HostComponent<NativeProps>>, latitude: Double, longitude: Double, zoom: Double, animated: boolean) => void;
  setSelectedMarker: (viewRef: React.ElementRef<HostComponent<NativeProps>>, markerId: string) => void;
}

export const Commands: NativeCommands = codegenNativeCommands<NativeCommands>({supportedCommands: ['fitToCoordinates', 'moveCamera', 'setSelectedMarker']});
export default codegenNativeComponent<NativeProps>('QZAMapView') as HostComponent<NativeProps>;
