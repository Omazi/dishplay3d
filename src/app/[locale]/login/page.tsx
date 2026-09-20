import { AuthForm } from '@/components/auth-form';
import { localizedMetadata } from '@/lib/i18n/metadata';
export const generateMetadata = localizedMetadata('Se connecter', true);
export default function LoginPage() {
  return <AuthForm />;
}
