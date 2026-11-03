# Design

Surface mode: **Operate** for the whole app. Restrained color; brand lives in precise detail.

## World

An auditor's desk. Warm paper neutrals for the chrome so the document page reads as the brightest,
whitest thing on screen; ink-dark text; one deep ink-blue for actions and selection. Status color
is semantic only and always paired with a word or icon.

Light theme, chosen from the use scene: office daylight, long reading sessions next to white
document pages.

## Type

IBM Plex Sans for everything (self-hosted via @fontsource). IBM Plex Mono only for data:
field keys, values in tables, page numbers, file sizes. Fixed rem scale, ratio ~1.15:
12 / 13 / 14 (base) / 16 / 18 / 22. Tabular numerals in all numbers.

## Tokens (see web/src/index.css)

- `--paper` #f6f5f1 app background · `--panel` #fbfaf7 sidebars/toolbars · `--surface` #ffffff content
- `--ink` #1b1d21 text · `--ink-2` #4a4f57 secondary · `--ink-3` #6d727a tertiary (≥4.5:1 on paper)
- `--line` #e3e0d8 borders · `--line-strong` #cfcbc0
- `--accent` #1f4fa3 actions/selection · `--accent-weak` #e8eef9
- `--pass` #2f6b45 / `--pass-weak` #e7f1ea · `--fail` #a8322a / `--fail-weak` #f8e9e7
- `--review` #8a5a00 / `--review-weak` #f8eedb · evidence highlight `--mark` #fbe7a1

Radius 6px controls, 8px panels. Shadows only on floating layers (menus, toasts):
`0 4px 16px rgb(27 29 33 / 0.10)`.

## Components

Buttons: primary (accent fill), secondary (surface + line border), ghost, danger. 32px height,
13–14px label. Inputs 32px, 1px line border, accent focus ring (2px, offset 1px).
Tables: 40px rows, hairline separators, sticky header on panel color.
Status: dot + word ("Verified", "Corrected", "Needs review"), never color alone.

## Motion

150–200ms ease-out on hover/selection/panel changes. No entrance choreography.

## Refused

Gradient headers, metric tiles, eyebrow labels, card grids, glass, emoji, colored side-borders.
