# Licensing, terms and disclosure (as recorded - not legal advice)

Only what the sessions actually stated or did. Anything else is marked **unknown**: check the provider's current
terms and your plan before commercial use.

## AI-generated content labels
- Stated in the sessions: 抖音, 小红书, B站, TikTok and YouTube all ask creators to declare AI-generated content,
  and China's AIGC labelling rules have been enforced since September 2025; not declaring risks reduced reach
  or removal. Treat the platform label as mandatory for every post (`series.ai_generated: true`).
- Automation coverage: YouTube via `containsSyntheticMedia`; 抖音 via social-auto-upload's declaration flag; every
  other platform needs a manual tick after upload (the package CHECKLIST says so).
- 即梦 / Seedance outputs carry a small burned-in "AI生成" mark. The sessions kept it and recommended keeping it;
  removing it means cropping or blurring that corner.
- The creator chose to drop a self-added "AI-generated · Fiction" overlay from the final cut; the platform-level
  declaration stayed on. The overlay is optional, the declaration is not.

## Generator plans and commercial use
| Provider | Recorded | Unknown |
|---|---|---|
| 即梦 / Seedance | free tier output watermarked; publishing implies a paid plan (third-party guides) | commercial-use terms per plan |
| Kling | paid membership used; MCP downloads offered an unwatermarked URL | commercial-use terms per plan |
| MiniMax | account registered with a Chinese phone number | commercial-use terms, regional availability |
| Vidu, Wan, Veo | researched prices only | everything else |

## People, voices and reference material
- Faces and voices: the creator used **their own** photos and voice. Cloning or closely reproducing anyone
  else's likeness or voice needs that person's permission (the dialogue workflow asks before any clone).
- A third-party video used as a **style reference** was uploaded with an explicit instruction not to reuse its
  footage, characters, text or audio. Do not cut third-party footage into the deliverable.
- Music: generated or locally synthesised beds were used because nothing licensed was at hand; replace with
  a track you hold rights to before publishing anything commercial. Kling's audio option did not produce music.

## Tools
- social-auto-upload: MIT (2023, dreammis). Used as an external CLI; not vendored here.
- Real-ESRGAN weights `realesr-general-x4v3`: BSD-3-Clause; download yourself.
