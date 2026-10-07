---
format: 1080x1920
duration: ~10s (3 frames)
message: "Matcha in three beats: whisk, pour, sip."
arc: Hook → Pour → Payoff
---

Fixture storyboard for the HyperFrames importer.

## Frame 1 — Whisk

- scene: Bamboo whisk spins in a bowl, kinetic type "WHISK" punches in
- duration: 3s
- transition_in: cut
- status: animated
- src: compositions/f01-whisk.html
- voiceover: "Whisk it fast."
- motion: kinetic-type-beats

Open on motion, no title fade.

## Frame 2 — Pour

- scene: Milk pours in a slow arc, the word POUR draws on the path
- duration: 4s
- transition_in: push 0.3s
- status: built
- src: compositions/f02-pour.html
- voiceover: "Pour it slow."

## Frame 3 — Sip

- scene: Cup lifts out of frame, end card
- duration: 3s
- status: outline
- voiceover: "Then sip."
