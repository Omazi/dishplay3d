// Illustrative licensed models, not reconstructions of the catalogue photographs.
export const showcaseModels = [
  {
    id: 'burger',
    name: 'Le burger',
    src: '/models/burger-illustration.glb',
    poster: '/images/burger-model.webp',
    author: 'darklord3d / erebus3d',
    source:
      'https://sketchfab.com/3d-models/burger-realistic-free-18e59d7dbd2243c69f469e0f056f44c4',
    orbit: '0deg 75deg 110%',
  },
  {
    id: 'pasta',
    name: 'Les pâtes',
    src: '/models/pasta-illustration.glb',
    poster: '/images/pasta-model.webp',
    author: 'ne0ns / Ervinas',
    source: 'https://sketchfab.com/3d-models/pasta-bec7601a89f14d0bbe7eb40b48d14b26',
    orbit: '0deg 45deg 110%',
  },
  {
    id: 'salad',
    name: 'La salade',
    src: '/models/salad-illustration.glb',
    poster: '/images/salad-model.webp',
    author: 'churaed',
    source: 'https://sketchfab.com/3d-models/salad-5254132bd1b24be7a2dc888aba5e51a3',
    orbit: '0deg 45deg 110%',
  },
] as const;
export type ShowcaseModel = (typeof showcaseModels)[number];
