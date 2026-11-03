import Link from "next/link";
import { Suspense } from "react";
import { AiHow, AiStatus } from "@/components/ai";
import { NeedsCard, WorthCard } from "@/components/cards";
import { ThemeToggle } from "@/components/theme-toggle";
import { DoneRestorer } from "@/components/triage";
import { BRIEF_SOURCE, type Brief, getBrief, pickWindow } from "@/lib/brief";
import { istDay, istTime, istWeekday } from "@/lib/format";

export default function Page(props: PageProps<"/">) {
  return (
    <div className="shell">
      <header className="topbar">
        <div className="brand">
          <span className="logo" aria-hidden="true">F</span>
          <span className="brand-name">FINN</span>
          <span className="brand-sep" aria-hidden="true">/</span>
          <span className="brand-page">Brief</span>
        </div>
        <ThemeToggle />
      </header>
      <Suspense fallback={<Skeleton />}>
        <BriefScreen searchParams={props.searchParams} />
      </Suspense>
    </div>
  );
}

async function BriefScreen({ searchParams }: { searchParams: PageProps<"/">["searchParams"] }) {
  const key = pickWindow((await searchParams).w);
  const brief = await getBrief(key);
  if (!brief) {
    return (
      <main className="empty">
        {BRIEF_SOURCE.kind === "remote" ? (
          <>
            <p>The Brief couldn’t be loaded right now.</p>
            <p className="fine">It is read from <code>{BRIEF_SOURCE.where}</code>. Try again in a minute.</p>
          </>
        ) : (
          <>
            <p>No Brief has been built yet.</p>
            <p className="fine">Run <code>python -m finn collect</code> and then <code>python -m finn brief</code> from the repo root.</p>
          </>
        )}
      </main>
    );
  }
  const needs = brief.cards.filter((c) => c.tier === "needs_you");
  const worth = brief.cards.filter((c) => c.tier === "worth_knowing");
  const t = brief.thresholds;
  return (
    <main>
      <section className="intro" aria-label="Time window">
        <p className="date">{istWeekday(brief.generated_at)}</p>
        <nav className="windows" aria-label="Choose the time window">
          {brief.windows.map((w) => (
            <Link key={w.key} href={w.key === "24h" ? "/" : `/?w=${w.key}`} className="window"
              aria-current={w.key === brief.window.key ? "page" : undefined}>
              {w.key === "24h" ? "24 hours" : w.key === "3d" ? "3 days" : "7 days"}
            </Link>
          ))}
        </nav>
        <p className="fine">
          {istTime(brief.window.start)} → {istTime(brief.window.end)} IST · built {istTime(brief.generated_at)}
        </p>
      </section>

      <section className="tally" aria-label="Summary">
        <a href="#needs" className="stat strong"><b>{brief.counts.needs_you}</b><span>need you</span></a>
        <a href="#worth" className="stat"><b>{brief.counts.worth_knowing}</b><span>worth knowing</span></a>
        <a href="#routine" className="stat quiet"><b>{brief.counts.routine_filings}</b><span>routine, hidden</span></a>
      </section>
      <p className="checked fine">
        Checked {brief.counts.filings} filings from {brief.counts.companies} of your {brief.price_check.stocks} companies,
        and NSE closing prices for {brief.price_check.sessions.length === 1 ? "the session of " : ""}
        {brief.price_check.sessions.map((s) => istDay(s.day)).join(", ") || "no session in this window"}.
        Thresholds: price ±{t.price_move_pct}%, volume {t.volume_multiple}× the {t.volume_lookback_sessions}-session average.
      </p>
      {brief.llm ? <AiStatus llm={brief.llm} /> : null}

      <section id="needs" className="stack needs" aria-labelledby="needs-h">
        <h2 id="needs-h">Needs you</h2>
        {needs.map((c) => <NeedsCard key={c.id} card={c} />)}
        {needs.length ? <p className="all-clear">All clear. Everything that needed you in this window is done.</p>
          : <p className="all-clear show">Nothing in this window needs you.</p>}
        {brief.price_check.hits === 0 && brief.price_check.sessions.length
          ? <p className="fine">No stock crossed a price or volume threshold in this window.</p> : null}
      </section>

      <section id="worth" className="stack worth" aria-labelledby="worth-h">
        <h2 id="worth-h">Worth knowing</h2>
        {worth.map((c) => <WorthCard key={c.id} card={c} />)}
        {worth.length ? null : <p className="fine">Nothing else in this window.</p>}
      </section>
      <DoneRestorer />

      <section id="routine" className="receipt" aria-labelledby="routine-h">
        <details>
          <summary>
            <h2 id="routine-h">{brief.routine.count} routine filings, hidden</h2>
            <span className="fine">What was left out, and why</span>
          </summary>
          {brief.routine.groups.map((g) => (
            <div key={g.label} className="receipt-group">
              <h3>{g.label} <span className="muted">· {g.count}</span></h3>
              <p className="fine">{g.reason}</p>
              <ul>
                {g.items.map((f) => (
                  <li key={f.id}>
                    <span className="ticker small">{f.symbol}</span>
                    <span className="receipt-what">{f.headline}</span>
                    {f.url ? <a href={f.url} target="_blank" rel="noreferrer">PDF</a> : null}
                  </li>
                ))}
              </ul>
            </div>
          ))}
        </details>
      </section>

      <HowItWorks brief={brief} />
    </main>
  );
}

function HowItWorks({ brief }: { brief: Brief }) {
  return (
    <section className="how" aria-label="How this Brief is built">
      <details>
        <summary><h2>How this Brief ranks</h2></summary>
        <ol className="tiers">
          {brief.ranking.tiers.map((t) => <li key={t.key}><b>{t.label}.</b> {t.rule}</li>)}
        </ol>
        <p className="fine">Inside a tier, cards sort by category in this order, then newest first:</p>
        <p className="order">{brief.ranking.category_order.join(" › ")}</p>
        <p className="fine">
          Filings from one company about the same thing are grouped into one card. A company’s unusual move goes
          inside its card when it has one. Labels come from rules over NSE’s own subject line and summary, so each
          card can say which words it matched. No model decides a label or a rank.
        </p>
      </details>
      {brief.llm ? <AiHow llm={brief.llm} /> : null}
      <details>
        <summary><h2>Your portfolio · {brief.portfolio.holdings.length}</h2></summary>
        <p className="fine">{brief.portfolio.note}</p>
        <ul className="holdings">
          {brief.portfolio.holdings.map((h) => <li key={h.symbol}><span className="ticker small">{h.symbol}</span> {h.name}</li>)}
        </ul>
      </details>
      <footer className="sources-foot fine">
        Data: {brief.sources.map((s, i) => (
          <span key={s.url}>{i ? " · " : ""}<a href={s.url} target="_blank" rel="noreferrer">{s.label}</a></span>
        ))}. Primary sources only.
      </footer>
    </section>
  );
}

function Skeleton() {
  return (
    <main aria-busy="true">
      <div className="skeleton bar" />
      <div className="skeleton tally-s" />
      <div className="skeleton card-s" />
      <div className="skeleton card-s" />
    </main>
  );
}
