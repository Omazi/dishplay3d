# Operations

## Start, stop and data

Use Node 24 and `npm ci`. Keep one server running. Ctrl+C stops the development server and its supervised child processes. The app does not launch a reconstruction worker.

Local data lives in `.data/dishplay` (or `PGLITE_DATA_DIR`). Stop the local server before copying this directory for backup. Restore only while stopped, preserving the original directory until the restored data has been checked. Do not run multiple Node processes against the same local embedded database directory.

Production uses PostgreSQL through `DATABASE_URL`. Keep its credentials in the hosting secret store. Use the provider's backups and a periodic encrypted `pg_dump` using a direct database connection. Restore into a separate database, run the app against it, and verify account access, private media, draft editing and a published menu before cutover. A backup has not been validated until a restore succeeds. No production restore was executed during this delivery.

## Retention and limits

For this pilot, original captures remain in the browser until explicitly removed or evicted by the browser. Export a ZIP before clearing browser storage. Local persistence is not a backup. Private uploaded images remain in the database; there is no automatic deletion job. Operators must establish a retention schedule and export policy before a live restaurant rollout.

Published snapshots and their immutable photo URLs are retained indefinitely so an already-open menu keeps working after republication. Once published, an image remains public until an operator explicitly retires it and handles CDN invalidation; removing it from a newer draft does not make it private again.

Images have a 3 MiB limit. The server validates MIME signatures and membership; it does not treat file extensions as proof. Image dimensions and total storage are bounded in the pilot adapters where specified. Review storage quotas before increasing capture limits. Large 3D models must be hosted on a controlled static asset origin with CORS, correct MIME types and immutable names.

## Publication and recovery

Publishing takes a coherent snapshot in a database transaction. Editing a draft does not mutate a published snapshot. Version conflicts return HTTP 409 so a second editor cannot silently overwrite a more recent save. The stable restaurant slug is retained after price/name changes.

Keep the last good model URL until a new model has been reviewed. A failed reconstruction request does not erase it. Model import validates URL policy, not geometric accuracy. Review textures, orientation and metric scale on actual iOS and Android viewers before publishing.

## Credentials and account access

Passwords are hashed with scrypt and sessions are random opaque tokens whose hashes are stored in PostgreSQL. Production cookies use HttpOnly, SameSite and Secure. Mutation endpoints check Origin. Hosted signup is an explicit environment setting. This pilot has no password reset, email verification or member invitation UI; keep access to the database/operator account for recovery.

Deployment uses the installed Vercel GitHub integration and the workflow’s short-lived built-in repository token. No account-wide Vercel credential is stored in GitHub. Keep the `production` branch managed by the deployment workflow and review changes to `.github/workflows/ci-cd.yml`.

## Incident checks

1. Check GitHub Actions for the last successful verified commit.
2. Check Vercel deployment status and application logs; logs must not include credentials or image contents.
3. Check PostgreSQL connection availability and quota. A 503 setup/connection error must not be worked around using ephemeral local storage.
4. Run `node scripts/smoke.mjs https://your-production-domain`.
5. If needed, use Vercel rollback to the last known good deployment. A code rollback does not roll back business data or schema; review migration compatibility separately.
