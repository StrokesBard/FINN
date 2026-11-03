# FINN web

The Brief screen, built with Next.js 16 (App Router, Cache Components). It renders `data/brief/brief-<window>.json`, which `python -m finn brief` writes. The UI computes no figures. Set `FINN_BRIEF_DIR` to read the JSON from somewhere else.

- `app/page.tsx`: the screen
- `components/cards.tsx`: cards, results tables, moves, sources
- `components/ai.tsx`: model-read blocks and the AI status
- `components/triage.tsx`: Done / Undo, restored before first paint
- `lib/brief.ts`: types and the cached loader
- `lib/format.ts`: display formatting only

Run it with `npm run dev` here, or see the root [README](../README.md) for the whole pipeline and for opening it on a phone.
