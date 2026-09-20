// Lightweight, advisory image checks. These do not estimate pose, coverage,
// focus distance or reconstruction success. Keep algorithm/version in exports.
export type QualityWarning = 'dark' | 'bright' | 'detail';
export interface ImageQuality {
  version: 1;
  brightness: number;
  clipped: number;
  detail: number;
  warnings: QualityWarning[];
}
export function inspectPixels(data: Uint8ClampedArray, width: number, height: number) {
  if (width < 3 || height < 3 || data.length !== width * height * 4)
    throw new Error('Invalid analysis image');
  const gray = new Uint8Array(width * height);
  let total = 0,
    clipped = 0,
    samples = 0;
  // Central region: less background interference. Still not object detection.
  const x0 = Math.floor(width * 0.15),
    x1 = Math.ceil(width * 0.85);
  const y0 = Math.floor(height * 0.15),
    y1 = Math.ceil(height * 0.85);
  for (let i = 0; i < gray.length; i++)
    gray[i] = Math.round(
      data[i * 4] * 0.2126 + data[i * 4 + 1] * 0.7152 + data[i * 4 + 2] * 0.0722,
    );
  let sum = 0,
    squares = 0;
  for (let y = Math.max(1, y0); y < Math.min(height - 1, y1); y++) {
    for (let x = Math.max(1, x0); x < Math.min(width - 1, x1); x++) {
      const i = y * width + x,
        light = gray[i];
      total += light;
      clipped += light > 248 ? 1 : 0;
      const edge = 4 * light - gray[i - 1] - gray[i + 1] - gray[i - width] - gray[i + width];
      sum += edge;
      squares += edge * edge;
      samples++;
    }
  }
  const brightness = total / samples,
    clipping = clipped / samples;
  const detail = Math.max(0, squares / samples - (sum / samples) ** 2);
  const warnings: QualityWarning[] = [];
  if (brightness < 45) warnings.push('dark');
  if (brightness > 225 || clipping > 0.35) warnings.push('bright');
  if (detail < 35) warnings.push('detail');
  return {
    gray,
    quality: {
      version: 1,
      brightness: Math.round(brightness),
      clipped: Math.round(clipping * 1000) / 1000,
      detail: Math.round(detail),
      warnings,
    } as ImageQuality,
  };
}
export function imageDifference(a: Uint8Array, b: Uint8Array | null) {
  if (!b || a.length !== b.length) return null;
  let difference = 0;
  for (let i = 0; i < a.length; i++) difference += Math.abs(a[i] - b[i]);
  return difference / a.length;
}
export const qualityMessages: Record<QualityWarning, string> = {
  dark: 'Ajoutez une lumière douce.',
  bright: 'Évitez les reflets et la lumière directe.',
  detail: 'Vérifiez la netteté du plat à l’écran.',
};
export const capturePasses = [
  {
    name: 'Les côtés',
    angle: '30°',
    title: 'Un premier tour, assez bas.',
    instruction:
      'Inclinez le téléphone vers le plat, à environ 30° au-dessus de la table. Faites un tour complet en gardant toute l’assiette dans le cadre.',
    short: 'À hauteur du plat, légèrement au-dessus.',
    icon: 'low',
  },
  {
    name: 'Les reliefs',
    angle: '45°',
    title: 'Un deuxième tour, plus haut.',
    instruction:
      'Remontez le téléphone vers 45°. Refaites le tour pour voir les reliefs et les ingrédients que le premier passage cachait.',
    short: 'Remontez le téléphone, puis refaites le tour.',
    icon: 'middle',
  },
  {
    name: 'Le dessus',
    angle: '65°',
    title: 'Un dernier tour, vu d’en haut.',
    instruction:
      'Montez vers 65–80° et visez le centre. Faites le tour pour voir le dessus et l’intérieur du bol, sans retourner le plat.',
    short: 'Visez le dessus et l’intérieur du bol.',
    icon: 'high',
  },
] as const;
