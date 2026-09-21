# DishPlay public storefront redesign

## Scope and evidence

The live site was opened in Chrome at 1440 × 900 and 390 × 844 before editing.
Actual screenshots are in `.data/landing-redesign/before/`. The previous hero pushed
food below the first mobile screen; photo relief, model tabs and explanation cards
felt like separate demonstrations. The existing public menu and its three model/AR
assets loaded. Native AR on a real phone was not tested.

The redesign changes only the marketing page and its components. Public menu behavior, authentication, dashboard, capture, API and reconstruction code
are preserved. The user subsequently requested a more realistic central 3D model;
the shared illustrative burger asset and its licence metadata were replaced in
both the storefront and demo menu.
No production deployment is authorized by this brief or performed for this redesign.

## Implemented narrative

1. Food-first graphite hero, licensed burger model poster and immediate real menu /
   signup links. No GLB or model-viewer import before scroll or deliberate interaction.
2. Scroll-driven real camera approach (110% to 99%) and modest orbit (38° desktop,
   24° mobile). Interactive control explicitly releases the camera from scroll.
   Horizontal dragging turns the model; vertical scrolling and browser zoom remain free.
3. The same viewer shrinks into an HTML menu card using actual localized demo dish
   data and price. Phone details form around it. Desktop QR points to the live demo;
   mobile gets a direct link. One shared viewer avoids duplicated models.
4. The phone dissolves into a clearly labelled illustrative restaurant table. The
   same burger changes position and viewing angle, with a contact shadow. AR starts
   only through the dedicated button, with capability checks and failure guidance.
5. The restaurant workflow explains preparation, capture, processing, editing and
   publication. The real existing web guide is pictured in FR/EN. Processing is not
   described as instant and no fake live reconstruction progress is added.

Native scrolling drives one GSAP ScrollTrigger. There is no wheel handler,
`preventDefault` on touch, smooth-scroll library, added WebGL engine or body lock.
Animation parameters are centralized and reversible. The viewer's render surface
stays fixed while CSS transforms change its screen footprint, avoiding a canvas
allocation on every scroll update. Model-viewer retains adaptive resolution.
The scene is removed off screen; observers/listeners/GSAP contexts are disposed.

## File map

- `src/app/[locale]/page.tsx`: server composition, navigation, actual menu data and QR.
- `src/components/landing/sections.tsx`: named server components for the seven
  editorial sections, including static fallbacks.
- `src/components/landing/story.tsx`: client scroll coordinator, one viewer,
  interaction ownership, AR launch, errors and resource cleanup.
- `src/components/landing/motion.ts`: timings, camera limits and responsive geometry.
- `src/components/landing/content.ts`: complete French/English editorial and controls.
- `src/app/launch.css`: scoped marketing styles; system type avoids adding font files.
- `public/landing-static.css`: no-JavaScript fallback, loaded only in `<noscript>`.
- `public/images/{burger-story,capture-guide-fr,capture-guide-en,restaurant-table}.webp`:
  documented media; see `docs/assets.md` for provenance and generation prompt.
- `tests/landing-motion.test.ts`, `tests/e2e/landing-story.spec.ts`: new targeted checks.
- Existing homepage presentation tests now exercise the requested narrative instead
  of removed photo tabs and fake price/publish controls. The three public menu AR
  asset tests and actual restaurant/capture workflows are retained.
- `scripts/audit-landing.mjs`: reproducible screenshot, accessibility, QR decoding
  and mobile laboratory metric collection. Audit tools are temporary, not app deps.

## Responsive and accessible behavior

Portrait mobile uses top-aligned copy, fewer camera degrees, a smaller menu phone,
a direct demo link, and no on-screen QR request. Heights below 720 px (including
landscape phones), reduced motion, JavaScript disabled or animation import failure
use a complete static reading flow with the same dish and real navigation.

Hidden animated chapters are inert. Chapter links jump directly to useful states
and focus their heading. Escape returns camera ownership to the narrative and
focus to chapter navigation. Static content and links are rendered on the server.
The poster remains during slow, unavailable or failed WebGL/model loading.

## Validation protocol

Production build, one test worker and one browser at a time, local isolated PGlite
for authenticated tests (`DATABASE_URL=''`). Existing memory supervisor limits task
RSS to 1,536 MiB and stops when system available memory falls below 256 MiB.
Builds and browsers run sequentially. Browser traces are disabled for local low-RAM
runs; screenshots and diagnostics are captured separately.

Metrics: Chrome, production build on localhost, viewport 360 × 780, DPR 2, cold cache,
4× CPU slowdown, 1.6 Mbps download / 0.75 Mbps upload / 150 ms emulated latency.
Three runs collect LCP and maximum CLS session via PerformanceObserver; no model
should download before scroll. These are laboratory measurements, not real-user
Core Web Vitals or performance guarantees for physical phones.

