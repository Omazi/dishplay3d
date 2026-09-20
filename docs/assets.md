# Illustrative photographs

The example restaurant and all its menu data are fictional. The photographs are real stock photographs; they are not this restaurant's dishes, captured scans, or evidence of reconstruction. No demonstration 3D asset is represented as a reconstructed dish.

Images downloaded from Unsplash's image CDN for the labelled example catalogue:

| File                       | Original image                                               |
| -------------------------- | ------------------------------------------------------------ |
| `public/images/burger.jpg` | https://images.unsplash.com/photo-1568901346375-23c9450c58cd |
| `public/images/pasta.jpg`  | https://images.unsplash.com/photo-1473093226795-af9932fe5856 |
| `public/images/salad.jpg`  | https://images.unsplash.com/photo-1512621776951-a57141f2eefd |

See https://unsplash.com/license. Replace these with your own dish photographs for an actual restaurant. Example names, prices and allergen lists do not describe the stock photographs reliably and must never be used as food advice.

## Original-photo relief and illustrative 360° dishes

The photo mode is a shallow WebGL parallax treatment of the three photographs above. It never claims to reconstruct unseen surfaces. The 360° mode uses separate, similar dishes under **CC BY 4.0**, explicitly accepted as illustrations and labelled separately from the photographs. Artist and licence links appear beside each viewer.

| File                      | Artist                | Original source                                                                                                   | Bytes     |
| ------------------------- | --------------------- | ----------------------------------------------------------------------------------------------------------------- | --------- |
| `burger-illustration.glb` | darklord3d / erebus3d | [Burger Realistic (Free)](https://sketchfab.com/3d-models/burger-realistic-free-18e59d7dbd2243c69f469e0f056f44c4) | 1,851,652 |
| `pasta-illustration.glb`  | ne0ns / Ervinas       | [Pasta](https://sketchfab.com/3d-models/pasta-bec7601a89f14d0bbe7eb40b48d14b26)                                   | 1,542,076 |
| `salad-illustration.glb`  | churaed               | [Salad](https://sketchfab.com/3d-models/salad-5254132bd1b24be7a2dc888aba5e51a3)                                   | 1,405,228 |

[CC BY 4.0 licence](https://creativecommons.org/licenses/by/4.0/). These are modified assets: colour textures resized to 1024 px JPEG, other textures to 512 px; meshes simplified with official gltfpack 1.2 (`-si 0.6 -se 0.002 -ke`). Pasta's legacy specular-glossiness material was converted to nonmetallic metallic-roughness with its original diffuse texture. Models contain their textures and need no external mesh or texture decoder. The matching `*-model.webp` posters are actual renders of these optimized models, not photographs.

Burger was retrieved from [this pinned mirror](https://github.com/AtulSemwal963/signature-burger/tree/6205a7e48c9278a96352d69da25fa0401c267e06/public/models/burger), preserving its embedded source/author/licence attribution. Pasta and salad came from AllenAI's Objaverse distribution: `glbs/000-082/bec7601a89f14d0bbe7eb40b48d14b26.glb` and `glbs/000-081/5254132bd1b24be7a2dc888aba5e51a3.glb`. Original metadata and current Sketchfab pages agree on CC BY 4.0.

Optimized GLB SHA-256:

- Burger: `3e19471c2f9633f6f31522de276b7b97022520934b23e5e6221e6de3cf79aa82`
- Pasta: `2a000ff788dd69f0f45d6a01963473d4fc8ee5e56a09853fe5f1023a4bfd528f`
- Salad: `77d45a6082413858981e7f3dca4ebb1d6907e610fe8209b987052faa228517fd`

Only an explicit 360° action imports the model engine and selected GLB. One viewer/cache entry is retained. Motion pauses offscreen or when hidden, reduced-motion starts without autoplay, and leaving the mode releases its viewer. Photo relief has no animation loop: it renders on interaction or resize with a maximum 1400 × 1000 drawing buffer.
