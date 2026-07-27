# Vendored fonts

Owner-approved (M8, 2026-07-27): Jarvis is self-contained and depends on no external font
delivery. All three families are licensed under the SIL Open Font License 1.1 — the full
license text for each ships beside the binaries in this directory.

| Family | Role (see docs/design/03-typography.md) | License file |
|---|---|---|
| Bricolage Grotesque (variable, opsz/wght) | `--font-display` | OFL-bricolage-grotesque.txt |
| IBM Plex Sans (400/500/600) | `--font-body` | OFL-ibm-plex-sans.txt |
| IBM Plex Mono (400/600) | `--font-data` | OFL-ibm-plex-mono.txt |

Provenance: woff2 binaries and `@font-face` declarations fetched from the Google Fonts
css2 API (all unicode subsets kept); license texts from the google/fonts repository (ofl/).
`../fonts.css` carries the declarations with URLs rewritten to this directory. The hookup
into the page (`<link>`/token fallback order) lands with the next surface merge so running
lanes aren't conflicted; until then the tuned fallback stack from M8-4 remains in effect.
