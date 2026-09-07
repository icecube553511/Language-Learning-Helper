# 冰子能量光球特效契约 v1

`pet-energy-ball-v1` revision `2` migrates pursuit and visuals from the sibling
`gpt6_test` prototype into both native clients. All effects are transient
presentation state and never persisted.

## Trigger and coordinates

- Every valid activation of any of the four Study/Review rating buttons emits
  one independent orb from the button's screen-space center. Mouse, touch,
  keyboard and accessibility share that command; cancelled gestures emit
  nothing. Study is gold `#F5C451`; Review is cyan `#39D9D0`. Existing rating
  and vitals settlement never waits for collision.
- Dimensions use logical pixels (Android dp and Windows pet coordinate scale),
  independently of text scale. Follow the active Bingzi's live screen position,
  including application-owned dialogs. Never replace an unavailable target
  with the viewport center or a stale position.

## Pursuit and collision

- Immediately pursue with scalar speed `65` logical px/s and acceleration
  `230` logical px/s squared. Each step turns directly toward the target at
  that step's start. Travel is `speed*dt + 0.5*acceleration*dt*dt`, then speed
  increases by `acceleration*dt`. No spiral, speed cap, age limit, boundary
  deletion or concurrency eviction is permitted.
- Use fixed `1/120` second steps and retain the accumulator remainder. Accept
  at most `0.1` seconds of a render frame to avoid large catch-up jumps.
  Interpolate continuous target movement over accepted substeps. Reset target
  history on host changes and resume so relocations do not sweep across space.
- Use swept relative motion of both circles, with combined radius
  `Bingzi displayed half-size + orb radius (7)`. Initial overlap hits at once;
  neither a fast orb nor moving Bingzi can tunnel through the other. Only
  contact ends flight. Anchor the impact to Bingzi's interpolated center at
  contact, then keep it fixed. Rendering and collision use the same sample.

## Visuals

- Port the radius `7` colored orb, radius `4` pale core and radius `46` soft
  glow, with opacity `105/255 * (1-r/46)^2` and the phase color.
- Keep `42` fixed-step trail samples; render every third sample as a tapering,
  fading path with head width `7` and opacity up to `0.55`. Its length grows
  naturally with speed and has no fixed length cap. Pause freezes the trail.
- Contact removes the orb/trail and emits one `420` ms effect: a ring with
  radius `20+38*p`, width `2`, and eight dots at radial distance `22+44*p`, dot
  radius `2`. Here `p` is impact progress; all use phase color and fade `1-p`.

## Lifetime

- Preserve every instance through card rebuilds, navigation and pet host changes.
- Minimized/background applications and unavailable targets pause all effect
  state, including trails, speed and impacts. Resume with a fresh clock and
  target baseline; paused wall time never advances motion or acceleration.
- Exit/disposal clears all instances and callbacks; the next process starts
  empty. There is no maximum concurrent count or timeout.

## Onion boundary and verification

Domain/application retain rating and pet-state rules. Pure transient pursuit
state lives with presentation without storage access. Tk/Win32 and Compose
adapters own clocks, density and window APIs. Windows native effect surfaces
remain pointer-transparent with pointer-safe callback signatures/lifetimes.

`pet-energy-ball-golden-v1.json` supplies shared parameters, motion samples and
relative swept-contact vectors for both platforms. Parity manifests and
`tools/verify_sync.py` enforce the same revision and parameters.
