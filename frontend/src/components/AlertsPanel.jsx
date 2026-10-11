import { useEffect, useState } from "react";

// Email + SMS early-warning alerts via Amazon SNS, translated by Amazon Bedrock into the subscriber's language
export default function AlertsPanel({ place, langs, defaultLang, onSubscribe, onSendNow, busy }) {
  const [contact, setContact] = useState("");
  const [minLevel, setMinLevel] = useState("medium");
  const [lang, setLang] = useState(defaultLang);
  const [msg, setMsg] = useState("");
  useEffect(() => setLang(defaultLang), [defaultLang]);

  const subscribe = async (e) => {
    e.preventDefault();
    const r = await onSubscribe(contact.trim(), minLevel, lang);
    if (r) setMsg(`${r.message} Alerts will arrive in ${r.lang}.`);
  };
  const sendNow = async () => {
    const r = await onSendNow();
    if (!r) return;
    const where = r.deliveries.map((d) => d.lang).join(", ");
    setMsg(r.deliveries[0].mode === "local"
      ? `Local mode: alert built in ${where}. Example: "${r.deliveries[r.deliveries.length - 1].subject}"`
      : `Alert published to Amazon SNS in: ${where}.`);
  };

  return (
    <section className="alerts">
      <h2>Early-warning alerts (email or SMS)</h2>
      <p className="hint">Get alerts when risk rises for {place.name}, in your language. A scheduled Amazon EventBridge job
        re-checks every 3 hours, Amazon Bedrock translates, and Amazon SNS delivers, only when things get worse.</p>
      <form className="row" onSubmit={subscribe}>
        <input required value={contact} onChange={(e) => setContact(e.target.value)} placeholder="Email, or phone like +919812345678" aria-label="Email or phone number for alerts" />
        <select aria-label="Alert language" value={lang} onChange={(e) => setLang(e.target.value)}>
          {langs.map((l) => <option key={l}>{l}</option>)}
        </select>
        <select aria-label="Alert level" value={minLevel} onChange={(e) => setMinLevel(e.target.value)}>
          <option value="medium">Medium and high</option>
          <option value="high">High only</option>
        </select>
        <button className="btn" type="submit" disabled={!!busy}>Subscribe</button>
      </form>
      <button className="link mt" onClick={sendNow} disabled={!!busy}>Send an alert now (demo)</button>
      {msg && <p className="hint">{msg}</p>}
    </section>
  );
}
