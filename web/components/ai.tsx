import type { AiPerson, Card, Llm } from "@/lib/brief";
import { modelName } from "@/lib/brief";
import { count, usd } from "@/lib/format";

const CHANGE: Record<string, string> = {
  appointed: "Appointed", resigned: "Resigned", retired: "Retired", ceased: "Ceased",
  redesignated: "Redesignated", other: "Changed",
};

function Quote({ text, page, url }: { text: string; page: number | null; url: string }) {
  return (
    <details className="ai-quote">
      <summary>Quote{page ? `, page ${page}` : ""}</summary>
      <blockquote>{text}</blockquote>
      <a href={url} target="_blank" rel="noreferrer">Open the filing</a>
    </details>
  );
}

function Person({ p }: { p: AiPerson }) {
  return (
    <li>
      <p className="ai-person">
        <b>{p.person}</b> · {CHANGE[p.change] ?? p.change} · {p.role}
        {p.effective_date ? <span className="muted"> · effective {p.effective_date}</span> : null}
      </p>
      {p.reason ? <p className="fine">Reason given: {p.reason}</p> : null}
      <Quote text={p.quote} page={p.page} url={p.url} />
    </li>
  );
}

/** Model-read content on a card. Only verified claims arrive here; the label says what that means. */
export function AiBlock({ ai }: { ai: NonNullable<Card["ai"]> }) {
  const model = ai.digest?.model ?? ai.people[0]?.model;
  if (!ai.digest && !ai.people.length) {
    return ai.discarded ? (
      <p className="fine ai-label">
        The model’s reading of this filing was discarded: {ai.discarded} claim{ai.discarded === 1 ? "" : "s"} did not
        quote the document.
      </p>
    ) : null;
  }
  return (
    <section className="ai" aria-label="Read from the filing by a model">
      <p className="ai-label">
        <span className="ai-badge">AI</span> Read from the filing by {model ? modelName(model) : "a model"}. Every line
        quotes the PDF{ai.discarded ? `; ${ai.discarded} claim${ai.discarded === 1 ? " that didn’t was" : "s that didn’t were"} dropped` : ""}.
      </p>
      {ai.digest ? (
        <div className="ai-digest">
          <p className="ai-headline">{ai.digest.headline}</p>
          <Quote text={ai.digest.quote} page={ai.digest.page} url={ai.digest.url} />
          {ai.digest.facts.length ? (
            <dl className="ai-facts">
              {ai.digest.facts.map((f) => (
                <div key={f.label + f.value}>
                  <dt>{f.label}</dt>
                  <dd>
                    {f.value}
                    <Quote text={f.quote} page={f.page} url={ai.digest!.url} />
                  </dd>
                </div>
              ))}
            </dl>
          ) : null}
        </div>
      ) : null}
      {ai.people.length ? <ul className="ai-people">{ai.people.map((p) => <Person key={p.person + p.change} p={p} />)}</ul> : null}
    </section>
  );
}

/** One line under the tally: is model reading on, and what has it cost. */
export function AiStatus({ llm }: { llm: Llm }) {
  if (!llm.enabled) {
    return (
      <p className="ai-status off">
        <span className="ai-badge muted-badge">AI off</span> No API key is set, so nothing on this page was read by a
        model. {llm.filings_waiting ? `${llm.filings_waiting} filing${llm.filings_waiting === 1 ? "" : "s"} whose substance is only in the PDF ${llm.filings_waiting === 1 ? "is" : "are"} linked as-is.` : ""}
        {llm.cards_with_extracts ? " Earlier verified readings are still shown." : ""}
      </p>
    );
  }
  return (
    <p className="ai-status">
      <span className="ai-badge">AI on</span> {modelName(llm.routing[0].model)} reads filing PDFs; claims without a
      matching quote are dropped ({llm.claims_discarded} so far). Spent {usd(llm.spend.cost_usd)} over{" "}
      {count(llm.spend.calls)} call{llm.spend.calls === 1 ? "" : "s"}.
      {llm.filings_waiting ? ` ${llm.filings_waiting} waiting for the next run.` : ""}
    </p>
  );
}

export function AiHow({ llm }: { llm: Llm }) {
  const models = Object.entries(llm.spend.by_model);
  return (
    <details>
      <summary><h2>How AI is used · {llm.enabled ? "on" : "off"}</h2></summary>
      <p className="fine">{llm.reason}</p>
      <ul className="tiers">
        {llm.routing.map((r) => <li key={r.tier}><b>{modelName(r.model)}.</b> {r.use}</li>)}
      </ul>
      <p className="fine">
        Rules still decide every label and the ranking. The model only reads filings whose NSE summary says nothing,
        and every claim must come with a passage copied from the PDF. A claim whose passage isn’t found in the
        document, or that states a number, name, role or change the passage doesn’t, is discarded before it reaches
        this page. Each filing is sent once; the result is cached.
      </p>
      {models.length ? (
        <table className="figures compact">
          <thead><tr><th scope="col">Model</th><th scope="col" className="num">Calls</th><th scope="col" className="num">Tokens in / out</th><th scope="col" className="num">Cost</th></tr></thead>
          <tbody>
            {models.map(([id, m]) => (
              <tr key={id}>
                <th scope="row">{modelName(id)}</th>
                <td className="num">{count(m.calls)}</td>
                <td className="num">{count(m.input_tokens)} / {count(m.output_tokens)}</td>
                <td className="num">{usd(m.cost_usd)}</td>
              </tr>
            ))}
          </tbody>
        </table>
      ) : <p className="fine">No model calls yet.</p>}
    </details>
  );
}
