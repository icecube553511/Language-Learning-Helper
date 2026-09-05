# reward-feedback-v1

This presentation contract defines the transient feedback emitted after a
successful Study or Review rating. It is independent of pet vitals persistence.

- `FeedbackRequest` carries `study` or `review` and a finite pointer origin.
- The visual state is transient and lives only in presentation.
- Each event follows a 150 ms intro arc, then seeks the currently rendered pet
  center with per-frame target sampling. Contact uses pet half-size plus a 7 px
  orb radius.
- Intro, seek, and impact states are independent, so concurrent ratings never
  replace one another. A missing target expires an event after 600 ms.
- Study uses gold `#F4C542`; Review uses the platform primary teal.
- The visual language is a compact 11 px core, 27 px glow, 2.5 px highlight,
  speed-aware 2..6 px trail, and a 280 ms impact with 12 particles.
- The overlay is visual-only and must pass pointer hit testing through to the
  learning and review controls.
