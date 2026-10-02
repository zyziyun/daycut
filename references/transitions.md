# Transitions

Authored in the **index root timeline** on `.scene-wrap` wrappers (one untimed wrapper per scene host), so scene files never author exits. Set in `scenes.config.json` as `"transition": [type, seconds]` on the incoming scene.

| type | feel | use for | default s |
|---|---|---|---|
| `blur` | soft crossfade with blur | continuing the same idea | 0.8 |
| `fade` | quick plain crossfade | same board, next step | 0.45 |
| `push` | horizontal slide, light blur | "next point" | 0.7 |
| `vpush` | vertical slide | going deeper on the same topic | 0.7 |
| `iris` | circle opens from centre | the hero reveal (core idea) | 1.1 |
| `zoom` | zoom through outgoing | diving into detail / the math | 0.8 |
| `focus` | focus pull (blur out → in) | changing viewpoint | 0.9 |
| `blocks` | 8 navy panels sweep down and up | new chapter | 1.1 |
| `chroma` | red/blue split, stepped jitter | tension ("the enemy") | 0.8 |
| `flip` | 3D card flip | switching to real-world tools | 0.9 |
| `zoomout` | outgoing shrinks, incoming settles | outro | 1.0 |

Quantization film used: blur ×3, push ×4, vpush ×2, iris, zoom, fade, focus, blocks, chroma, flip, zoomout — one calm primary family plus accents at section changes.

Mechanics: the outgoing scene must stay alive for the transition length (`make_index.py --patch-scenes`); each wrapper gets an identity `tl.set` at t=0 as a seek baseline, incoming tweens use `immediateRender: false`; overlays (`#tx-blocks`) sit above scenes and below captions (z 40 vs 50).
