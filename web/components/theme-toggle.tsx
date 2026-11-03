"use client";

// Flips between light and dark and remembers the choice. Until the user picks,
// the page follows the system setting (see globals.css).
export function ThemeToggle() {
  function toggle() {
    const root = document.documentElement;
    const current = root.dataset.theme ??
      (window.matchMedia("(prefers-color-scheme: dark)").matches ? "dark" : "light");
    const next = current === "dark" ? "light" : "dark";
    root.dataset.theme = next;
    try {
      localStorage.setItem("finn:theme", next);
    } catch {}
  }
  return (
    <button type="button" className="icon-button" onClick={toggle} aria-label="Switch light or dark mode">
      <svg className="icon-sun" viewBox="0 0 24 24" width="20" height="20" aria-hidden="true">
        <circle cx="12" cy="12" r="4.2" fill="none" stroke="currentColor" strokeWidth="1.8" />
        <path d="M12 2.5v2.2M12 19.3v2.2M2.5 12h2.2M19.3 12h2.2M5.3 5.3l1.6 1.6M17.1 17.1l1.6 1.6M5.3 18.7l1.6-1.6M17.1 6.9l1.6-1.6"
          stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" />
      </svg>
      <svg className="icon-moon" viewBox="0 0 24 24" width="20" height="20" aria-hidden="true">
        <path d="M20 14.6A8.2 8.2 0 0 1 9.4 4a8.2 8.2 0 1 0 10.6 10.6Z" fill="none" stroke="currentColor"
          strokeWidth="1.8" strokeLinejoin="round" />
      </svg>
    </button>
  );
}
