# DishPlay

Restaurant photo menus, guided photo capture, published menu snapshots and permanent QR links. Built from the supplied DishPlay dossier in a fresh checkout. French UI; Next.js, React and PostgreSQL.

**This is a web pilot.** Native Object Capture/ARCore apps and reconstruction of a real dish have not been validated. Browser capture records real images; it does not fabricate tracking, points or 3D results. The separate reconstruction CLI requires external engines and explicit execution.

## Run locally (8 GB laptop)

```bash
nvm use
npm ci
npm run dev
```

Open `http://localhost:3000`. Local development stores accounts and catalogue data in `.data/dishplay`. No Docker, cloud database or GPU is needed. Create an account at `/signup` using a password of at least 12 characters. Data and secrets are excluded from Git.

Only run one development server, build or browser test at a time. Development and build commands use one worker, bounded JavaScript heaps and a process memory guard. If it stops a task, use GitHub CI or close unused applications. No script stops unrelated applications.

## Product paths

- `/`: product introduction.
- `/menu/demo`: explicitly labelled illustrative photo menu; no account or camera needed.
- `/signup`, `/login`, `/dashboard`: restaurant account, draft catalogue, photos, categories, preview, publish, QR.
- `/menu/<stable-slug>`: last published snapshot. Editing a draft or price does not reconstruct anything or change the QR.
- `/capture`: real browser camera or photo import, saved locally and exportable. Requires HTTPS outside localhost.

3D viewing loads only after selecting a model's 3D view. Imported GLB/USDZ assets must be hosted on `MEDIA_PUBLIC_ORIGIN`; the owner must verify their source and quality. AR availability depends on the device/browser. An error leaves the photo accessible.

## Checks

```bash
npm run check
python3 -m unittest discover -s worker/tests
npm run build
npx playwright install chromium
npm run test:e2e
npm run worker:doctor
```

The browser test runner starts a local production server with an isolated database. A system Chrome can be used without downloading a browser:

```bash
PLAYWRIGHT_CHROMIUM_EXECUTABLE_PATH=/opt/google/chrome/chrome npm run test:e2e
```

See [acceptance and evidence](docs/acceptance.md) for outcomes and limitations. A successful build is not physical iOS/Android validation.

## Vercel and CI/CD

The `Verify and deploy` workflow runs on pull requests and `main`. It checks types, tests, dependency vulnerabilities, production build and browser workflows. Only a successful `main` run deploys to Vercel. Pull requests never receive deployment secrets. Stale pull-request runs are cancelled; production runs are serialized to avoid overlapping deployments.

The Vercel project is connected to `Omazi/dishplay3d`, with `production` as its production branch. After verification, Actions creates a deployment commit containing the tested application source and `public/deployment.json`, excluding `.github` workflow files. This avoids requiring workflow-write permissions from the built-in repository token. Vercel builds that commit; Actions checks both its live `/api/health` commit and the recorded tested source commit before checking public pages. No additional Vercel token is required.

Keep `production` managed by the workflow. Deployment commits advance by fast-forward, and the release script rejects source commits older than the last deployed source. Main/PR pushes do not deploy directly. To use another Vercel project, connect its Git repository, select `production` as the production branch and update the workflow's deployment URL.

Production environment:

| Variable              | Purpose                                                                                 |
| --------------------- | --------------------------------------------------------------------------------------- |
| `DATABASE_URL`        | Durable PostgreSQL connection, e.g. a connected Neon database                           |
| `ALLOW_SIGNUP`        | Set `true` to permit pilot restaurant registration; disable after onboarding if desired |
| `NEXT_PUBLIC_APP_URL` | Canonical HTTPS origin (optional)                                                       |
| `MEDIA_PUBLIC_ORIGIN` | Controlled HTTPS model asset origin (optional)                                          |

Copy `.env.example` for local overrides; do not commit populated environment files. Migrations run transactionally at first database connection. Vercel intentionally has no fallback to an ephemeral file database.

`vercel.json` permits automatic Git deployments only from `production`. Initial manual deployment used `vercel deploy --prod`; further changes go through the verification workflow.

## Operations and remaining scope

- [Architecture decisions and official references](docs/decisions.md)
- [Operations and backup](docs/operations.md)
- [Reconstruction CLI and licenses](docs/reconstruction.md)
- [Native capture apps and acceptance](docs/native-capture.md)
- [Durable reconstruction queue](docs/worker-queue.md)
- [Illustrative asset sources](docs/assets.md)

No paid 3D API, model inference key or GPU service is used. Hosting/storage providers have their own quotas and account terms; no paid plan is selected automatically.
