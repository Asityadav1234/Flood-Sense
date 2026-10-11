import { COLORS } from "./FloodMap.jsx";

export const KIND_LABELS = {
  drip: "Dripping tap or joint (~20 L/day)",
  steady: "Steady stream (~2,000 L/day)",
  overflow: "Overflowing tank (~1,000 L/day)",
  burst: "Burst or gushing pipe (~50,000 L/day)",
};

export default function LeakPanel({ data, draft, kind, setKind, note, setNote, photo, setPhoto, onSubmit, onCancel, onSeed, onGo, busy }) {
  const s = data?.summary;
  const im = data?.impact;
  const list = (data?.leaks || []).slice(0, 5);
  return (
    <>
      <h2>Water leaks (crowd-sourced)</h2>
      <p className="hint">Click the map where you see a leak. Reports are stored in Amazon DynamoDB and ranked by how much
        water they waste, and higher when the area is also dry.</p>
      {draft && (
        <div className="form">
          <label>Type of leak
            <select value={kind} onChange={(e) => setKind(e.target.value)}>
              {Object.entries(KIND_LABELS).map(([k, v]) => <option key={k} value={k}>{v}</option>)}
            </select>
          </label>
          <label>Note (optional)
            <input value={note} maxLength={200} onChange={(e) => setNote(e.target.value)} placeholder="e.g. near the bus stop" />
          </label>
          <label>Photo (optional, checked by Amazon Rekognition)
            <input type="file" accept="image/*" capture="environment" onChange={(e) => setPhoto(e.target.files?.[0] || null)} />
          </label>
          {photo && <p className="hint">{photo.name}: it is resized on your device, uploaded to a private S3 bucket and checked for water and a pipe.</p>}
          <div className="row">
            <button className="btn" onClick={onSubmit} disabled={!!busy}>Report this leak</button>
            <button className="link" onClick={onCancel}>Cancel</button>
          </div>
        </div>
      )}
      {s && (
        <>
          <div className="counts">
            <div><b>{s.open}</b><span>open leaks</span></div>
            <div><b>{s.lpd_total.toLocaleString()}</b><span>litres lost / day</span></div>
            <div><b>{s.people_equivalent.toLocaleString()}</b><span>people's daily need</span></div>
          </div>
          <p className="hint">{s.assumption}</p>
        </>
      )}
      {im && im.fixed > 0 && (
        <div className="impact">
          <h2>Impact so far</h2>
          <div className="counts">
            <div><b>{im.fixed}</b><span>leaks fixed</span></div>
            <div><b>{im.lpd_stopped.toLocaleString()}</b><span>litres / day stopped</span></div>
            <div><b>{im.litres_saved.toLocaleString()}</b><span>litres saved</span></div>
          </div>
          <p className="hint">That is about {im.tanker_trips} water-tanker trips (10,000 L each). Estimates from the leak-size assumptions above.</p>
        </div>
      )}
      {list.length > 0 ? (
        <>
          <h2 className="mt">Fix first</h2>
          <ol className="hot">
            {list.map((l) => (
              <li key={l.id}><button className="link" onClick={() => onGo([l.lat, l.lon])}>
                <i style={{ background: COLORS[l.level] }} />{l.label} · {l.lpd.toLocaleString()} L/day{l.photo_check?.status === "verified" ? " · photo verified" : ""}</button></li>
            ))}
          </ol>
        </>
      ) : s && <p className="hint">No open leaks in this area yet. Report one, or load demo reports.</p>}
      <button className="link mt" onClick={onSeed} disabled={!!busy}>Load demo reports around here</button>
    </>
  );
}
