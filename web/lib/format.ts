// Display formatting only. Every value arrives from the Brief JSON; nothing here computes a figure.

const IST = "Asia/Kolkata";
const MINUS = "−";

function grouped(n: number, digits: number): string {
  return new Intl.NumberFormat("en-IN", { minimumFractionDigits: digits, maximumFractionDigits: digits }).format(n);
}

/** Rupees -> "1,469" or "219.1" in crore (Indian grouping; one decimal below 1,000 crore). */
export function crore(rupees: number): string {
  const cr = rupees / 1e7;
  return grouped(cr, Math.abs(cr) >= 1000 ? 0 : 1).replace("-", MINUS);
}

/** +12.7% / −9.4%; null means "not meaningful" (missing quarter, or a change from a loss). */
export function pct(p: number | null | undefined): string {
  if (p === null || p === undefined) return "n/m";
  const s = grouped(Math.abs(p), 1);
  return `${p > 0 ? "+" : p < 0 ? MINUS : ""}${s}%`;
}

export function sign(p: number | null | undefined): "pos" | "neg" | "flat" {
  if (p === null || p === undefined || p === 0) return "flat";
  return p > 0 ? "pos" : "neg";
}

export function rupees(n: number): string {
  return `₹${grouped(n, 2)}`;
}

export function count(n: number): string {
  return grouped(Math.round(n), 0);
}

export function multiple(x: number | null): string {
  return x === null ? "n/m" : `${grouped(x, 1)}×`;
}

export function istTime(iso: string): string {
  return new Intl.DateTimeFormat("en-IN", {
    timeZone: IST, day: "numeric", month: "short", hour: "2-digit", minute: "2-digit", hour12: false,
  }).format(new Date(iso));
}

export function istDay(isoDate: string): string {
  return new Intl.DateTimeFormat("en-IN", { timeZone: IST, day: "numeric", month: "short", year: "numeric" })
    .format(new Date(`${isoDate}T12:00:00+05:30`));
}

export function istClock(iso: string): string {
  return new Intl.DateTimeFormat("en-IN", { timeZone: IST, hour: "2-digit", minute: "2-digit", hour12: false })
    .format(new Date(iso));
}

export function istWeekday(iso: string): string {
  return new Intl.DateTimeFormat("en-IN", { timeZone: IST, weekday: "short", day: "numeric", month: "short" })
    .format(new Date(iso));
}
