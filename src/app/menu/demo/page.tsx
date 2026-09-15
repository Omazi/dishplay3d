import { MenuView } from '@/components/menu-view';
import { demoMenu } from '@/lib/demo';
export const metadata = { title: 'La carte de démonstration' };
export default function DemoMenu() {
  return <MenuView menu={demoMenu} />;
}
