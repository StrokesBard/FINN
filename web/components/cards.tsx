import type { Card, Filing, Metric, Move, Results } from "@/lib/brief";
import { count, crore, istDay, istTime, multiple, pct, rupees, sign } from "@/lib/format";
import { CardShell } from "./triage";

const ELEMENT_LABEL: Record<string, string> = {
  ProfitBeforeTax: "PBT",
  FinanceCosts: "finance costs",
  DepreciationDepletionAndAmortisationExpense: "depreciation & amortisation",
  DepreciationAndAmortisationExpense: "depreciation & amortisation",
  OtherIncome: "other income",
  InterestEarned: "interest earned",
  InterestExpended: "interest expended",
};

function Change({ value }: { value: number | null }) {
  return <span className={`chg ${sign(value)}`}>{pct(value)}</span>;
}

function CardHead({ card }: { card: Card }) {
  return (
    <header className="card-head">
      <div className="who">
        <span className="ticker">{card.symbol}</span>
        <span className="company">{card.company}</span>
      </div>
      <time dateTime={card.time} className="when">{istTime(card.time)}</time>
    </header>
  );
}

function ResultsTable({ r }: { r: Results }) {
  if (r.status !== "ok" || !r.metrics) {
    return <p className="note pending">{r.reason}</p>;
  }
  const s = r.sources ?? {};
  return (
    <div className="results">
      <table className="figures">
        <caption className="sr-only">Headline numbers, {r.quarter}, in ₹ crore</caption>
        <thead>
          <tr>
            <th scope="col">₹ crore</th>
            <th scope="col" className="num">{r.quarter}</th>
            <th scope="col" className="num">QoQ</th>
            <th scope="col" className="num">YoY</th>
          </tr>
        </thead>
        <tbody>
          {r.metrics.map((m) => (
            <tr key={m.key}>
              <th scope="row">{m.label}{m.computed ? <sup>*</sup> : null}</th>
              <td className="num">{crore(m.value)}</td>
              <td className="num"><Change value={m.qoq_pct} /></td>
              <td className="num"><Change value={m.yoy_pct} /></td>
            </tr>
          ))}
        </tbody>
      </table>
      <p className="fine">
        {r.basis} · QoQ vs {s.previous?.quarter ?? "previous quarter"}, YoY vs {s.year_ago?.quarter ?? "year-ago quarter"}
        {" · "}* {r.note}
      </p>
      {r.gaps?.map((g) => <p key={g} className="fine warn">{g}</p>)}
      <details className="more">
        <summary>All three quarters and the inputs</summary>
        <table className="figures compact">
          <thead>
            <tr>
              <th scope="col">₹ crore</th>
              <th scope="col" className="num">{s.current?.quarter}</th>
              <th scope="col" className="num">{s.previous?.quarter ?? "—"}</th>
              <th scope="col" className="num">{s.year_ago?.quarter ?? "—"}</th>
            </tr>
          </thead>
          <tbody>
            {r.metrics.map((m) => (
              <tr key={m.key}>
                <th scope="row">{m.label}</th>
                <td className="num">{crore(m.value)}</td>
                <td className="num">{m.previous === null ? "—" : crore(m.previous)}</td>
                <td className="num">{m.year_ago === null ? "—" : crore(m.year_ago)}</td>
              </tr>
            ))}
          </tbody>
        </table>
        {r.metrics.filter((m) => m.computed).map((m) => <Inputs key={m.key} m={m} quarter={r.quarter ?? ""} />)}
      </details>
    </div>
  );
}

function Inputs({ m, quarter }: { m: Metric; quarter: string }) {
  return (
    <p className="fine">
      {m.label} {quarter} = {m.inputs.map((i, n) => (
        <span key={i.element}>
          {n === 0 ? (i.sign < 0 ? "− " : "") : i.sign < 0 ? " − " : " + "}
          {ELEMENT_LABEL[i.element] ?? i.element} {crore(i.value)}
        </span>
      ))} = {crore(m.value)}
    </p>
  );
}

function MoveLine({ m }: { m: Move }) {
  return (
    <div className="move">
      <p className="move-main">
        <span className="move-day">{istDay(m.day)}</span>
        <span>close {rupees(m.close)}</span>
        <Change value={m.change_pct} />
        <span className="muted">vs {rupees(m.prev_close)}</span>
      </p>
      <p className="move-vol">
        Volume {count(m.volume)} shares
        {m.volume_multiple !== null
          ? <> · <strong className={m.volume_hit ? "hit" : undefined}>{multiple(m.volume_multiple)}</strong> the {m.lookback.length}-session average of {count(m.avg_volume ?? 0)}</>
          : null}
      </p>
      {m.caveats.map((c) => <p key={c} className="fine warn">{c}</p>)}
    </div>
  );
}

