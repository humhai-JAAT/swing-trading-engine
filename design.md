# Design — Swing Trading Engine

## Visual design system

Ported from the unified trading engine's dark fintech-professional palette,
with class prefix changed from `ute-` to `ste-`.

**Dark theme palette** (`engine/dashboard_view.py`'s token dict is the single
source of truth in code):

| Token | Hex | Used for |
|---|---|---|
| `bg_page` | `#0B0F14` | App background |
| `bg_surface` | `#141A21` | Sidebar background |
| `bg_surface_raised` | `#1B232C` | Metric cards, account chips, position card |
| `border` | `#232B34` | Card/chip borders |
| `text_primary` | `#E8EDF2` | Headings, metric values |
| `text_secondary` | `#8A96A3` | Labels, captions |
| `accent` | `#3B82F6` | Primary buttons, position card border |
| `success` | `#22C55E` | Profit, "configured" account dot |
| `danger` | `#EF4444` | Loss |
| `warning` | `#F59E0B` | Warning banner |
| `radius` | `10px` | All cards/chips/alerts |

## Differences from the unified engine's design

- **CSS class prefix**: `ste-` (not `ute-`), avoiding collision if both apps
  share a browser session.
- **Simplified variant selector**: simple radio buttons (only 2 variants, no
  need for the 2-level universe-bot dropdown + 4-way variant radio).
- **CNC-specific labels**: "CNC Delivery" instead of "MIS Intraday", no
  square-off time display, scan caption shows "1H-boundary+1 offsets
  (10:16, 11:16, 12:16, 13:16, 14:16)".
- **No subh30/puradin timing labels** — irrelevant for this timeframe.

## Not yet done

- No Figma design file created for this project — the palette was ported
  directly from the unified engine's proven design. If the dashboard needs
  custom components beyond what the unified engine already has, a dedicated
  Figma file should be created at that point.
- `danger` token wiring for loss-colored P&L display — same gap as the unified
  engine.
- Mobile-responsive layout check — not tested.
