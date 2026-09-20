# Acceptance record

This record distinguishes implemented functionality from executed checks and the dossier's final product targets. Never infer hardware results from browser emulation.

## Web checks

- [x] Locked installation, TypeScript check, domain tests, build.
- [x] Signup/login/logout with persisted accounts.
- [x] Two restaurants cannot read/edit each other's drafts or private media.
- [x] Create/edit a dish and reject a stale edit.
- [x] Draft changes remain private until atomic publication.
- [x] Price changes preserve restaurant URL and do not enqueue reconstruction.
- [x] Photo upload is bounded and private until publication.
- [x] Public customer menu works without login or camera permission.
- [x] 3D code/model requests occur only after the customer's 3D action.
- [x] Mobile menu, accessible labels/focus, camera error recovery.
- [x] GitHub CI and Vercel deployment checked independently; latest run linked below.

## Not yet physically verified

| Requirement                                | Missing evidence                                                       |
| ------------------------------------------ | ---------------------------------------------------------------------- |
| iPhone native capture                      | Signed installation, supported physical phone and real capture test    |
| Android native tracking/points             | Installed APK on a connected physical ARCore device                    |
| True textured food reconstruction          | New calibrated food dataset and installed supported engines            |
| Model scale/colour/hidden-surface fidelity | Measured object, held-out images and GLB/USDZ review on both platforms |
| 16/20 food reconstruction yield            | Twenty-dish pilot, at most two captures each                           |
| Performance p75 thresholds                 | Real-user field samples; local browser checks are insufficient         |
| Dense live point preview parity            | Sensor-specific implementation and hardware measurements               |

Suggested next physical test: immobile matte/textured dish, three passes at differing heights, held-out control images, known plate diameter. Record phone/OS, retained views and resolution, engine versions, wall time and peak RSS, failures, output hashes and reviewers. Start with a reduced worker batch on 8 GB RAM. Do not turn over food or invent occluded surfaces.

## Executed evidence (2026-09-15 and 2026-09-19)

- Locked npm install, TypeScript checks, 6 domain tests, 5 queue state tests, 16 Python worker/lifetime tests and production build passed.
- Initial production build peaked at **703 MiB sampled aggregate RSS** for the supervised task. A later complete build measured **583 MiB**. These are measured builds, not a universal bound.
- Chromium browser flows passed: mobile public menu, authentication/tenant isolation/snapshot API, real lazy model viewer with a labelled technical test fixture, camera-denial/import/persistence/original-export recovery, restaurant UI photo/edit/preview/publish/stable QR download, and linked capture transfer/finalization/reload. Six browser scenarios now pass. Cold embedded-database and software-WebGL checks allow bounded 30-second waits on a busy development laptop.
- GitHub independently verifies installation, types, tests, audit, build and all browser scenarios. [Latest CI/CD runs](https://github.com/Omazi/dishplay3d/actions/workflows/ci-cd.yml). Deployment uses the connected Vercel Git integration and an app-only production branch; no Vercel CI token is required.
- Initial Vercel deployment succeeded at https://dishplay3d.vercel.app. Live `/`, `/menu/demo`, `/capture`, `/login` and `/api/menus/demo` returned success.
- Deployed screenshots: [desktop landing](screenshots/landing-desktop.png), [mobile public menu](screenshots/menu-mobile.png). No real-user p75, actual AR device, food reconstruction, model scale or twenty-dish yield result is claimed.

## Remaining product gaps

Native dish pairing/upload, iOS ARKit spatial fallback, web video sampling, automatic reviewed model asset publication, password recovery/member invitations and physical acceptance still require work. The native and worker guides describe available implementation and explicit limits.

## Native build evidence

- [iOS unsigned compile passed](https://github.com/Omazi/dishplay3d/actions/runs/35035015993): Xcode 16.4, iOS 18.5 SDK, source `c2aadc6`. Requires Apple signing before installation.
- [Android debug APK and lint passed](https://github.com/Omazi/dishplay3d/actions/runs/35486507579): source `55ff169`. APK available in the workflow artifact.
- Builds ran on hosted runners; no mobile SDK or reconstruction engine was installed on the 8 GB laptop.

## Cloud account activation

After the account owner accepted the provider terms, Neon `dishplay3d-db` was provisioned on the explicit `free_v3` plan in `iad1` and linked only to Vercel production. The existing verified application was redeployed with the database variables. Restaurant registration is active at [the live signup page](https://dishplay3d.vercel.app/signup).

Live verification on 2026-09-19 America/New_York (2026-09-20 03:46 UTC), source `fa7e227`, production commit `b733e425`:

- Browser signup, secure HttpOnly/SameSite session, logout and subsequent login passed against real PostgreSQL.
- Browser category, dish and photo creation, preview, publication and SVG QR download passed.
- Unpublished menus/photos stayed private; a second restaurant could neither read the private photo nor edit the first restaurant's dish.
- Stale edits returned 409. A draft price change left the published snapshot untouched until republication, preserved the menu URL and created no reconstruction job.
- The published mobile menu loaded without authentication, showed the updated price and had no page errors or horizontal overflow.
- Both temporary test accounts and their restaurant data were removed in a scoped database transaction; cleanup verified that neither account remained.
- One local browser session ran under the memory guard, with **1,316 MiB sampled aggregate task RSS**. No local server, mobile SDK or reconstruction engine ran alongside it.

Local and CI account/catalogue/publication checks continue to use isolated databases. The production site has no fallback to ephemeral hosting files.
