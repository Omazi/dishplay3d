export interface Restaurant {
  id: string;
  name: string;
  slug: string;
  tagline: string;
  currency: string;
  version: number;
}

export interface Category {
  id: string;
  name: string;
  sortOrder: number;
}

export interface Dish {
  id: string;
  categoryId: string | null;
  name: string;
  description: string;
  priceCents: number;
  allergens: string[];
  imageId: string | null;
  modelGlbUrl: string | null;
  modelUsdzUrl: string | null;
  version: number;
  sortOrder: number;
  isAvailable: boolean;
}

export interface PublicMenu {
  restaurant: Restaurant;
  categories: Category[];
  dishes: Dish[];
  publishedAt: string | null;
  isDemo?: boolean;
}

export type RestaurantWorkspace = PublicMenu;

export interface ApiError {
  error: string;
  code?: string;
}
