import { Dashboard } from '@/components/dashboard';
import { localizedMetadata } from '@/lib/i18n/metadata';
export const generateMetadata = localizedMetadata('Mon espace restaurant', true);
export default function DashboardPage() {
  return <Dashboard />;
}
