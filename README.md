# FINN

A mobile-first investor agent: a short daily **Brief** of what changed across a portfolio (push), and an on-demand **Dossier** grounded in each company's own filings (pull).

## Layout

```
pipeline/          Python: ingestion, parsing, storage (installable package `finn`)
  src/finn/
  tests/           tests run against real captured exchange data (tests/fixtures/)
web/               the mobile web app (not started yet)
spike/             throwaway scripts that proved each data source; see spike/FINDINGS.md
data/              local archive written by the pipeline; git-ignored on main
```

## Data is kept off `main`

`data/` is ignored on `main`, so the code history stays readable. When the archive is worth committing, it gets its own orphan branch, checked out as a worktree at `data/`:

```bash
git worktree add --orphan -b data data
```

The pipeline keeps writing to `data/` as usual. Snapshots are committed from inside `data/` to the `data` branch, which shares no history with `main`.
