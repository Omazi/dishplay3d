import type { Locale } from '@/lib/i18n';
const fr = {
  navDemo: 'Le menu démo',
  navCreate: 'Créer mon menu',
  login: 'Connexion',
  how: 'Comment ça marche',
  eyebrow: 'LA CARTE PREND UNE NOUVELLE DIMENSION',
  hero: ['Vos plats.', 'Sous un nouveau regard.'],
  intro:
    'Un menu à ouvrir par QR code. Des photos qui donnent envie. Et des plats à explorer en 3D, lorsque disponible.',
  discover: 'Découvrir un plat',
  scroll: 'Faites défiler. Changez de perspective.',
  details: ['Chaque détail', 'donne envie.'],
  detailText: 'Approchez. Tournez autour. Découvrez le volume, avant la première bouchée.',
  explore: 'Explorer en 3D',
  back: 'Revenir au récit',
  loading: 'Préparation de la vue 3D…',
  error: 'La 3D est indisponible. L’aperçu reste visible.',
  retry: 'Réessayer la 3D',
  controls:
    'Glissez horizontalement pour tourner. Le défilement vertical reste libre. Échap pour revenir.',
  menuTitle: ['Toute cette expérience.', 'Dans un simple menu.'],
  menuText:
    'Un nom. Une envie. Toutes les informations à portée de main, sur le téléphone de vos clients.',
  openMenu: 'Ouvrir le menu démo',
  qr: 'Scannez pour ouvrir le vrai menu.',
  menuCaption: 'Extrait du menu de démonstration · vue 3D',
  tableTitle: ['Avant de choisir.', 'Voyez-le devant vous.'],
  tableText:
    'Sur un appareil compatible, ouvrez le modèle en réalité augmentée et placez-le sur votre table.',
  ar: 'Voir sur ma table',
  arFallback:
    'Ouvrez cette page dans Safari sur iPhone ou Chrome sur Android compatible. Vous pouvez aussi explorer le menu en 3D.',
  arError: 'L’AR n’a pas pu démarrer. La vue 3D et le menu restent accessibles.',
  tableCaption: 'Mise en scène illustrative · aucune caméra en direct · taille indicative',
  illustrative: 'Modèle illustratif',
  poster: 'Aperçu du modèle illustratif du burger',
  creatorEyebrow: 'DE VOTRE CUISINE À LEUR ÉCRAN',
  creatorTitle: ['Vous préparez le plat.', 'Donnez-lui une nouvelle présence.'],
  creatorText:
    'Commencez avec vos photos. Ajoutez un modèle 3D lorsque votre capture a été traitée et vérifiée.',
  capture: 'Découvrir la capture guidée',
  steps: [
    ['Préparez', 'Un plat immobile, une lumière régulière et de la place pour tourner autour.'],
    [
      'Capturez',
      'Suivez le parcours guidé dans l’app de capture. Les possibilités dépendent de votre appareil.',
    ],
    [
      'Laissez traiter',
      'Envoyez les vues au service de reconstruction configuré. Le traitement prend du temps ; vérifiez le résultat.',
    ],
    [
      'Composez',
      'Renseignez le nom, le prix, la description et les allergènes. Ajoutez vos photos et votre modèle disponible.',
    ],
    ['Publiez', 'Publiez le menu, puis partagez son lien ou son QR code avec vos clients.'],
  ],
  workflowCaption:
    'Le parcours de création · la 3D nécessite une capture et un traitement séparés.',
  faqTitle: 'Quelques détails, avant de passer à table.',
  faqs: [
    [
      'Mes clients doivent-ils installer une app ?',
      'Le menu s’ouvre dans leur navigateur. L’affichage AR dépend de la compatibilité de leur téléphone.',
    ],
    [
      'Ai-je besoin d’un modèle 3D pour commencer ?',
      'Non. Vous pouvez publier une carte avec des photos et ses informations, puis ajouter la 3D quand elle est prête.',
    ],
    [
      'La reconstruction est-elle instantanée ?',
      'Non. La capture doit être envoyée et traitée par le service configuré. La qualité des vues, le plat et le matériel influencent le résultat.',
    ],
    [
      'Le burger présenté est-il un vrai scan DishPlay ?',
      'Il s’agit d’un modèle illustratif sous licence, utilisé dans le menu de démonstration. Il n’est pas la reconstruction de la photographie du burger. La table est une mise en scène.',
    ],
  ],
  end: ['Votre cuisine mérite', 'd’être découverte.'],
  endText: 'Commencez par votre menu. Donnez envie de choisir.',
  credits: 'Burger : Ehsan Abbasi. Modèle optimisé et formats adaptés.',
  chapterLabels: ['Le plat', 'Le volume', 'Le menu', 'La table'],
  chaptersLabel: 'Étapes de la présentation',
};
const en: typeof fr = {
  navDemo: 'Demo menu',
  navCreate: 'Create my menu',
  login: 'Sign in',
  how: 'How it works',
  eyebrow: 'A NEW DIMENSION FOR YOUR MENU',
  hero: ['Your dishes.', 'A new perspective.'],
  intro:
    'A menu opened with a QR code. Photos that whet the appetite. And dishes to explore in 3D, when available.',
  discover: 'Discover a dish',
  scroll: 'Scroll. Find a new perspective.',
  details: ['Every detail', 'invites a taste.'],
  detailText: 'Move closer. Look around. Discover the shape, before the first bite.',
  explore: 'Explore in 3D',
  back: 'Back to the story',
  loading: 'Preparing the 3D view…',
  error: '3D is unavailable. The preview remains visible.',
  retry: 'Retry 3D',
  controls: 'Drag horizontally to turn. Scroll vertically as usual. Escape to return.',
  menuTitle: ['The whole experience.', 'One simple menu.'],
  menuText: 'A name. An appetite. Every detail within reach, right on your guests’ phones.',
  openMenu: 'Open the demo menu',
  qr: 'Scan to open the real menu.',
  menuCaption: 'From the demo menu · 3D view',
  tableTitle: ['Before you choose.', 'See it in front of you.'],
  tableText:
    'On a compatible device, open the model in augmented reality and place it on your table.',
  ar: 'View on my table',
  arFallback:
    'Open this page in Safari on iPhone or Chrome on a compatible Android. You can also explore the menu in 3D.',
  arError: 'AR could not start. The 3D view and menu remain available.',
  tableCaption: 'Illustrative scene · not a live camera · approximate size',
  illustrative: 'Illustrative model',
  poster: 'Preview of the illustrative burger model',
  creatorEyebrow: 'FROM YOUR KITCHEN TO THEIR SCREEN',
  creatorTitle: ['You prepare the dish.', 'Give it a new presence.'],
  creatorText:
    'Start with your photos. Add a 3D model once your capture has been processed and checked.',
  capture: 'Discover guided capture',
  steps: [
    ['Prepare', 'A still dish, even light and enough room to move around it.'],
    [
      'Capture',
      'Follow the guided workflow in the capture app. Available features depend on your device.',
    ],
    [
      'Let it process',
      'Send the views to your configured reconstruction service. Processing takes time; check the result.',
    ],
    [
      'Compose',
      'Add the name, price, description and allergens. Include your photos and available model.',
    ],
    ['Publish', 'Publish the menu, then share its link or QR code with your guests.'],
  ],
  workflowCaption: 'The creation workflow · 3D requires separate capture and processing.',
  faqTitle: 'A few details, before you take a seat.',
  faqs: [
    [
      'Do my guests need to install an app?',
      'The menu opens in their browser. AR availability depends on their phone’s compatibility.',
    ],
    [
      'Do I need a 3D model to get started?',
      'No. Publish your menu with photos and details, then add 3D when it is ready.',
    ],
    [
      'Is reconstruction instant?',
      'No. A capture must be uploaded and processed by the configured service. The views, dish and hardware affect the result.',
    ],
    [
      'Is this burger a real DishPlay scan?',
      'It is a licensed illustrative model used in the demo menu, not a reconstruction of the burger photograph. The table is an illustrative scene.',
    ],
  ],
  end: ['Your food deserves', 'to be discovered.'],
  endText: 'Start with your menu. Give guests a taste of what’s to come.',
  credits: 'Burger: Ehsan Abbasi. Optimized model and adapted formats.',
  chapterLabels: ['The dish', 'The volume', 'The menu', 'The table'],
  chaptersLabel: 'Presentation chapters',
};
export type LandingCopy = typeof fr;
export const landingCopy = (locale: Locale) => (locale === 'en' ? en : fr);
