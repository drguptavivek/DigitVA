import Svg, { Circle, Path } from "react-native-svg";

/** Pregnancy-related badge: a standing figure with a round belly. 16px, drawn in the text colour. */
export function MaternalIcon({ color, size = 16 }: { color: string; size?: number }) {
  return (
    <Svg width={size} height={size} viewBox="0 0 24 24" fill={color} accessibilityElementsHidden importantForAccessibility="no-hide-descendants">
      <Circle cx={11} cy={4} r={2.5} />
      <Path d="M8 8.5h5a2.5 2.5 0 0 1 2.5 2.5v1.5a3.5 3.5 0 0 1-1.5 2.9V22h-2.2v-5.5h-1.1V22H8.5v-7.2A3.5 3.5 0 0 1 7 12v-1.5A2 2 0 0 1 8 8.5z" />
    </Svg>
  );
}

/** Perinatal badge: a baby's head and body. */
export function PerinatalIcon({ color, size = 16 }: { color: string; size?: number }) {
  return (
    <Svg width={size} height={size} viewBox="0 0 24 24" fill={color} accessibilityElementsHidden importantForAccessibility="no-hide-descendants">
      <Circle cx={12} cy={6.5} r={3.5} />
      <Path d="M4 14.5c0-1.1.9-2 2-2h12a2 2 0 0 1 2 2v1a8 8 0 0 1-16 0z" />
    </Svg>
  );
}

/** Use on a phone row: a tick in a ring, the compact twin of the "ⓘ" beside it. Drawn in strokes of the text colour. */
export function UseIcon({ color, size = 24 }: { color: string; size?: number }) {
  return (
    <Svg width={size} height={size} viewBox="0 0 24 24" fill="none" stroke={color} strokeWidth={2} strokeLinecap="round" strokeLinejoin="round" accessibilityElementsHidden importantForAccessibility="no-hide-descendants">
      <Circle cx={12} cy={12} r={10} />
      <Path d="M7.5 12.5l3 3 6-6.5" />
    </Svg>
  );
}
