# Dashboard UI refresh — design notes (2026-09-17)

Written for engineers and collaborators on SIGNAL (Jim, Jack). Explains the
choices behind the September 2026 dashboard redesign so later changes stay
consistent with them.

## The brief

Jim asked for the dashboard to look futuristic and intuitive, with proper
charts, and to close the findings of an external UI audit (Tailwind Play CDN
in production, low contrast, no keyboard path to rows, unlabeled inputs,
unclear column names, palette duplicated across templates).

Three skill libraries were read for guidance (the MCPmarket "futuristic
designer" skill, bencium's controlled/impact/innovative UX skills and design
audit, and Vercel's web interface guidelines) plus Anthropic's `dataviz` and
`frontend-design` skills. Where they conflicted, the decision and the reason
are recorded below.

## Subject, audience, job

- **Subject:** NHTSA defect telemetry, read through Rule 23. The vernacular
  is instrument clusters, tiers, thresholds, and filings.
- **Audience:** two lawyers scanning for the next cluster worth a memo.
- **The page's one job:** rank and expose the clusters most likely to
  certify, and let the reader open one in a keystroke.

## Tokens

Defined once in `tailwind.config.js`; templates only use utilities.

| Role | Value | Notes |
|---|---|---|
| Page | `#0A0E1A` | Midnight navy, not pure black (OLED smear, and "designed dark, not inverted"). |
| Surface | `#111827` | Cards. Border `#1D2536`. |
| Text primary | `#E6E9F2` | Soft off-white, ~15:1. |
| Text secondary | `#98A2BA` | 9.1:1. |
| Text tertiary | `#7C8AA3` | 6.2:1. Labels, eyebrows, ticker captions. Fixes the audit's contrast finding. |
| Disabled / decorative | `#5A6580` | 3.3:1. Dimmed zeros, sort glyphs. |
| Brand accent `signal` | `#FB7185` | LIVE dot, focus ring, selection. |
| Data hue `data` | `#3987E5` | Chart marks only. Never a status color. |
| Tier colors | rose / orange / amber / emerald 400 | Unchanged; they carry meaning. Always paired with a text label. |

The Tailwind `zinc` scale is overridden with these ink values, so every
existing `zinc-*` utility picked up the theme without a template rewrite.

**Type.** Chakra Petch (display: page titles, eyebrows, column headers,
tier labels) over IBM Plex Sans (body) and IBM Plex Mono (ticker, scores,
axis ticks). Inter was dropped: every skill flagged it as the default look.
Chakra Petch's angular forms read as instrument-cluster type, which is the
subject's own world.

**Depth.** Layered shadow plus a 1px inset highlight (`shadow-card`,
`shadow-raised`, `shadow-panel`). Glassmorphism was rejected: bencium lists
it as the single flatly banned technique, and it hurts contrast behind data.
The header keeps a backdrop blur because it sits over scrolling content.

**Motion.** Only transform, opacity and color. Entrance stagger on the KPI
and chart cards totals under 400ms. Panel opens in 250ms. Everything is
disabled under `prefers-reduced-motion`, and the tier count-up is skipped
there too (the server-rendered number is already in place).

## Signature element

The **score meter**: a ten-segment bar in the tier's color, lit to the
nearest ten points, with the score in mono beside it. It reads like a
tachometer, scans faster than a continuous bar, and makes the 100-score
saturation at the top of the table visible instead of hiding it. It appears
on rows, in the panel header and on the cluster page.

## Layout

```
Filters (one row; scope everything below)
Tier counts   CRITICAL | HOT | WATCH | MONITOR      (48px hero figures + 12-mo sparklines)
Charts        Volume 12 mo (2 cols) | By component | By make
Table         signals strip → sortable table → pagination      [ detail panel ]
```

Filters moved above the KPI row because dataviz's rule is "one filter row
above everything it scopes". The tier counts respect only the activity
window (as before); the two breakdown charts and the signals strip respect
every filter; the volume chart is global and says so in its subtitle.

## Charts (dataviz method)

- **Volume, 12 months.** Trend over time with one series that matters, so
  the *emphasis* form: all tracked complaints as a gray line with a 10% wash,
  and the score-70+ slice as the data-blue line. Legend present, end markers
  with a 2px surface ring, hairline solid gridlines, crosshair + tooltip
  listing both series, and a "View as table" twin so nothing is gated on
  hover. No dual axis.
- **By component / by make.** Nominal categories, so one hue for every bar,
  sorted descending, value at the tip, top seven.
- **Tier colors were validated** with the dataviz palette script as a
  categorical set on the dark surface and failed (orange vs amber below the
  normal-vision floor). They are therefore never used as chart series; they
  remain status colors with labels.
- All chart geometry is computed in `web/charts.py` (pure functions, tested)
  and rendered as inline SVG. No JavaScript chart library.

## Accessibility and keyboard

- Real `<a>` on the vehicle name in every row (opens the panel via JS, falls
  back to the cluster page). Row hover actions also show on `focus-within`.
- `aria-sort` on the active column; `scope="col"` on every header; a
  `<caption>` on both tables.
- Every filter has a `<label for>`; inputs are 44px with one focus ring.
- The detail panel is `role="dialog"`, labelled by its title; focus moves to
  the close button when content lands and returns to the row link on close.
- Skip link, `color-scheme: dark`, `theme-color`, explicit select colors for
  Windows dark mode, `content-visibility` on rows.

## Build

Tailwind is compiled ahead of time: `npm run css` writes
`web/static/app.css`, which is committed. Railway's image has no Node.
Dynamic class names are forbidden in templates; the tier palette is a dict of
full class strings in `web/app.py` (`CLASSIFICATION_PALETTE`), which the
compiler's content scan reads.

## Not done in this pass

- Texas complaint count column (needs a per-cluster state join; parked until
  it matters for case selection).
- The 100-score saturation itself is a scoring-formula question, not UI.
- Visual QA in a real browser against production data. The templates are
  covered by render tests with fake data; the live look still needs a pair
  of eyes on the deployed dashboard.
