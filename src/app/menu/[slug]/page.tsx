import { notFound } from 'next/navigation';
import { MenuView } from '@/components/menu-view';
import { getPublishedMenu } from '@/lib/server/catalogue';

export const dynamic = 'force-dynamic';
export default async function RestaurantMenuPage({
  params,
}: {
  params: Promise<{ slug: string }>;
}) {
  const { slug } = await params;
  const menu = await getPublishedMenu(slug);
  if (!menu) notFound();
  return <MenuView menu={menu} />;
}
