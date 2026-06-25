# Agent Constraints

## Frontend visual language

- Keep the app in a light, information-dense "Mod intelligence console" style, not a generic SaaS dashboard and not a dark HUD.
- The main impression should be white plus light blue. Use `white`, `slate`, `sky`, and `cyan` as the dominant palette; reserve `rose` for NSFW/destructive states and `amber` for warnings or attention. Avoid green-led themes and large blue/purple gradients.
- Page backgrounds should stay `bg-slate-50`, `bg-sky-50`, or a very subtle light-blue radial accent. Do not use full-page dark backgrounds, visible grid overlays, neon borders, or heavy glow effects.
- Primary surfaces are white or near-white with `border-slate-200` or `border-sky-100`, small shadows, and compact spacing. Cards should support scanning repeated mod intelligence, not marketing presentation.
- Source, NSFW, game, and language tags should be visually distinct and compact. Source tags should use cyan/sky, NSFW should use rose, and game tags should use slate/sky.
- Filters should be dense but readable: compact labels, stable widths on desktop, full width on mobile, and sky focus states.
- Use Tailwind classes already available in the project. Do not add GSAP, large animation libraries, or new design-system dependencies for visual polish.
- Keep hover and focus states subtle: color shifts, light borders, small translate/shadow changes. Avoid bouncing, large scale transforms, and decorative animation.
- Do not change API contracts, route paths, state management, or data structures for visual-only redesign work.
