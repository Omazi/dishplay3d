// The only source of timing, framing and responsive geometry for the narrative.
export const chapters = [0, 0.3, 0.62, 0.94] as const;
export const chapterIds = ['arrivee', 'experience-3d', 'menu-reveal', 'sur-table'] as const;
export const motionQuery = '(prefers-reduced-motion: no-preference) and (min-height: 720px)';
const clamp = (x: number) => Math.min(1, Math.max(0, x));
const smooth = (x: number) => {
  const p = clamp(x);
  return p * p * (3 - 2 * p);
};
const mix = (a: number, b: number, p: number) => a + (b - a) * p;
export function narrativeFrame(progress: number, width: number, height: number) {
  const p = clamp(progress),
    mobile = width < 760;
  const approach = smooth((p - 0.04) / 0.2);
  const menu = smooth((p - 0.4) / 0.2);
  const table = smooth((p - 0.72) / 0.18);
  const base = Math.min(
    mobile ? width * 1.06 : width * 0.46,
    mobile ? 440 : 640,
    height * (mobile ? 0.67 : 0.94),
  );
  const phoneWidth = Math.min(mobile ? 190 : 286, height * 0.43);
  const centerX = width * (mobile ? 0.5 : 0.72);
  const centerY = height * (mobile ? 0.62 : 0.5);
  const phoneY = height * (mobile ? 0.68 : 0.5);
  const size = mix(mix(base, base * 1.04, approach), phoneWidth * 0.88, menu);
  return {
    x: centerX,
    y: mix(mix(centerY, phoneY - phoneWidth * 0.25, menu), height * (mobile ? 0.64 : 0.56), table),
    size: mix(size, base * 0.75, table),
    phoneWidth,
    renderSize: mobile ? 384 : 640,
    phoneShell: smooth((p - 0.56) / 0.12) * (1 - table),
    centerY: phoneY,
    theta: mix(mix(0, mobile ? 24 : 38, approach), -14, menu) * (1 - table),
    phi: mix(75, 66, table),
    radius: mix(mix(110, 99, approach), 110, menu),
    phone: menu * (1 - table),
    table,
    card: menu * (1 - table),
    scene: p < 0.2 ? 0 : p < 0.5 ? 1 : p < 0.8 ? 2 : 3,
    progress: p,
    copyOpacity: [
      1 - smooth((p - 0.14) / 0.06),
      smooth((p - 0.2) / 0.04) * (1 - smooth((p - 0.46) / 0.04)),
      smooth((p - 0.5) / 0.04) * (1 - smooth((p - 0.76) / 0.04)),
      smooth((p - 0.8) / 0.04),
    ],
  };
}
