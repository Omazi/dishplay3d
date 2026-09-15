import type { Metadata } from 'next';
import './globals.css';

export const metadata: Metadata = {
  title: {
    default: 'DishPlay — Donnez une nouvelle dimension à votre carte',
    template: '%s · DishPlay',
  },
  description:
    'Créez votre carte, photographiez vos plats et partagez un menu accessible depuis un simple QR code.',
  icons: { icon: '/favicon.svg' },
};

export default function RootLayout({ children }: Readonly<{ children: React.ReactNode }>) {
  return (
    <html lang="fr">
      <body>
        <a className="skip-link" href="#main">
          Aller au contenu
        </a>
        {children}
      </body>
    </html>
  );
}
