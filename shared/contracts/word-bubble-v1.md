# Word Bubble Interaction v1

`word-bubble-v1` defines the shared meaning of word-level lookup inside every
English example rendered by the Windows and Android clients.

## Token and lookup

- English tokens are contiguous ASCII letters with an optional internal or
  trailing ASCII apostrophe or right single quote (`don't`, `students'`).
  Hyphens split tokens. Punctuation and
  surrounding digits are not part of a token.
- A token lookup normalizes the token with Unicode NFKC, trim, and casefold.
- A known token resolves to the vocabulary entry with its part of speech
  extracted from the leading `n.`, `v.`, `adj.`, `adv.`, `prep.`, `pron.`,
  `conj.`, `interj.`, `abbr.`, `aux.`, `art.`, `num.`, `vt.`, or `vi.` tokens
  in the meaning. The Chinese meaning is the same meaning with those tokens
  removed and whitespace folded.
- An unknown token still opens a bubble with the stable text
  “词库暂无中文释义”. Its source sentence may be shown as context, and English
  tokens in that context remain recursively interactive under the same rules.

- A known token must surface the entry's bilingual example pairs so the bubble
  never renders a known word's examples as English-only. For each visible
  example the platform renders the English sentence together with its stored
  Chinese translation (`zh`). When an example has no Simplified-Chinese
  translation, the platform must render a Simplified-Chinese fallback line
  (“（暂无中文释义）”) rather than an English-only example. The same rule applies
  to the source context shown for an unknown token.

## Stack behavior

- The maximum stack depth is **9**. A depth-9 bubble cannot create another
  child.
- Opening a token from the base replaces the current stack with one root.
- Opening a token from bubble depth `d` keeps bubbles `0..d`, removes all
  descendants, and appends the new bubble.
- Clicking blank space inside bubble depth `d` keeps bubbles `0..d` and closes
  descendants.
- A bubble's explicit dismiss control (close button, title-bar close, or the
  platform's dismiss affordance) removes that bubble and all of its
  descendants, revealing its parent. Dismissing a root bubble clears the whole
  stack. This is distinct from a blank-space click, which keeps the current
  bubble.
- Clicking outside every bubble closes the complete stack.
- Bubble state is transient presentation state. It is not persisted and does
  not change review, learnt-word, catalog, or settings data.

The platform UI may position a bubble above or below its token anchor, but it
must preserve these state transitions and reuse the same token/lookup rules.

The bubble surface must be sized just enough to fully show the word, phonetic,
part of speech, meaning, and every rendered bilingual example — no larger than
its content requires and never clipping it. On common layouts the bubble fits
its content without manual resizing.

The scope is the learning card, review card, and runtime word-reminder
examples. Printable dictation output is a document preview, not an interactive
example surface, so its text is intentionally not tokenized.
