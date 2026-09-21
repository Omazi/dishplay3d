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

The photo mode is a shallow WebGL parallax treatment of the three photographs above. It never claims to reconstruct unseen surfaces. The 360° mode uses separate, similar dishes under the licences listed below, explicitly accepted as illustrations and labelled separately from the photographs. Artist and licence links appear beside each viewer.

| File                      | Artist                | Original source                                                                                                   | Bytes     |
| ------------------------- | --------------------- | ----------------------------------------------------------------------------------------------------------------- | --------- |
| `burger-illustration.glb` | Ehsan Abbasi (CC BY-SA 4.0) | [Back Yard Burgers - Classic Burger](https://sketchfab.com/3d-models/back-yard-burgers-classic-burger-6e13942ff76d4129b06e097cdd060adb) | 3,671,948 |
| `pasta-illustration.glb`  | ne0ns / Ervinas       | [Pasta](https://sketchfab.com/3d-models/pasta-bec7601a89f14d0bbe7eb40b48d14b26)                                   | 1,542,076 |
| `salad-illustration.glb`  | churaed               | [Salad](https://sketchfab.com/3d-models/salad-5254132bd1b24be7a2dc888aba5e51a3)                                   | 1,405,228 |

[CC BY 4.0 licence](https://creativecommons.org/licenses/by/4.0/). Pasta and salad are modified assets: colour textures resized to 1024 px JPEG, other textures to 512 px; meshes simplified with official gltfpack 1.2 (`-si 0.6 -se 0.002 -ke`). Pasta's legacy specular-glossiness material was converted to nonmetallic metallic-roughness with its original diffuse texture. Models contain their textures and need no external mesh or texture decoder. The matching `*-model.webp` posters are actual renders of these optimized models, not photographs.

The replacement burger was retrieved from AllenAI's public Objaverse distribution,
`glbs/000-103/6e13942ff76d4129b06e097cdd060adb.glb`. Both the embedded attribution and
current Sketchfab API identify Ehsan Abbasi and **CC BY-SA 4.0**. It is a modeled
illustration with more natural textured surfaces, not a documented photogrammetry scan.
Original 1024 px color maps were retained in resolution and encoded as quality-94
JPEG; normal maps use 512 px PNG. gltfpack 1.2 optimized geometry layout without
mesh simplification. A root transform sets an illustrative 16 cm footprint and
aligns the bottom to the table. The GLB, USDZ and poster derivatives remain licensed
[CC BY-SA 4.0](https://creativecommons.org/licenses/by-sa/4.0/); public attribution
and modification details are in `/models/LICENSE.txt`. The original model is 9,038,332
bytes; the lazy-loaded GLB is 3,671,948 bytes and Quick Look USDZ is 6,154,818 bytes.
The USDZ is requested only after an explicit AR action. Embedded source credits survive.

Pasta and salad came from AllenAI's Objaverse distribution:
`glbs/000-082/bec7601a89f14d0bbe7eb40b48d14b26.glb` and
`glbs/000-081/5254132bd1b24be7a2dc888aba5e51a3.glb`. Original metadata and current
Sketchfab pages agree on CC BY 4.0.

Original optimized GLB SHA-256 (before the illustrative tabletop transform):

- Pasta: `2a000ff788dd69f0f45d6a01963473d4fc8ee5e56a09853fe5f1023a4bfd528f`
- Salad: `77d45a6082413858981e7f3dca4ebb1d6907e610fe8209b987052faa228517fd`

In the public menu, only an explicit 360°/3D action imports the model engine and selected GLB. The marketing story also loads its one model after scrolling begins. One viewer/cache entry is retained. Motion pauses offscreen or when hidden, reduced-motion starts without autoplay, and leaving the mode releases its viewer. Photo relief has no animation loop: it renders on interaction or resize with a maximum 1400 × 1000 drawing buffer.

## Tabletop AR and mobile gestures (2026-09-20)

All three illustrations now expose **View on my table** from the home page’s 360° mode and the demo menu. GLB powers WebXR/Scene Viewer; a pre-exported textured USDZ powers iPhone Quick Look. The default illustrative footprint is 16 cm for the burger, 26 cm for pasta and 24 cm for salad. These are presentation sizes, explicitly labelled approximate; they do not measure the original photographs or a restaurant serving. Visitors can resize the illustrations in AR.

`scripts/prepare-demo-ar.py` runs with the installed Blender 4.5.13 in an isolated one-CPU, 768 MiB/no-extra-swap container. It adds a tabletop root transform to GLB while preserving every original mesh, compressed texture, material and attribution. USDZ conversion bakes gltfpack’s texture-coordinate transforms into per-face UVs, maps unlit salad materials to matte USD Preview Surface, and reimports both formats to check geometry, readable textures, footprint and bottom alignment. [Validation results and current hashes](demo-ar-validation.json) record all six assets. Small CPU renders of all three exported USDZ files also verified their visible texture placement; native camera placement must still be checked on an actual compatible phone.

3D capture of pointer/wheel gestures is off by default. **Control in 3D** enables model rotation/pinch zoom; **Done** or Escape restores page scrolling. Panning and tap-to-refocus are disabled to keep the dish centered. Photo relief ignores touch-drag scrolling; its explicit perspective slider remains usable. In public menus the model engine/GLB loads only after choosing 360°/3D, and USDZ is not fetched until AR is requested. Browsers without AR receive a clear supported-phone instruction; rejected AR launch returns an error message without losing the 3D view.

## Immersive storefront (September 2026)

- `public/images/burger-story.webp`: a new transparent browser render of the replacement
  licensed burger GLB, at `0deg 75deg 110%`, FOV 30°, exposure .9. The prior poster
  included the viewer's progress bar; the new render removes that UI artifact.
  Same CC BY-SA 4.0 model attribution as above. This is still an illustrative model,
  not a reconstruction of `burger.jpg`.
- `public/images/capture-guide-fr.webp`, `capture-guide-en.webp`: actual screenshots
  of DishPlay's existing web capture guide, captured from the local production build
  with zero photos and no camera access. The guide's own explanation of its limits
  remains visible. They do not depict live reconstruction or the native iOS app.
- `public/images/restaurant-table.webp`: original background generated with the
  built-in ImageGen tool for this redesign, then encoded as a 1440 × 960 WebP
  (100,290 bytes). The burger is not part of this image: the site composites the real
  licensed 3D model over it. Visible copy identifies the scene as illustrative.

Table generation prompt (built-in tool, not the API/CLI fallback):

> Use case: photorealistic-natural. Asset type: background for an explicitly illustrative restaurant-table scene on the DishPlay website. Generate ONE wide landscape editorial photograph, 3:2 ratio. Empty warm walnut restaurant table surface filling the lower 75 percent of the image, seen at about 25 degrees down from a seated guest position. Leave a large completely empty clean area in the center and center-right for a real 3D burger to be composited by the website, with no food, plates or objects there. At the far right edge only a casually folded dark linen napkin and simple silver fork. Soft warm late-afternoon window light from upper left. Upper quarter is an out-of-focus intimate premium bistro with dark graphite walls, subtle warm highlights. Quiet realistic grain, natural restrained palette, no orange filter. Table must extend fully to left/right/bottom edges with NO front edge visible. No people, no lettering, no logo, no phone, no food, no watermarks. High-end gastronomic editorial photography, believable real materials, not a game render. This is only a background, not a screenshot or an AR camera feed.
