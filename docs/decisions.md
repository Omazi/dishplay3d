# Implementation decisions

## Scope and starting evidence

The requested checkout `/home/omar/Desktop/Dish3d` was empty. The user chose a fresh build from the supplied 35-page PDF and Markdown brief. Existing local DishPlay copies, the private GitHub `DishPlay` repository, and the Sites **DishPlay · Scan Lab** project were left intact.

The supplied documents are product requirements and acceptance criteria. Statements in them about versions, demonstrated capability, or physical testing are not test evidence. The separate reference video and a new food-photo dataset were not supplied.

## Runtime and resource budget

- Node 24, Next.js 16.3.5, React 19.3, TypeScript 6.0.3; exact dependency versions and npm lockfile.
- Next route handlers serve the API on Vercel. A separate Nest server would need another deployment and is unnecessary for this initial catalogue.
- PostgreSQL in production; embedded PostgreSQL (PGlite) on disk locally. Production fails with a useful setup error if PostgreSQL is absent. It never silently saves restaurant data to an ephemeral Vercel filesystem.
- One build/test worker; bounded Node heap. `scripts/low-memory.mjs` supervises its own process tree and stops it when the sampled total exceeds 1.5 GiB or system available RAM drops below 256 MiB. Sampling is a guardrail, not a guarantee against every memory spike.
- No native SDK, reconstruction engine, container, or GPU model is installed or started automatically. Reconstruction is a separate opt-in process, never a web request.

## Truthful delivery

- Restaurant editing, photo publication, stable QR and customer menu are the usable first path.
- The illustrative menu is clearly marked; its photographs are not scans of a customer's food.
- Browser capture stores actual images. It does not draw fake spatial cubes, invented poses or random point clouds.
- GLB/USDZ viewing consumes existing reviewed files from an operator-controlled origin. Importing a URL does not validate the model's provenance or dimensions.
- Native ARKit/ARCore capture, Apple Object Capture, automatic background reconstruction and physical iPhone/Android acceptance remain distinct unfinished requirements.

## Data tradeoffs

Small JPEG/PNG/WebP photographs are kept in PostgreSQL for a bounded pilot with a 3 MiB per-file limit. This keeps authorization and publication coherent and stays below Vercel's 4.5 MB request limit. Large model files belong in object storage; the app stores their URLs. Move bulk original scan storage to private object storage before a broad rollout.

The first authentication adapter uses Node scrypt password hashes and opaque database-backed sessions. Hosted signup is opt-in. Password reset, email verification, invitations and role management need a subsequent account-management implementation; they are not simulated.

## Hosting and source

New private GitHub repository: `Omazi/dishplay3d`. Vercel project: `azomar/dishplay3d`. The Sites connector was used to inspect the existing project, while the explicit Vercel deployment request determines hosting. Sites building/hosting skill files were not available in this environment; no Sites project was replaced or published.

GitHub Actions verifies types, meaningful tests, dependency audit, build and browser workflows before deploying the exact checked-out commit. Vercel's automatic Git deployments are disabled to prevent bypassing these checks. CI credentials belong only in GitHub Actions secrets; runtime database credentials belong in Vercel environment variables.

## Primary references checked

- [Next memory guide](https://nextjs.org/docs/app/guides/memory-usage)
- [Vercel function limits](https://vercel.com/docs/functions/limitations)
- [Vercel with GitHub Actions](https://vercel.com/kb/guide/how-can-i-use-github-actions-with-vercel)
- [Vercel PostgreSQL integrations](https://vercel.com/docs/postgres)
- [Vercel token creation API](https://vercel.com/docs/rest-api/authentication/create-an-auth-token)
- [Unsplash license](https://unsplash.com/license)
