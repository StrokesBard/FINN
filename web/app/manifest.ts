import type { MetadataRoute } from "next";

// Served at /manifest.webmanifest (Next's manifest file convention). Makes the Brief
// installable on a phone, and is what PWABuilder reads to package the Android app.
export default function manifest(): MetadataRoute.Manifest {
  return {
    id: "/",
    name: "FINN · Brief",
    short_name: "FINN",
    description: "What changed across your portfolio, ranked, explained and sourced.",
    start_url: "/",
    scope: "/",
    display: "standalone",
    orientation: "portrait",
    background_color: "#f4f3ee",
    theme_color: "#15171b",
    categories: ["finance", "business", "news"],
    icons: [
      { src: "/icons/icon-192.png", sizes: "192x192", type: "image/png", purpose: "any" },
      { src: "/icons/icon-512.png", sizes: "512x512", type: "image/png", purpose: "any" },
      { src: "/icons/maskable-192.png", sizes: "192x192", type: "image/png", purpose: "maskable" },
      { src: "/icons/maskable-512.png", sizes: "512x512", type: "image/png", purpose: "maskable" },
    ],
  };
}
