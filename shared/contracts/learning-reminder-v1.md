# Learning reminder v1

Windows and Android expose the same learning-card content and interval semantics.

- Reminders are disabled by default.
- Reminder vocabulary groups are a multi-select setting independent from the study and review filters. A missing or empty selection means all supported groups (CET4, CET6, and custom), matching the default.
- The user configures one fixed interval in minutes. Decimal values are supported from `0.5` through `120.0`, inclusive.
- Saving settings restarts the timer. Dismissing a scheduled card starts the next full interval.
- Only one learning-card reminder may be visible at a time.
- The card prefers a due reviewed word. If none are due, it selects from the local vocabulary matching `reminderLevels`; an empty selection uses the full local vocabulary. `studyLevels` and `reviewLevels` do not affect reminders.
- Consecutive reminders avoid repeating the previous word when another candidate is available.
- Each card shows the word, phonetic, meaning, and three bilingual examples. A mnemonic is shown when present.
- Preview opens a card immediately without changing an existing timer. There is no snooze action.
- Windows shows a topmost card while the desktop process is running.
- Android uses an in-process card while foregrounded and a high-importance system notification while backgrounded. The alarm is persisted and rearmed after delivery and device boot.
- Android notification delivery requires user notification permission and remains subject to Doze, OEM battery policy, and the user's notification-channel settings. Permission denial disables reminders and is reported in the UI.
- Android notification taps open the matching full card. Heads-up display is requested but the operating system decides whether it appears over the current screen.

The interval is persisted as an IEEE-754 numeric value named `reminderIntervalMinutes`; implementations must not round it to an integer before scheduling. Selected groups are persisted as the normalized set `reminderLevels`; missing or empty legacy values retain the all-groups default.
