import type { Dish, PublicMenu } from './contracts';
import { createTranslator, type Locale } from './i18n';

// Illustrative catalogue only. These photographs are not reconstruction inputs.
export const demoMenu: PublicMenu = {
  isDemo: true,
  restaurant: {
    id: 'demo',
    name: 'Atelier des saveurs',
    slug: 'demo',
    tagline: 'Une cuisine de saison, une autre façon de la découvrir.',
    currency: 'EUR',
    version: 1,
  },
  categories: [
    { id: 'plats', name: 'Les plats', sortOrder: 0 },
    { id: 'entrees', name: 'Pour commencer', sortOrder: 1 },
  ],
  dishes: [
    {
      id: 'demo-1',
      categoryId: 'plats',
      name: 'Le burger de l’atelier',
      description:
        'Pain doré, légumes croquants et une généreuse garniture. Un exemple de présentation de votre carte.',
      priceCents: 1850,
      allergens: ['Gluten', 'Lait'],
      imageId: 'demo-burger',
      modelGlbUrl: null,
      modelUsdzUrl: null,
      version: 1,
      sortOrder: 0,
      isAvailable: true,
    },
    {
      id: 'demo-2',
      categoryId: 'plats',
      name: 'Pasta della casa',
      description:
        'Pâtes, tomates et herbes fraîches. Les descriptions et allergènes de cette carte sont illustratifs.',
      priceCents: 2200,
      allergens: ['Gluten'],
      imageId: 'demo-pasta',
      modelGlbUrl: null,
      modelUsdzUrl: null,
      version: 1,
      sortOrder: 1,
      isAvailable: true,
    },
    {
      id: 'demo-3',
      categoryId: 'entrees',
      name: 'La salade du marché',
      description:
        'Légumes de saison, feuilles tendres et vinaigrette maison. Une photo pour donner envie de découvrir.',
      priceCents: 1450,
      allergens: ['Moutarde'],
      imageId: 'demo-salad',
      modelGlbUrl: null,
      modelUsdzUrl: null,
      version: 1,
      sortOrder: 2,
      isAvailable: true,
    },
  ],
  publishedAt: null,
};

export const DEMO_MENU = demoMenu;

export function localizedDemoMenu(locale: Locale): PublicMenu {
  const t = createTranslator(locale);
  return {
    ...demoMenu,
    restaurant: {
      ...demoMenu.restaurant,
      name: t(demoMenu.restaurant.name),
      tagline: t(demoMenu.restaurant.tagline),
    },
    categories: demoMenu.categories.map((category) => ({ ...category, name: t(category.name) })),
    dishes: demoMenu.dishes.map((dish) => ({
      ...dish,
      name: t(dish.name),
      description: t(dish.description),
      allergens: dish.allergens.map((allergen) => t(allergen)),
    })),
  };
}

export function dishImageUrl(dish: Pick<Dish, 'imageId'>): string | null {
  if (!dish.imageId) return null;
  const demoImages: Record<string, string> = {
    'demo-burger': '/images/burger.jpg',
    'demo-pasta': '/images/pasta.jpg',
    'demo-salad': '/images/salad.jpg',
  };
  return demoImages[dish.imageId] ?? `/api/media/${encodeURIComponent(dish.imageId)}`;
}
