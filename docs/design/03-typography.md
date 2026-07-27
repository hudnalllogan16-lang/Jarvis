# 03 — Typography

## Three families, three jobs

Jarvis's visual identity is carried almost entirely by type. There are three families and each
has exactly one job; using one for another's job is the fastest way to make the surface look
generic.

| Token | Family | Job |
|---|---|---|
| `--font-display` | Bricolage Grotesque | Names of things — company names, page and panel titles, the wordmark |
| `--font-body` | IBM Plex Sans | Everything an operator reads as prose |
| `--font-data` | IBM Plex Mono | Anything measured — numbers, units, timestamps, eyebrow labels, state |

**Why a monospace for labels and not just numbers.** The eyebrow labels
(`HEALTH`, `LATEST UPDATE`, `SPENT TODAY`) are structural furniture, not prose. Setting them in
the data face at small size with wide tracking makes them read as *instrument panel markings* —
they recede as text and register as position. This is the single strongest identity signal in
the surface, and it is why the system looks like an instrument rather than a web app.

**Why numbers must be monospace, non-negotiably.** Money and health values re-render every 15
seconds. In a proportional face the digits change width, the row reflows, and the eye is drawn
to motion that means nothing. Tabular figures make a changing number change *in place*. Every
numeric value in the surface uses `--font-data` with `font-variant-numeric: tabular-nums`.

### The fallback stack is part of the design

    --font-display: "Bricolage Grotesque", "Segoe UI", system-ui, sans-serif
    --font-body:    "IBM Plex Sans", "Segoe UI", system-ui, sans-serif
    --font-data:    "IBM Plex Mono", ui-monospace, "Cascadia Mono", Consolas, monospace

The webfonts load from Google Fonts. **This is a known weakness, recorded as finding M8-F21:**
a locally-run platform should not make a third-party network request to render its own chrome,
and offline the display face silently degrades. The fallbacks are chosen so that degradation is
graceful rather than broken, and self-hosting is a follow-up.

---

## The scale

A modular scale, roughly 1.2, snapped to whole pixels. Nine steps is enough for an application
surface; a tenth step is a sign that a hierarchy problem is being solved with size.

| Token | px | Line height | Used for |
|---|---|---|---|
| `--size-2xs` | 10 | 1.4 | eyebrow labels, unit suffixes |
| `--size-xs` | 11 | 1.45 | timestamps, section eyebrows, meter labels |
| `--size-sm` | 12 | 1.5 | dense metadata, chip text |
| `--size-base` | 13 | 1.55 | secondary prose — health reasons, `why` lines |
| `--size-md` | 14 | 1.55 | **body default** — the reading size |
| `--size-lg` | 15 | 1.45 | emphasised body, part values |
| `--size-xl` | 17 | 1.35 | company names on cards, empty-state headline |
| `--size-2xl` | 19 | 1.3 | approval card titles |
| `--size-3xl` | 22 | 1.25 | panel titles |
| `--size-4xl` | 26 | 1.2 | the wordmark |

Line heights tighten as size grows — a 26px heading at 1.5 floats apart. Weights: 400 (body),
500 (data emphasis, buttons), 600 (names, subheads), 800 (wordmark only).

### Tracking

| Token | Value | Where |
|---|---|---|
| `--track-tight` | `-0.02em` | display type at 22px and above |
| `--track-snug` | `-0.01em` | display type 17–19px |
| `--track-normal` | `0` | all body prose |
| `--track-label` | `0.1em` | uppercase eyebrow labels |
| `--track-wide` | `0.14em` | uppercase section headings |

Large display type needs negative tracking or it reads loose; small uppercase needs positive
tracking or it reads as a block. Both are corrections for optical effects, not style choices.

---

## Rules

1. **Uppercase is reserved for eyebrow labels and section headings**, always in `--font-data`,
   always at `--size-2xs`/`--size-xs`, always with `--track-label` or wider. Uppercase body text
   does not exist in this system.
2. **Never set prose in the data face.** A sentence in monospace reads as output, not as
   explanation. The health reason is prose; the health number is not.
3. **Company names are always display face**, at every size, including inside a sentence in a
   panel title. The name of a company is the most important string on any surface it appears on.
4. **One size step per hierarchy level.** If two things need to be distinguished and are already
   one step apart, distinguish them with weight or colour, not another size.
5. **Measure caps at ~70 characters** for prose blocks. Long-form values (approval payloads) are
   exempt: they are shown in full and never trimmed, because an operator who approves a summary
   of the words has not approved the words.
6. **No text smaller than 10px, ever**, and 10px only for uppercase labels with wide tracking —
   never for prose or for a value an operator must read accurately.
