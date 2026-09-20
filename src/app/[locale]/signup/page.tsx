import { AuthForm } from '@/components/auth-form';
import { localizedMetadata } from '@/lib/i18n/metadata';
export const generateMetadata = localizedMetadata('Créer un compte', true);
export default function SignupPage() {
  return <AuthForm signup />;
}
