# iPhone capture → restaurant dish

## Using the implemented flow

1. Install a signed build of the [iOS app](native-ios.md). The GitHub unsigned build alone cannot be installed. Object Capture support is checked on the actual phone; unsupported phones can still take ordinary photos.
2. Capture an immobile dish in the app: detect and adjust the volume, circle at the low height, follow the native dial, then continue at the oblique and upper heights. Completion comes from Apple’s capture session, not a photo counter. Finish and retain the originals.
3. On the restaurant website, save/open a dish and choose **Préparer de nouvelles photos / Prepare new photos**. In the iPhone section create a private association code. It expires after ten minutes.
4. Copy the code into **Associer au site / Pair with website**, or use **Open installed app** on that iPhone. The custom URI only pre-fills the code; it cannot alter the server or send photos automatically. Select the saved series and pair.
5. Check the returned restaurant and dish, then explicitly send. The app processes and uploads one JPEG copy at a time. If interrupted, reopen the same local series and resume; known image hashes are skipped. Keep the app open for transfer.
6. Finalize only when all desired views are received. The website shows private received photos and lets the owner select a dish image. Publishing remains a separate owner action. Local USDZ reconstruction/Quick Look and ZIP export still use the original capture.

The current app does not automatically upload or publish its generated USDZ, convert it to GLB, or certify the quality/scale of a food model. The external reconstruction worker remains separately configured and must be available before the website offers a job. The Android app can adopt the same server protocol later; it currently exports captures manually.

## Protocol

| Endpoint | Access | Behavior |
| --- | --- | --- |
| `POST /api/capture-links` | Owner cookie + same Origin, `{dishId}` | Returns `{id,code,expiresAt}`; 16 random hex characters (64 bits), single-use, ten minutes. Replaces prior unclaimed codes for this dish. |
| `GET /api/capture-links?dishId=…` | Owner cookie | Latest 20 associations: IDs, dates, state and received count; no raw code/token or hashes of credentials. |
| `DELETE /api/capture-links/{id}` | Owner cookie + same Origin | Immediately revokes the capability. Preserves the capture and every received image. |
| `POST /api/native/pair` | No cookie, `{code,deviceSecret}` JSON | Native generates/persists 32 secure random bytes as 64 lowercase hex characters before sending. Claims one dish/scan; returns snapshot below. Twenty attempts/IP/15 minutes. |
| `GET /api/native/session` | `Authorization: Bearer deviceSecret` | Snapshot for this capability’s single scan. |
| `POST /api/native/frames` | Same Bearer | Raw JPEG/PNG/WebP, matching `Content-Type`, mandatory SHA-256 `X-Content-SHA256`; 201 new or 200 duplicate. No arbitrary scan/dish parameter. |
| `POST /api/native/finalize` | Same Bearer | Freezes at least three distinct received photos; idempotent. This is not a quality threshold or a reconstruction action. |

Snapshot shape: `{scan:{id,dishId,state,frameCount,createdAt,manifestHash},dishName,restaurantName,expiresAt,hashes:[sha256],limits:{maxImageBytes,maxFrames}}`. It exposes no private media URLs, account session or mutation authority beyond this scan. Session cookies alone cannot authorize native requests.

The capability lasts seven days from its first claim. Retrying a claim with the same code and same device secret returns the same scan without extending expiry, even if the original ten-minute code expired after a lost response. A different secret cannot reclaim the code. Revocation or capability expiry blocks reads, writes and finalization. A new code can associate a fresh server series; prior photos remain retained. Replacing the local association explicitly removes the old local credential; the owner can revoke that old grant on the site.

## Storage, concurrency and limits

- Migration `003_native_capture_links.sql` stores only SHA-256 credential hashes. The iPhone stores the credential in `kSecAttrAccessibleWhenUnlockedThisDeviceOnly` Keychain storage, outside the Files-visible Documents directory and ZIP export.
- Association and native scan writes serialize on the same restaurant row lock as web uploads, finalization and revocation. A write rechecks authorization while holding the lock. An in-flight write may finish before revocation obtains the lock; none authorized afterward can proceed.
- Browser APIs retain mandatory same-origin checks. Native endpoints allow absent Origin, reject foreign Origin and do not enable CORS. HTTPS API origin is fixed in the iOS app; redirects are refused and cookies disabled.
- Shared server limits remain 150 unique photos per scan, 3 MiB / 24 MP per photo, 100 MiB distinct media bytes per restaurant and ten active scan sessions. Creating a code does not consume an active scan slot; claiming it does. Cancel/finish unused capturing series from the website to release slots.
- Cached JPEG copies use transformed orientation and strip the original file’s metadata by decoding/re-encoding. The original is never rewritten. Server photos do not pretend to include native camera poses or depth. Reconstruction from originals can still use native metadata on the phone.
- Backgrounding cancels the active upload task. An interrupted request may already have been received; the next status/hash check handles this. Nothing removes originals or cached working copies automatically.

## Evidence boundary

Node integration tests exercise real embedded PostgreSQL migrations, owner isolation, concurrent claims, expiry, limits, revocation, hash deduplication and immutable finalization. The browser scenario exercises code generation, a simulated native HTTP client, owner photo review/selection, publication, cross-tenant denial and revocation, in FR/EN. It does not simulate Apple camera tracking or prove physical capture quality.

A signed iPhone installation must still verify Keychain restoration after relaunch, HEIC orientation, real offline/background interruption, the native volume/points, three completed passes and a real dish reconstruction. Xcode compilation runs on GitHub’s Mac runner, never on the 8 GB Linux laptop.
