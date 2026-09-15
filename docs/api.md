# Implemented HTTP API

This document describes the application currently implemented in `src/app/api`. The machine-readable contract is [openapi.json](./openapi.json). Native capture, an HTTP worker bridge, password reset, invitations and billing are not implemented.

## Access, requests and errors

- All paths below are relative to the application origin. The browser UI uses same-origin requests.
- Every mutation (`POST`, `PATCH`, `DELETE`) requires an `Origin` header exactly matching the request destination origin or the configured `NEXT_PUBLIC_APP_URL` origin. The destination uses the validated `Host` header and request URL protocol; this handles Next.js normalizing a local request hostname to `localhost`. A missing or different origin returns `403 ORIGIN_REJECTED`, including for signup/login. Command-line clients must send this header themselves. No cross-origin CORS integration is provided.
- JSON request bodies must use `Content-Type: application/json` and contain an object. The maximum parsed JSON body is 64 KiB. Image endpoints accept raw binary bodies, **not multipart form data**.
- Authentication uses the `dishplay_session` HttpOnly, SameSite=Lax cookie. Sessions expire after seven days and are stored by token hash. Cookies are Secure on Vercel and in production, except an explicitly configured local production run with `ALLOW_LOCAL_DATABASE=true` outside Vercel. Save and resend the cookie when testing with a command-line client.
- Private requests resolve the user and restaurant membership on the server. The current pilot creates one restaurant per account. Supplying another restaurant's dish, capture or private image ID never grants access.
- Registration requires a 12–128-character password. Login accepts the previously stored password, including intentional leading/trailing spaces. Email addresses are trimmed and lowercased. Registration is enabled locally in development; hosted/production registration requires `ALLOW_SIGNUP=true`.
- Persistent auth limits use 15-minute windows: signup 5 attempts/IP; login 50 attempts/IP, 10 attempts/IP+email and 30 attempts/email. Buckets older than one day are removed during auth attempts. The deployment proxy must provide trustworthy `X-Forwarded-For` values.
- Vercel requires `DATABASE_URL`; there is no ephemeral database fallback. Local development uses persistent PGlite in `.data/dishplay`, overridable with `PGLITE_DATA_DIR`. Production local PGlite additionally requires `ALLOW_LOCAL_DATABASE=true` and cannot be enabled on Vercel. Database initialization/connection failures return a useful `503 DATABASE_UNAVAILABLE` response.
- JSON responses use `Cache-Control: no-store`. Published immutable images use the public cache policy described below. API responses include `X-Content-Type-Options: nosniff` on success.

Errors have the shape:

```json
{ "error": "A readable explanation.", "code": "VERSION_CONFLICT" }
```

| Status | Meaning / representative codes                                                                                                                                                      |
| ------ | ----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| 400    | Validation failed, invalid foreign reference, bad image/checksum; `INVALID_REQUEST`, `CHECKSUM_MISMATCH`                                                                            |
| 401    | Authentication required or incorrect credentials; `UNAUTHENTICATED`, `INVALID_CREDENTIALS`                                                                                          |
| 403    | Rejected origin or hosted registration disabled; `ORIGIN_REJECTED`, `SIGNUP_DISABLED`                                                                                               |
| 404    | Missing or inaccessible resource; `NOT_FOUND`                                                                                                                                       |
| 409    | Stale edit, closed capture, saved capture protection, existing email; `VERSION_CONFLICT`, `SCAN_CLOSED`, `SCAN_FINALIZED`, `SCAN_CANCELLED`, `HAS_SAVED_CAPTURES`, `ACCOUNT_EXISTS` |
| 413    | Request, image dimensions or restaurant media quota exceeded                                                                                                                        |
| 415    | A JSON endpoint received a different content type                                                                                                                                   |
| 429    | Auth attempts exceeded; `RATE_LIMITED`                                                                                                                                              |
| 500    | Unexpected operation failure; `INTERNAL_ERROR`                                                                                                                                      |
| 503    | Database unavailable or worker integration absent; `DATABASE_UNAVAILABLE`, `WORKER_UNAVAILABLE`                                                                                     |

## Data shapes

`Restaurant`:

```json
{
  "id": "opaque-id",
  "name": "Maison",
  "slug": "maison-a1b2c3d4",
  "tagline": "Seasonal food",
  "currency": "EUR",
  "version": 3
}
```

The slug is generated once at signup and is not editable. Supported currencies are `EUR`, `USD` and `CAD`.

`Category`:

```json
{ "id": "opaque-id", "name": "Mains", "sortOrder": 0 }
```

`Dish`:

```json
{
  "id": "opaque-id",
  "categoryId": null,
  "name": "Roasted vegetables",
  "description": "Vegetables and herbs",
  "priceCents": 1850,
  "allergens": ["Milk"],
  "imageId": null,
  "modelGlbUrl": null,
  "modelUsdzUrl": null,
  "version": 1,
  "sortOrder": 0,
  "isAvailable": true
}
```

