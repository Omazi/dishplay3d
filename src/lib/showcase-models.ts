// Illustrative licensed models, not reconstructions of the catalogue photographs.
export const showcaseModels = [
  {
    id: 'burger',
    name: 'Le burger',
    src: '/models/burger-illustration.glb',
    usdz: '/models/burger-illustration.usdz',
    poster: '/images/burger-model.webp',
    author: 'Ehsan Abbasi',
    license: 'CC BY-SA 4.0',
    licenseUrl: 'https://creativecommons.org/licenses/by-sa/4.0/',
    source:
      'https://sketchfab.com/3d-models/back-yard-burgers-classic-burger-6e13942ff76d4129b06e097cdd060adb',
    orbit: '0deg 75deg 110%',
  },
  {
    id: 'pasta',
    name: 'Les pâtes',
    src: '/models/pasta-illustration.glb',
    usdz: '/models/pasta-illustration.usdz',
    poster: '/images/pasta-model.webp',
    author: 'ne0ns / Ervinas',
    license: 'CC BY 4.0',
    licenseUrl: 'https://creativecommons.org/licenses/by/4.0/',
    source: 'https://sketchfab.com/3d-models/pasta-bec7601a89f14d0bbe7eb40b48d14b26',
    orbit: '0deg 45deg 110%',
  },
  {
    id: 'salad',
    name: 'La salade',
    src: '/models/salad-illustration.glb',
    usdz: '/models/salad-illustration.usdz',
    poster: '/images/salad-model.webp',
    author: 'churaed',
    license: 'CC BY 4.0',
    licenseUrl: 'https://creativecommons.org/licenses/by/4.0/',
    source: 'https://sketchfab.com/3d-models/salad-5254132bd1b24be7a2dc888aba5e51a3',
    orbit: '0deg 45deg 110%',
  },
] as const;
export type ShowcaseModel = (typeof showcaseModels)[number];
