import { MenuView } from '@/components/menu-view';
import { demoMenu } from '@/lib/demo';
import { localizedMetadata } from '@/lib/i18n/metadata';
export const generateMetadata = localizedMetadata('La carte de démonstration');
export default function DemoMenu() {
  return <MenuView menu={demoMenu} />;
}
