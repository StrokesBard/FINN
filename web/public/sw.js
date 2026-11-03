// FINN's service worker. Online, every page comes from the network, so the Brief is
// never staler than the site. Offline (the installed app on a phone with no signal),
// it shows the last copy of each window this device loaded, with that page's styles
// and scripts, instead of the browser's error screen.
const PAGES = "finn-pages-v1";
const ASSETS = "finn-assets-v1";
const STATIC = /\/_next\/static\/[^"'\\\s)?#]+\.(?:js|css|woff2?)/g;

self.addEventListener("install", () => self.skipWaiting());

self.addEventListener("activate", (event) => {
  event.waitUntil((async () => {
    for (const key of await caches.keys()) if (key !== PAGES && key !== ASSETS) await caches.delete(key);
    await self.clients.claim();
  })());
});

self.addEventListener("fetch", (event) => {
  const req = event.request;
  const url = new URL(req.url);
  if (req.method !== "GET" || url.origin !== self.location.origin) return;
  if (req.mode === "navigate") event.respondWith(page(event));
  else if (url.pathname.startsWith("/_next/static/")) event.respondWith(asset(req));
});

async function page(event) {
  try {
    const res = await fetch(event.request);
    // Save a copy without holding up the streamed response.
    if (res.ok) event.waitUntil(keep(event.request, res.clone()));
    return res;
  } catch {
    const cache = await caches.open(PAGES);
    return (await cache.match(event.request)) ?? (await cache.match("/")) ?? offline();
  }
}

// Stores the page and the /_next/static files it references. A new deploy changes those
// file names; pages saved from the old build are then dropped along with their files.
async function keep(req, res) {
  const html = await res.clone().text();
  const wanted = new Set([...html.matchAll(STATIC)].map((m) => new URL(m[0], self.location.origin).href));
  const [pages, assets] = await Promise.all([caches.open(PAGES), caches.open(ASSETS)]);
  const held = new Set((await assets.keys()).map((r) => r.url));
  const sameBuild = [...wanted].every((u) => held.has(u));
  if (!sameBuild) {
    for (const r of await pages.keys()) await pages.delete(r);
    for (const u of held) if (!wanted.has(u)) await assets.delete(u);
    await Promise.all([...wanted].filter((u) => !held.has(u)).map((u) => assets.add(u).catch(() => {})));
  }
  await pages.put(req, res);
}

async function asset(req) {
  const cache = await caches.open(ASSETS);
  const hit = await cache.match(req);
  if (hit) return hit;
  const res = await fetch(req);
  if (res.ok) cache.put(req, res.clone());
  return res;
}

function offline() {
  return new Response(
    '<!doctype html><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">' +
      "<title>FINN · offline</title>" +
      '<body style="font:16px/1.5 system-ui,sans-serif;margin:0;padding:48px 24px;background:#f4f3ee;color:#15171b">' +
      "<h1 style=\"font-size:20px\">You're offline</h1>" +
      "<p>FINN needs a connection the first time it opens. Once you've loaded the Brief, it stays readable offline.</p>",
    { status: 503, headers: { "Content-Type": "text/html; charset=utf-8" } },
  );
}
