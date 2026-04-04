# Design System: Tiny Monitor (based on Linear)

## Visual Theme
Dark-mode-first dashboard on near-black canvas. Inter Variable with OpenType `"cv01","ss03"`. Single brand accent: indigo-violet.

## Color Palette

### Backgrounds
- Page: `#08090a`
- Panel: `#0f1011`
- Card: `rgba(255,255,255,0.02)` with `1px solid rgba(255,255,255,0.08)`
- Elevated: `#191a1b`

### Text
- Primary: `#f7f8f8`
- Secondary: `#d0d6e0`
- Muted: `#8a8f98`
- Dim: `#62666d`

### Brand & Status
- Accent: `#5e6ad2` / `#7170ff`
- Normal/Success: `#27a644`
- Warning: `#d97706`
- Critical: `#dc2626`

### Borders
- Standard: `rgba(255,255,255,0.08)`
- Subtle: `rgba(255,255,255,0.05)`

## Typography
- Font: Inter Variable, `font-feature-settings: "cv01","ss03"`
- Mono: Berkeley Mono / SF Mono
- Weights: 400 (read), 510 (emphasis), 590 (strong)
- Display letter-spacing: negative at large sizes

## Components
- Cards: translucent bg, semi-transparent borders, 8px radius
- Buttons: near-zero opacity bg, 6px radius
- Inputs: `rgba(255,255,255,0.02)` bg, 6px radius
- Elevation via luminance stepping, not shadows
