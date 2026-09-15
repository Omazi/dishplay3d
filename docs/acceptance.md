# Acceptance record

This record distinguishes implemented functionality from executed checks and the dossier's final product targets. Populate measured outcomes after testing; never infer hardware results from browser emulation.

## Web checks

- [ ] Locked installation, TypeScript check, domain tests, build.
- [ ] Signup/login/logout with persisted accounts.
- [ ] Two restaurants cannot read/edit each other's drafts or private media.
- [ ] Create/edit a dish and reject a stale edit.
- [ ] Draft changes remain private until atomic publication.
- [ ] Price changes preserve restaurant URL and do not enqueue reconstruction.
- [ ] Photo upload is bounded and private until publication.
- [ ] Public customer menu works without login or camera permission.
- [ ] 3D code/model requests occur only after the customer's 3D action.
- [ ] Mobile menu, accessible labels/focus, camera error recovery.
- [ ] GitHub CI and Vercel deployment checked independently.

## Not yet physically verified

| Requirement                                | Missing evidence                                                       |
| ------------------------------------------ | ---------------------------------------------------------------------- |
| iPhone native capture                      | Apple SDK/build signing, supported physical phone, native app and test |
| Android native tracking/points             | Implemented native app and connected physical ARCore device            |
| True textured food reconstruction          | New calibrated food dataset and installed supported engines            |
| Model scale/colour/hidden-surface fidelity | Measured object, held-out images and GLB/USDZ review on both platforms |
| 16/20 food reconstruction yield            | Twenty-dish pilot, at most two captures each                           |
| Performance p75 thresholds                 | Real-user field samples; local browser checks are insufficient         |
| Dense live point preview parity            | Sensor-specific implementation and hardware measurements               |

Suggested next physical test: immobile matte/textured dish, three passes at differing heights, held-out control images, known plate diameter. Record phone/OS, retained views and resolution, engine versions, wall time and peak RSS, failures, output hashes and reviewers. Start with a reduced worker batch on 8 GB RAM. Do not turn over food or invent occluded surfaces.