`priceCents` is an integer in the restaurant currency's minor units, from 0 to 10,000,000. Strings, negative amounts and fractions are rejected. Dish names are required, at most 120 characters; descriptions are at most 2,000 characters. Allergens are owner-declared labels: up to 30 unique trimmed strings of at most 80 characters. `sortOrder` is an integer from 0 to 100,000.

`PublicMenu` and the authenticated workspace share the shape:

```json
{ "restaurant": {}, "categories": [], "dishes": [], "publishedAt": null }
```

`publishedAt` is an ISO timestamp or `null`; the independent fixture additionally has `isDemo: true`. The workspace contains drafts, including unavailable dishes. A published menu contains only the available dishes at publication time.

## Authentication

| Method and path         | Body                              | Success                                                              |
| ----------------------- | --------------------------------- | -------------------------------------------------------------------- |
| `POST /api/auth/signup` | `{email,password,restaurantName}` | `201 {user:{id,email},restaurantId}` and session cookie              |
| `POST /api/auth/login`  | `{email,password}`                | `200 {user:{id,email},restaurantId}` and session cookie              |
| `POST /api/auth/logout` | No body required                  | `200 {ok:true}`; invalidates this session and clears its cookie      |
| `GET /api/auth/me`      | —                                 | `200 {user:{id,email},restaurantId}`; anonymous requests receive 401 |

## Restaurant and catalogue

These endpoints require authentication.

| Method and path               | Body                                    | Success                                                    |
| ----------------------------- | --------------------------------------- | ---------------------------------------------------------- |
| `GET /api/restaurant`         | —                                       | `200 PublicMenu` containing the coherent current workspace |
| `PATCH /api/restaurant`       | `{version,name?,tagline?,currency?}`    | `200 {restaurant}`                                         |
| `POST /api/categories`        | `{name,sortOrder?}`                     | `201 {category}`                                           |
| `PATCH /api/categories/{id}`  | `{name?,sortOrder?}`                    | `200 {category}`                                           |
| `DELETE /api/categories/{id}` | No body required                        | `200 {ok:true}`                                            |
| `GET /api/dishes`             | —                                       | `200 {dishes:[]}`                                          |
| `POST /api/dishes`            | Writable `Dish` fields; `name` required | `201 {dish}`                                               |
| `PATCH /api/dishes/{id}`      | `{version,...changedWritableFields}`    | `200 {dish}`                                               |
| `DELETE /api/dishes/{id}`     | `{version}`                             | `200 {ok:true}`                                            |

Dish creation defaults to price 0, empty description/allergens, available, sort order 0, and null category/image/models. There are at most 500 dishes per restaurant. Category names are required, at most 100 characters; restaurant names are required, at most 120 characters; taglines are at most 240 characters.

The client must send the last loaded dish/restaurant `version` for versioned edits and deletion. A stale version returns 409 without overwriting newer work. Catalogue mutations increment the restaurant version; reload `GET /api/restaurant` before publishing. Deleting a category moves its dishes to no category and increments their versions. Category edits themselves do not have per-category optimistic version checks.

Deleting a dish with saved captures returns `409 HAS_SAVED_CAPTURES`. Mark the dish unavailable to preserve its capture history and originals. Changes to texts, prices and availability never create a reconstruction job or replace its existing model.

### Model references

Optional model fields accept null to remove a reference, or a URL at the exact operator-controlled `MEDIA_PUBLIC_ORIGIN`. URLs must be HTTPS, have a `.glb`/`.usdz` pathname, and contain no credentials, query string or fragment. An optional USDZ requires a GLB. Changes to unrelated fields retain prior model URLs even if the operator later changes the allowed origin.

The application does not fetch arbitrary import URLs, reconstruct these models, verify their geometry or infer their source photographs. These are owner-imported artifacts. Previous model references are archived when an existing reference is changed. No revision-restore endpoint is currently exposed.

## Publishing and public reads

| Method and path         | Access/body                                   | Success                                          |
| ----------------------- | --------------------------------------------- | ------------------------------------------------ |
| `POST /api/publish`     | Authenticated, `{version:restaurant.version}` | `200 {slug,url,publishedAt,version}`             |
| `GET /api/menus/{slug}` | Public                                        | `200 PublicMenu`; 404 before initial publication |

At least one available dish is required. Publication locks the restaurant, verifies its version and saves the complete public snapshot plus image grants in one database transaction. Repeating publication of the same current version returns the existing publication without creating another version. The returned `url` is a relative path such as `/menu/maison-a1b2c3d4` and remains stable after price/name changes. Later draft edits are invisible publicly until the next publication.

`GET /api/menus/demo` returns the clearly labeled fixture without a database. It does not represent a restaurant account, captured originals or a reconstruction result.

## Media

| Method and path       | Request/access                                                  | Success               |
| --------------------- | --------------------------------------------------------------- | --------------------- |
| `POST /api/media`     | Authenticated raw JPEG/PNG/WebP bytes, matching `Content-Type`  | `201 {id,sha256,url}` |
| `GET /api/media/{id}` | Owner or an asset referenced by any retained published snapshot | Image bytes           |

