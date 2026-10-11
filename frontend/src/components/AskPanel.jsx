import { useEffect, useState } from "react";

const SUGGESTIONS = ["Is it safe to travel now?", "Where is the nearest hospital or shelter?", "How can I save water today?"];

// "Ask FloodSense": questions answered by Amazon Bedrock from the live risk, leak and safe-place data
export default function AskPanel({ place, onAsk }) {
  const [q, setQ] = useState("");
  const [turns, setTurns] = useState([]); // { role, text, used?, source? }
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState("");
  useEffect(() => { setTurns([]); setErr(""); }, [place.lat, place.lon]);

  const send = async (text) => {
    const question = (text ?? q).trim();
    if (question.length < 2 || busy) return;
    setBusy(true); setErr(""); setQ("");
    const history = turns.map((t) => ({ role: t.role, text: t.text }));
    setTurns((t) => [...t, { role: "user", text: question }]);
    try {
      const r = await onAsk(question, history);
      setTurns((t) => [...t, { role: "assistant", text: r.answer, used: r.used, source: r.source }]);
    } catch (e) { setErr(e.message); } finally { setBusy(false); }
  };

  return (
    <section className="ask">
      <h2>Ask FloodSense</h2>
      <div className="chips">{turns.length === 0 && SUGGESTIONS.map((s) => (
        <button key={s} className="chip ask-s" onClick={() => send(s)} disabled={busy}>{s}</button>))}</div>
      {turns.map((t, i) => (
        <div key={i} className={`turn ${t.role}`}>
          <p className={t.role === "assistant" ? "advice" : ""}>{t.text}</p>
          {t.role === "assistant" && <p className="hint">Based on live data: {t.used?.join(", ") || "none"}. Source: {t.source}. Estimate, not an official warning.</p>}
        </div>
      ))}
      <form className="row" onSubmit={(e) => { e.preventDefault(); send(); }}>
        <input value={q} maxLength={300} onChange={(e) => setQ(e.target.value)} aria-label={`Ask about ${place.name}`}
          placeholder="Ask in any language, e.g. should I move my car?" />
        <button className="btn" type="submit" disabled={busy}>{busy ? "Thinking…" : "Ask"}</button>
      </form>
      {err && <p className="error">{err}</p>}
    </section>
  );
}
