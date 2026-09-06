# pet-vitals-v1

`pet-vitals-v1` defines Bingzi's persisted internal vitals, rating rewards, and
the transient reward-flight feedback shared by Windows and Android. These
values are intentionally absent from the UI until a later contract enables
their presentation.

## Onion boundary

- Domain owns bounded values, the derived hunger state, rating reward
  resolution, overflow conversion, automatic reserve transfer, and review-tag
  exclusivity. It has no platform or storage dependency.
- Application applies one rating outcome and asks an inner port to save the
  learnt-word marker and pet vitals together.
- Infrastructure stores the state in the platform-private learnt-words store.
  Hunger state is derived and is never persisted.
- Presentation owns reward-flight instances, trails, bursts, pointer
  coordinates, and the current rendered pet target. None of that animation
  state is persisted.

## Vitals

Balance values are centralized constants because they are expected to be
tuned later. Satiety and food reserve are finite floating-point values. The
canonical defaults are satiety `50.0`, food reserve `0.0`, and mood `calm`.
Food reserve is owned by an explicit immutable `FoodJar` domain value object;
`PetVitals` composes that object rather than treating the jar as presentation
or persistence state. The persisted `foodReserve` scalar remains the stable
wire shape so existing stores migrate without a nested-schema rewrite.

- Satiety is clamped to `0.0..100.0`.
- Food reserve is clamped to `0.0..200.0`.
- Hunger is derived as `hungry` below `30.0`, `sated` from `30.0` inclusive to
  `70.0` exclusive, and `satisfied` from `70.0` inclusive.
- Moods are `sad`, `worried`, `happy`, `excited`, `bored`, and `calm`, mapped
  respectively to 悲伤、担忧、开心、兴奋、无聊、平静. Ratings do not change
  mood in this version.

When a satiety addition exceeds `100.0`, the excess contributes `20%` of its
value to food reserve. A direct food-reserve addition contributes `100%` and
is not multiplied by `20%`. For one outcome, satiety and its converted overflow
are calculated first, then the direct reserve gain is added, then the reserve
cap is applied.

After every mutation or restore, satiety below `30.0` triggers a 1:1 transfer
from food reserve toward satiety `50.0`. The transfer is
`min(50.0 - satiety, foodReserve)`. If reserve is insufficient, all remaining
reserve is consumed and satiety may remain below `50.0`. At exactly `30.0`, no
automatic transfer occurs.

The existing scheduler/history repository and the learnt-word repository are
separate persistence boundaries. One learnt-word marker and `PetVitals`
(including its `FoodJar`) are committed together; this contract does not claim
that scheduler/history and learnt-word files form one cross-repository
transaction. Within a running process, adapters must not expose cancellation
between a successful durable commit and the matching in-memory publication;
the review savepoint must remain available so the application can compensate a
failed second write. This does not add crash atomicity across stores.
Presentation emits feedback and advances the card only after the application
call has returned successfully.

## Temporary review marker

The internal marker is an optional single-value enum, not a vocabulary/catalog
tag and not a UI label. Its persisted values are exactly
`ToBeReviewed_Forgot` and `ToBeReviewed_Vague`. A word can therefore hold zero
or one marker by construction. `again` replaces any marker with
`ToBeReviewed_Forgot`; `hard` replaces any marker with
`ToBeReviewed_Vague`; a successful `good` or `easy` review consumes and clears
the prior marker. If malformed legacy data contains both values, Forgot wins
during decoding and the next save writes the canonical single value.

## Rating rewards

The complete machine-readable matrix is in
`pet-vitals-golden-v1.json`. Study `again`/`hard` grant no vitals and set the
corresponding marker; study `good`/`easy` grant satiety `2.0`/`3.0`.

Review `again`/`hard` grant no vitals and replace the marker. Review success
uses the marker that existed before the rating:

| Prior marker | `good` satiety/reserve | `easy` satiety/reserve |
|---|---:|---:|
| none | `0.2 / 0.5` | `0.3 / 0.8` |
| `ToBeReviewed_Vague` | `1.0 / 0.7` | `1.2 / 1.0` |
| `ToBeReviewed_Forgot` | `1.5 / 0.9` | `2.0 / 1.4` |

## Reward-flight feedback

An accepted pointer rating on Study emits an independent gold flight at the
pointer-down screen position. Review uses the platform's primary teal. A
keyboard or accessibility activation falls back to the button center. Each
flight first follows the configured short accelerating spiral, then homes with
acceleration toward Bingzi's current rendered center. The target is sampled on
every frame so dragging, autonomous movement, or a host-window migration does
not leave the flight aimed at a stale position.

Trail history is time based, so faster movement produces a visibly longer
same-color trail. Contact uses the current pet half-size plus orb radius and
emits a radial point burst at the contact location. A new accepted click never
cancels an older flight or burst; all instances update and clean up
independently. Each accepted zero-reward `again`/`hard` action still emits
feedback. Animation state pauses while its host is not visible and is cancelled
only when the host is destroyed or no active pet target exists for the
configured timeout.

The physical `orbRadius` remains the contact radius. The shared `visual` tuning
values in the golden contract make the transient feedback observable: the
visible orb uses radius `16`, its glow reaches `34`, the trail core is `5..12`
wide and scales with speed, and burst particles use radius `4` with a `10`-pixel
glow. These are presentation constants deliberately kept centralized for later
tuning; they do not alter the trajectory or persistence rules.

The shared trajectory vectors fix the end of the 180 ms spiral at `(18, 0)`
relative to the activation point and require interpolation at the oldest trail
boundary, so the rendered polyline does not exceed the speed-derived length.
