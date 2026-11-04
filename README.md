# FINN data

This branch holds only the published Brief: `brief/brief-24h.json`, `brief-3d.json` and `brief-7d.json`. Each is exactly what the screen shows, with a source URL for every figure.

The [Refresh the Brief data](../../actions/workflows/data.yml) workflow on `main` rebuilds them from live NSE data on weekdays at 18:00 IST and commits them here. The live site reads them from `https://raw.githubusercontent.com/StrokesBard/FINN/data/brief/`.

The branch shares no history with `main`, so the code history stays readable.

`web/vercel.json` is here only to stop Vercel deploying this branch. Vercel reads its settings from the commit it is given, and its root directory is `web`, so the rule has to live on this branch; there is no app here to build.
