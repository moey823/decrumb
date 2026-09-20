# Decrumb visual identity

Original artwork: a clean chain link with three small amber crumbs lifting away.
The link remains whole; removing unnecessary tracking parameters is the metaphor.
The mark does not use an SF Symbol or third-party logo.

Use `decrumb-app-icon.svg` / `.png` for the application identity,
`decrumb-mark.svg` for the standalone mark, and `decrumb-wordmark.svg` for the
horizontal logo. Inverse versions are for dark backgrounds. The monochrome SVG
uses `currentColor`. All seven lowercase wordmark letters are original geometric
strokes authored in the generator. No letters were extracted from a typeface;
the wordmark has no font dependency or font redistribution requirement.

`decrumb-brand-preview.png` presents the icon, light/dark wordmarks, small sizes
and palette. All PNGs are native renders of the same vector geometry.

Palette: indigo `#4A57D1`, warm crumb `#F5B76C`, ink `#222543`.
Use the warm accent for the crumbs; do not recolor the entire wordmark amber.
Keep the mark's proportions and a clear area of at least one stroke around it.
The native 16-pixel icon is intended for small app representations; larger web
placements should use SVG. A monochrome menu-bar adaptation can use the mono mark.

The source of truth is `app/MakeIcon.swift`. Normal app builds generate the iconset
from this code. To regenerate the checked-in branding exports without running
the GUI or accessing an account:

```sh
xcrun swiftc -O -module-cache-path build/ModuleCache app/MakeIcon.swift -o build/make-icon
build/make-icon build/AppIcon.iconset branding
```

These assets follow the repository's AGPL-3.0-only license. They are an original
design for Decrumb, not an assertion of trademark clearance or exclusivity.