function Profile({ p }: { p: NonNullable<Card["profile"]> }) {
  return (
    <figure className="profile">
      <blockquote>{p.text}</blockquote>
      <figcaption>
        From the filing itself, page {p.page} · <a href={p.url} target="_blank" rel="noreferrer">open PDF</a>
      </figcaption>
    </figure>
  );
}

function WhyHere({ card }: { card: Card }) {
  return (
    <details className="more why">
      <summary>Why it’s here</summary>
      <ul>
        {card.why.map((w) => (
          <li key={w.text}>
            {w.text}
            {w.evidence ? <span className="evidence">{w.evidence}</span> : null}
          </li>
        ))}
        <li>{card.rank_reason}</li>
        {card.related.length ? <li>Also in this Brief for {card.symbol}: {card.related.join(", ")}.</li> : null}
      </ul>
    </details>
  );
}

function FilingLink({ f }: { f: Filing }) {
  return (
    <li>
      <span className="src-what">{f.subject}</span>
      <span className="src-when">{istTime(f.time)}</span>
      {f.url
        ? <a href={f.url} target="_blank" rel="noreferrer">PDF{f.size ? ` · ${f.size}` : ""}</a>
        : <span className="muted">no attachment</span>}
    </li>
  );
}

function Sources({ card }: { card: Card }) {
  const r = card.results;
  const moves = card.moves ?? [];
  return (
    <details className="more sources">
      <summary>Sources</summary>
      <ul className="src-list">
        {card.filings.map((f) => <FilingLink key={f.id} f={f} />)}
        {r?.sources
          ? (["current", "previous", "year_ago"] as const).map((k) => {
              const s = r.sources?.[k];
              return s ? (
                <li key={k}>
                  <span className="src-what">Results XBRL, {s.quarter}{s.revision && s.revision !== "Original" ? ` (${s.revision})` : ""}</span>
                  <span className="src-when">{s.filed ?? ""}</span>
                  <span>
                    {s.ixbrl ? <a href={s.ixbrl} target="_blank" rel="noreferrer">view</a> : null}
                    {s.ixbrl ? " · " : null}
                    <a href={s.xbrl} target="_blank" rel="noreferrer">XML</a>
                  </span>
                </li>
              ) : null;
            })
          : null}
        {moves.map((m) => (
          <li key={m.day}>
            <span className="src-what">NSE bhavcopy {istDay(m.day)}</span>
            <span className="src-when">close, previous close, volume</span>
            <a href={m.source_url} target="_blank" rel="noreferrer">ZIP</a>
          </li>
        ))}
        {moves.filter((m) => m.lookback.length).map((m) => (
          <li key={`lb-${m.day}`} className="lookback">
            <details>
              <summary>
                {m.lookback.length} earlier daily files for the average ({istDay(m.lookback[0].day)} – {istDay(m.lookback[m.lookback.length - 1].day)})
              </summary>
              <ol>
                {m.lookback.map((l) => (
                  <li key={l.day}>
                    <a href={l.url} target="_blank" rel="noreferrer">{istDay(l.day)}</a>
                    <span className="num">{count(l.volume)}</span>
                  </li>
                ))}
              </ol>
            </details>
          </li>
        ))}
      </ul>
    </details>
  );
}

export function NeedsCard({ card }: { card: Card }) {
  return (
    <CardShell id={card.id} label={`${card.symbol} · ${card.category_label}`}>
      <CardHead card={card} />
      <p className="kicker">{card.category_label}</p>
      <h3 className="headline">{card.headline}</h3>
      {card.results ? <ResultsTable r={card.results} /> : null}
      {card.moves?.length ? (
        <div className="market">
          {card.category !== "price_move" ? <p className="kicker small">Market reaction</p> : null}
          {card.moves.map((m) => <MoveLine key={m.day} m={m} />)}
        </div>
      ) : null}
      {card.profile ? <Profile p={card.profile} /> : null}
      {card.category !== "results" && card.filings[0]?.nse_summary && card.filings[0].headline !== card.headline
        ? <p className="summary">{card.filings[0].headline}</p> : null}
      <WhyHere card={card} />
      <Sources card={card} />
    </CardShell>
  );
}

export function WorthCard({ card }: { card: Card }) {
  return (
    <CardShell id={card.id} label={`${card.symbol} · ${card.category_label}`}>
      <CardHead card={card} />
      <p className="kicker">{card.category_label}</p>
      <h3 className="headline small">{card.headline}</h3>
      {card.results ? <ResultsTable r={card.results} /> : null}
      {card.profile ? <Profile p={card.profile} /> : null}
      <WhyHere card={card} />
      <Sources card={card} />
    </CardShell>
  );
}