Limits are 3 MiB per image, 24 million pixels, 10,000 pixels per side, and 100 MiB of distinct stored image bytes per restaurant. The server verifies the declared image type against magic bytes, parses bounded dimension headers and checks container completeness. It does not fully decode/re-encode pixels. SVG, HEIC and video are not accepted by these image endpoints.

IDs are immutable. Identical file bytes deduplicate within one restaurant by SHA-256. There is no cross-restaurant deduplication or access grant. Storage currently keeps the uploaded bytes in PostgreSQL/PGlite; operators should plan external object storage before scaling beyond this pilot.

Draft photos and capture originals remain private unless the exact media ID is used as a published dish image. Other tenants and anonymous clients receive 404 for private assets. Private image responses have `Cache-Control: private, no-store`.

Publication makes referenced images public; those grants remain for retained historical snapshots so an already-open menu continues to load. Published images have `Cache-Control: public, max-age=31536000, immutable` and a SHA-256 ETag. Removing a photo from a later draft/publication does not make an already published copy private again. There is no automated asset deletion/retirement endpoint; retained snapshots and assets need an explicit operator retention policy.

## Durable photo captures

`Scan`:

```json
{
  "id": "opaque-id",
  "dishId": "opaque-dish-id",
  "state": "capturing",
  "frameCount": 2,
  "createdAt": "2026-01-01T12:00:00.000Z",
  "manifestHash": null
}
```

`Frame`:

```json
{
  "id": "opaque-id",
  "mediaId": "opaque-media-id",
  "sha256": "64-lowercase-hex-characters",
  "url": "/api/media/opaque-media-id",
  "metadata": {}
}
```

All capture endpoints require authentication and restaurant ownership.

| Method and path                 | Request                                                         | Success                                                           |
| ------------------------------- | --------------------------------------------------------------- | ----------------------------------------------------------------- |
| `GET /api/scans`                | Optional `?dishId=...`                                          | `200 {scans:[]}`, newest 100                                      |
| `POST /api/scans`               | `{dishId}`                                                      | `201 {scan}`                                                      |
| `GET /api/scans/{id}`           | Optional `?download=1`                                          | `200 {scan,frames:[]}`; download adds JSON attachment disposition |
| `POST /api/scans/{id}/frames`   | Raw image, matching `Content-Type`; optional `X-Content-SHA256` | `201 {frame,duplicate:false}` or `200 {frame,duplicate:true}`     |
| `POST /api/scans/{id}/finalize` | No body required                                                | `200 {scan}`                                                      |
| `DELETE /api/scans/{id}`        | No body required                                                | `200 {ok:true,originalsPreserved:true}`                           |

Upload responses include `id`, `mediaId`, `sha256` and `url`; `metadata` is provided by the capture-detail listing and is currently an empty object for browser uploads. The API does not manufacture poses, camera intrinsics or tracking observations.

There are at most 10 open captures per restaurant, 150 distinct frames per capture, and the same file/restaurant limits as media uploads. Creating a capture requires an existing dish owned by the account.

### Resume protocol

1. Create a capture and retain its ID.
2. Before resuming, fetch its details and compare known server `sha256` values with hashes of the local originals.
3. Upload missing files one at a time. Optionally send the expected lowercase SHA-256 in `X-Content-SHA256`; a mismatch returns `400 CHECKSUM_MISMATCH` and stores nothing.
4. Retrying identical bytes during `capturing` returns the same frame ID with `duplicate:true`. This is resumability at the individual-file level; partial byte-range/chunk uploads are not implemented.
5. Finalize after uploads finish. At least three distinct frames are needed to freeze a manifest. This is an input-integrity minimum, **not** a reconstruction quality criterion. The manifest hashes the sorted frame hashes with a schema version.

Finalization is idempotent and moves `capturing → finalized`. Further frame uploads return `409 SCAN_CLOSED`, even retries of an existing frame. Cancellation moves an open capture to `cancelled`; repeated cancellation succeeds and preserves its originals. A finalized capture cannot be cancelled through this endpoint. Originals and manifests remain owner-readable in either closed state.

The JSON download contains a manifest and authenticated image URLs, not the image bytes or an offline archive. Export the image responses as well to obtain a complete offline capture.

## Reconstruction status

| Method and path            | Access        | Current behavior                                                        |
| -------------------------- | ------------- | ----------------------------------------------------------------------- |
| `GET /api/reconstruction`  | Authenticated | `200 {jobs:[]}` from the restaurant's persisted job records, newest 100 |
| `POST /api/reconstruction` | Authenticated | Always `503 WORKER_UNAVAILABLE`; does not enqueue a job                 |

Returned job records, when present in the database, contain `id`, `scanId`, `engine`, `state`, `attempts`, `errorCode`, `createdAt` and `updatedAt`. The schema reserves states `queued`, `running`, `succeeded`, `failed`, `cancelled` and lease fields for a future worker bridge. No connected queue consumer, worker HTTP authentication, fencing implementation or progress events are exposed by this pilot. The standalone local worker is documented separately in [reconstruction.md](./reconstruction.md).

The unavailable reconstruction action preserves originals and any current model. A menu read, rotation, QR read, price edit or publication never invokes reconstruction.
