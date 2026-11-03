import type { Metadata, Viewport } from "next";
import { Inter } from "next/font/google";
import "./globals.css";

const inter = Inter({ subsets: ["latin"], display: "swap" });

export const metadata: Metadata = {
  title: "FINN · Brief",
  description: "What changed across your portfolio, ranked, explained and sourced.",
  applicationName: "FINN",
  appleWebApp: { capable: true, title: "FINN", statusBarStyle: "default" },
};

export const viewport: Viewport = {
  width: "device-width",
  initialScale: 1,
  themeColor: [
    { media: "(prefers-color-scheme: light)", color: "#f4f3ee" },
    { media: "(prefers-color-scheme: dark)", color: "#0d0f12" },
  ],
};

// Applies a saved light/dark choice before first paint; with none saved, CSS follows the system.
const THEME_SCRIPT = `(function(){try{var t=localStorage.getItem("finn:theme");if(t==="light"||t==="dark")document.documentElement.setAttribute("data-theme",t)}catch(e){}})()`;

// Registers the offline copy (public/sw.js), and shows the offline note while the device has no connection.
const SW_SCRIPT = `(function(){var n=document.getElementById("offline-note");function u(){if(n)n.hidden=navigator.onLine}addEventListener("online",u);addEventListener("offline",u);u();if("serviceWorker"in navigator)addEventListener("load",function(){navigator.serviceWorker.register("/sw.js",{scope:"/",updateViaCache:"none"}).catch(function(){})})})()`;

export default function RootLayout({ children }: LayoutProps<"/">) {
  return (
    <html lang="en-IN" className={inter.className} suppressHydrationWarning>
      <head>
        <script dangerouslySetInnerHTML={{ __html: THEME_SCRIPT }} />
      </head>
      <body>
        <p id="offline-note" className="offline-note" role="status" hidden suppressHydrationWarning>
          Offline · showing the last Brief this device loaded
        </p>
        <script dangerouslySetInnerHTML={{ __html: SW_SCRIPT }} />
        {children}
      </body>
    </html>
  );
}
