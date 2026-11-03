import { readFile, stat } from "node:fs/promises";
import path from "node:path";
import { cacheLife } from "next/cache";

// The shape `finn brief` (pipeline/src/finn/brief/build.py) writes. The UI only renders it.

export type Tier = "needs_you" | "worth_knowing" | "routine";

export interface Why {
  text: string;
  evidence: string | null;
}

export interface Filing {
  id: string;
  time: string;
  subject: string;
  headline: string;
  nse_summary: string;
  url: string | null;
  size: string | null;
  category: string;
  tier: Tier;
  reason: string;
  evidence: string;
  symbol?: string;
}

export interface Metric {
  key: string;
  label: string;
  value: number;
  previous: number | null;
  year_ago: number | null;
  qoq_pct: number | null;
  yoy_pct: number | null;
  computed: boolean;
  inputs: { sign: number; element: string; value: number }[];
}

export interface PeriodSource {
  quarter: string;
  quarter_end: string;
  xbrl: string;
  ixbrl: string | null;
  filed: string | null;
  revision: string | null;
}

export interface Results {
  status: "ok" | "pending" | "unavailable" | "unsupported";
  reason?: string;
  kind?: "corporate" | "bank" | "nbfc";
  basis?: string;
  quarter?: string;
  note?: string;
  metrics?: Metric[];
  sources?: Partial<Record<"current" | "previous" | "year_ago", PeriodSource>>;
  gaps?: string[];
}

export interface Move {
  day: string;
  close: number;
  prev_close: number;
  change_pct: number;
  volume: number;
  avg_volume: number | null;
  volume_multiple: number | null;
  source_url: string;
  lookback: { day: string; url: string; volume: number }[];
  price_hit: boolean;
  volume_hit: boolean;
  caveats: string[];
}

export interface Card {
  id: string;
  symbol: string;
  company: string;
  category: string;
  category_label: string;
  tier: Tier;
  time: string;
  headline: string;
  why: Why[];
  filings: Filing[];
  rank: number;
  rank_reason: string;
  related: string[];
  results?: Results;
  profile?: { text: string; page: number; url: string; filing: string } | null;
  moves?: Move[];
}

export interface Brief {
  generated_at: string;
  window: { key: string; label: string; start: string; end: string };
  windows: { key: string; label: string }[];
  portfolio: { name: string; note: string; holdings: { symbol: string; name: string }[] };
  thresholds: { price_move_pct: number; volume_multiple: number; volume_lookback_sessions: number };
  counts: { needs_you: number; worth_knowing: number; routine_filings: number; filings: number; companies: number };
  cards: Card[];
  routine: { count: number; groups: { label: string; reason: string; count: number; items: Filing[] }[] };
  price_check: { sessions: { day: string; url: string; stocks: number }[]; stocks: number; hits: number };
  ranking: { tiers: { key: Tier; label: string; rule: string }[]; category_order: string[] };
  sources: { label: string; url: string }[];
}

export const WINDOWS = ["24h", "3d", "7d"] as const;
export type WindowKey = (typeof WINDOWS)[number];

export function pickWindow(value: string | string[] | undefined): WindowKey {
  return WINDOWS.find((w) => w === value) ?? "24h";
}

// data/brief at the repo root by default; FINN_BRIEF_DIR overrides it.
const BRIEF_DIR = process.env.FINN_BRIEF_DIR ?? path.join(process.cwd(), "..", "data", "brief");

/** The Brief for a window. The file's mtime is part of the cache key, so a rebuild shows up at once. */
export async function getBrief(window: WindowKey): Promise<Brief | null> {
  const file = path.join(BRIEF_DIR, `brief-${window}.json`);
  try {
    return await loadBrief(file, (await stat(file)).mtimeMs);
  } catch {
    return null;
  }
}

async function loadBrief(file: string, mtimeMs: number): Promise<Brief> {
  "use cache";
  cacheLife("hours");
  void mtimeMs; // only here to key the cache
  return JSON.parse(await readFile(file, "utf-8")) as Brief;
}
