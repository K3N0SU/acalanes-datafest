# Design rules

The goal is a site that looks like a person with taste built it over a weekend, not a template.

## References
- **flux-client.com** (read from its CSS): dark canvas `#0a0a0d`, ink `#f2f2f5`, hairline borders `#232329`, JetBrains Mono micro-labels (11px, uppercase, 0.18em tracking), tight headings (-0.02em), about 5% SVG grain, faint 64px line grid. Keep the grain, the grid and the mono labels. Skip its gradient text, glass panels and aurora blobs.
- **milpa-california.vercel.app** (read from its CSS): a farmworker pesticide-safety app. Fraunces 600 display with italic serif eyebrows ("The problem", "How it works"), Public Sans body. Every neutral is tinted toward the brand hue: cream `#f8fcf3`, ink `#001f12`, border `#d6e3cf`, primary green `#008a40`. Accents are limited to a harvest yellow CTA `#fdc436` with **brown** text `#331b06`, plus a poppy orange `#ff691f` for eyebrows. A dark ink hero alternates with cream bands. The product is shown in HTML phone mockups that use real sample data (Valley Guard 2EC, 11:42:08 countdown). `tabular-nums` on every live number. Link underlines draw in on hover, buttons get a color-sweep fill and scale on press, scroll reveals use blur, all on one ease-out-expo curve. Copy is plain, second person and number-heavy ("Point the camera. Get the answer."), and it says what the app can't do.

**Takeaway from both:** a warm serif display, neutrals tinted toward one hue, at most 1–2 accents, real data inside product mockups, and motion that does a job.

## House style
1. Two typefaces with contrast: a display face (a serif such as Fraunces, Instrument Serif or Newsreader, or an odd grotesk such as Space Grotesk or Bricolage Grotesque) plus a mono for labels (JetBrains Mono or IBM Plex Mono). Never Inter alone.
2. 5–6 colors. Off-black or paper off-white background, one ink color, **one** accent used sparingly. No pure `#000` or `#fff`.
3. No gradients on text or buttons. No glassmorphism or backdrop-blur cards.
4. Build structure with 1px hairline rules and tables, not drop-shadow cards.
5. Numbered sections and labels: `01 — Problem`, in mono uppercase.
6. Left-aligned, asymmetric layout. Big headlines (`clamp(3rem, 7vw, 6rem)`) against small body text.
7. Grain at about 4–5% opacity. Optional faint static grid.
8. At most two radii (0 and 6px).
9. One or two odd, specific touches: a margin note, a hand-drawn SVG underline, a footnote, a rotated stamp.
10. One staggered fade-up on load. Hovers change a border or underline. No floating blobs.
11. Real data, names, places and dates in the copy. Credit the data sources in the footer.
12. Copy is terse, declarative and sentence case. Never "revolutionize", "seamless", "unlock" or "empower".
13. Vary section rhythm: a full-bleed band, a ledger list, a big number, a chart with an annotation. Never three identical cards.
14. Icons: none, or simple custom inline SVG. Numbers and words do the work.
15. Charts: direct labels instead of legends, one highlighted series in the accent with the rest in grey, and an annotation explaining what matters.
16. Pick the palette per project and tint it toward that project's subject (e.g. green for agriculture, a rust/clay tone for housing). Text on an accent is a dark shade of the background hue, never pure black.
17. Show the product inside HTML mockups (phone or card) filled with real sample values, not screenshots of empty UI.
18. `font-variant-numeric: tabular-nums` on every number that changes.
19. One easing curve everywhere: `cubic-bezier(0.16, 1, 0.3, 1)` (ease-out-expo). Use a left-to-right underline draw for links and `scale(.97)` on press.

## Anti-patterns (reject on sight)
- Purple/blue/cyan gradients, aurora blobs, glass cards.
- Emoji or icon-in-circle feature grids.
- A centered hero with two CTAs followed by three cards.
- Uniform 16px-rounded cards everywhere, Inter plus system defaults.
- "Lorem", "10x faster", fake testimonials, stock illustrations.
