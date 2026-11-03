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

/** Model output that passed verification: every quote was found in the filing's text. */
export interface AiFact {
  label: string;
  value: string;
  quote: string;
  page: number | null;
}

export interface AiDigest {
  headline: string;
  quote: string;
  page: number | null;
  facts: AiFact[];
  url: string;
  model: string;
}

export interface AiPerson {
  person: string;
  role: string;
  change: string;
  effective_date: string | null;
  reason: string | null;
  quote: string;
  page: number | null;
  top_role: boolean;
  url: string;
  model: string;
}

export interface Llm {
  enabled: boolean;
  reason: string;
  routing: { tier: string; model: string; use: string }[];
  cards_with_extracts: number;
  filings_waiting: number;
  claims_shown: number;
  claims_discarded: number;
  spend: {
    calls: number;
    cost_usd: number;
    since: string | null;
    by_model: Record<string, { calls: number; input_tokens: number; output_tokens: number; cost_usd: number }>;
  };
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
  ai?: { digest: AiDigest | null; people: AiPerson[]; discarded: number };
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
  llm?: Llm;
}

const MODEL_NAMES: Record<string, string> = {
  "claude-haiku-5-5": "Claude Haiku 5.5",
  "claude-opus-5-5": "Claude Opus 5.5",
};

export function modelName(id: string): string {
  return MODEL_NAMES[id] ?? id;
}

export const WINDOWS = ["24h", "3d", "7d"] as const;
export type WindowKey = (typeof WINDOWS)[number];

export function pickWindow(value: string | string[] | undefined): WindowKey {
  return WINDOWS.find((w) => w === value) ?? "24h";
}

// Where the Brief JSON comes from.
// - Remote: FINN_BRIEF_URL, or on Vercel the repo's `data` branch, which the scheduled
//   GitHub workflow rebuilds. Read over HTTPS from GitHub's raw file host.
// - Local (development, `next start` on your machine): data/brief at the repo root, which
//   `python -m finn brief` writes. FINN_BRIEF_DIR overrides the folder.
const REPO_DATA = "https://raw.githubusercontent.com/StrokesBard/FINN/data/brief";
const BRIEF_URL = (process.env.FINN_BRIEF_URL ?? (process.env.VERCEL ? REPO_DATA : "")).replace(/\/+$/, "");
const BRIEF_DIR = process.env.FINN_BRIEF_DIR ?? path.join(process.cwd(), "..", "data", "brief");

export const BRIEF_SOURCE = BRIEF_URL
  ? { kind: "remote" as const, where: BRIEF_URL }
  : { kind: "local" as const, where: BRIEF_DIR };

/** The Brief for a window, or null if it hasn't been built (or can't be reached). */
export async function getBrief(window: WindowKey): Promise<Brief | null> {
  if (BRIEF_URL) {
    return fetchBrief(`${BRIEF_URL}/brief-${window}.json`);
  }
  const file = path.join(BRIEF_DIR, `brief-${window}.json`);
  try {
    // The file's mtime is part of the cache key, so a local rebuild shows up at once.
    return await loadBrief(file, (await stat(file)).mtimeMs);
  } catch {
    return null;
  }
}

async function fetchBrief(url: string): Promise<Brief | null> {
  "use cache";
  cacheLife("minutes"); // the workflow rebuilds daily; GitHub's raw host caches for ~5 minutes anyway
  try {
    const res = await fetch(url, { headers: { Accept: "application/json" } });
    return res.ok ? ((await res.json()) as Brief) : null;
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
