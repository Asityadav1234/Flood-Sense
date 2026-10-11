import { Fragment } from "react";
import { COLORS } from "./FloodMap.jsx";

// Bars = rain per week over the last 13 weeks, line = the 10-year average for the same weeks
function Trend({ actual, normal }) {
  const W = 300, H = 110, pad = 4, n = actual.length;
  const max = Math.max(1, ...actual, ...normal);
  const bw = (W - pad * 2) / n;
  const y = (v) => H - 14 - (v / max) * (H - 24);
  const line = normal.map((v, i) => `${pad + bw * (i + 0.5)},${y(v)}`).join(" ");
  return (
    <svg viewBox={`0 0 ${W} ${H}`} role="img" width="100%"
      aria-label="Weekly rainfall for the last 13 weeks compared with the 10-year average">
      {actual.map((v, i) => (
        <rect key={i} x={pad + bw * i + 1.5} width={bw - 3} y={y(v)} height={H - 14 - y(v)} fill="#0f6bbf" rx="2" />
      ))}
      <polyline points={line} fill="none" stroke="#14263a" strokeWidth="2" strokeDasharray="4 3" />
      <text x={pad} y={H - 2} fontSize="10" fill="#4d6277">13 weeks ago</text>
      <text x={W - pad} y={H - 2} fontSize="10" fill="#4d6277" textAnchor="end">this week</text>
    </svg>
  );
}

export default function DroughtPanel({ data, tips }) {
  if (!data) return <p className="hint">Loading drought index…</p>;
  const d = data.data, f = data.factors;
  const rows = [
    ["Rain, last 91 days", `${d.actual_mm} mm (${data.pct_of_normal}% of normal)`],
    ["Usual for this period", `${d.normal_mm} mm`],
    ["Days in a row without rain", d.dry_days],
    ["Evaporation (next 7 days)", `${d.et0_mm_day} mm/day`],
  ];
  return (
    <>
      <div className="badge" style={{ background: COLORS[data.level] }}>{data.level} drought risk</div>
      <span className="score"> score {data.score}</span>
      <p>{data.explanation}</p>
      <dl>{rows.map(([k, v]) => <Fragment key={k}><dt>{k}</dt><dd>{v}</dd></Fragment>)}</dl>
      <h3>Weekly rain vs 10-year average</h3>
      <Trend actual={d.weekly_mm} normal={d.weekly_normal_mm} />
      <p className="legend"><span className="swatch solid" /> this year <span className="swatch dash dark" /> 10-yr average</p>
      <h3>Score breakdown (0 to 1)</h3>
      <dl>
        <dt>Rain deficit</dt><dd>{f.deficit}</dd>
        <dt>Dry spell</dt><dd>{f.dry_spell}</dd>
        <dt>Evaporation</dt><dd>{f.evaporative_demand}</dd>
      </dl>
      <h3>What to do</h3>
      <ul className="tips">{tips.map((t) => <li key={t}>{t}</li>)}</ul>
      <p className="hint">Data: {d.source}</p>
    </>
  );
}