### Results from the final implementation

- `npm run check`: TypeScript and **24 unit tests passed**.
- `npm run build`: passed, peak sampled task RSS **709 MiB**.
- **26 Chromium browser scenarios passed**, run in separate small batches:
  seven narrative/camera/AR boundary/failure/slow-load/no-WebGL/no-JS checks;
  two responsive/reduced-motion checks; three public model/AR asset checks;
  two small-screen model-control checks; twelve account, capture, native pairing,
  publication, language and keyboard workflow checks. The FAQ test now targets its
  native `<summary>` (the decorative `+` is not part of the intended label).
- Viewports: 1440×900, 820×1180, 390×844, 360×780, 320×568 and 844×390, FR/EN.
  These are **emulated Chrome viewports, not physical device tests**.
- Full-page axe-core 4.13.0 checks at the four narrative states on desktop/tablet/
  mobile: **zero reported WCAG A/AA violations**. Background/image contrast has
  manual-review results and was visually inspected; this is not an accessibility
  certification. No horizontal overflow, JavaScript or console errors were found.
- Actual QR PNGs decoded with jsQR: FR and EN live demo destinations returned 200.
- Cold mobile measurements in Chrome 152.0.7977.64 under the protocol above:

  | Run | LCP | CLS | GLB requests before scrolling |
  | --- | --- | --- | --- |
  | 1 | 2.488 s | 0 | 0 |
  | 2 | 2.408 s | 0 | 0 |
  | 3 | 2.420 s | 0 | 0 |

  Initial transferred resources: 442,883 bytes in each run. The median LCP is
  2.420 s; all three runs meet the project targets, with little LCP margin.
- Memory protection stopped two combined/heavier test attempts at the configured
  limit. Reducing the burger's normal maps and testing each AR dish in a fresh
  browser kept final scenario peaks at or below **1,527 MiB**. No user applications
  were stopped. The final screenshot/metric audit peaked at **1,506 MiB**.
- No lint script is configured. Prettier checks on changed code and `git diff
  --check` pass. Existing backend/iOS code and deployment configuration are unchanged.

Evidence is local in `.data/landing-redesign/`: `before/`, `verification/` (actual
screenshots and machine-readable report), test/build logs and `scroll/`.
The actual 390×844 Chrome scroll recording `scroll/walkthrough.mp4` covers 17.65 s
forward and backward (41 sampled frames); frames from the volume, phone, table
transition and reverse path were inspected. Headless software rendering and CDP
sampling make this a visual continuity record, not a phone frame-rate benchmark. Initial
screenshots wait for the real poster's decode so an early compositor frame is not
mistaken for a missing asset. The local production preview at `http://127.0.0.1:3000`
was opened and exercised. Vercel preview has no environment variables configured;
no remote preview or production deployment is claimed.

WebKit/Safari and physical iPhone/Android AR were not available in this environment.
The frontend tests exercise the real asset loading and the AR launch boundary,
then mock the OS launch: they do not establish real camera placement or tracking.

## Media upgrade and remaining limits

The user explicitly chose a more realistic 3D model over a photo-first direction.
The old glossy, low-detail burger is replaced by Ehsan Abbasi's “Back Yard Burgers -
Classic Burger”, commercially reusable under CC BY-SA 4.0. Its textured crust,
irregular bread, layered filling and 46,209 faces improve the central visual.
It is a modeled illustration, not a verified photogrammetry scan or the user's dish.
The source and licence were checked against current Sketchfab API metadata and
embedded credits. The source GLB, browser rendering and exported USDZ were examined.

Color texture resolution stays at 1024px; normal maps use 512px to reduce downloads
and memory. No geometry simplification was applied. GLB: 3,671,948 bytes, loaded
lazily; matching USDZ: 6,154,818 bytes, requested only by deliberate AR launch.
Both were reimported and validated at an illustrative 16cm footprint, with readable
textures and the bottom on the tabletop. See `docs/demo-ar-validation.json` for
actual dimensions and hashes and `public/models/LICENSE.txt` for derivative terms.
Only the central burger changed; pasta and salad retain their existing illustrations.

A restaurant-owned scan with calibrated dimensions remains the next step for an
accurate representation of the actual dish. The background is generated staging,
not a real customer's restaurant or camera. Stock photos and demo models are
explicitly distinguished in the FAQ.

Automated AR tests validate assets, explicit launch and fallback boundaries. They
cannot validate placement, tracking, real dimensions or Quick Look on an iPhone.
No native iOS capture/reconstruction improvements are included in this frontend task.
