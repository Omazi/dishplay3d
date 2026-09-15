import { Suspense } from 'react';
import { Capture } from '@/components/capture';
export const metadata = { title: 'Capture photo guidée', robots: { index: false, follow: false } };
export default function CapturePage() {
  return (
    <Suspense
      fallback={
        <main id="main" className="standalone-state">
          Ouverture de l’atelier…
        </main>
      }
    >
      <Capture />
    </Suspense>
  );
}
