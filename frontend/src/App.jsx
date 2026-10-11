import { Fragment, useEffect, useMemo, useState } from "react";
import FloodMap, { boxAround, COLORS, SAFE_COLORS } from "./components/FloodMap.jsx";
import DroughtPanel from "./components/DroughtPanel.jsx";
import LeakPanel from "./components/LeakPanel.jsx";
import AlertsPanel from "./components/AlertsPanel.jsx";
import AskPanel from "./components/AskPanel.jsx";
import { askFloodSense, fixLeak, getAdvisory, getBriefing, getDrought, getFloodRisk, getHeatRisk, getHeatZones, getLeaks,
         getRiskZones, getSafePlaces, getSafeRoute, reportLeak, searchPlaces, seedLeaks, sendAlertNow, subscribeAlerts, uploadPhoto } from "./services/api.js";

const km = (m) => (m / 1000).toFixed(1) + " km";
const HAZARDS = [["flood", "Flood"], ["heat", "Heatwave"], ["drought", "Drought"], ["leak", "Leaks"]];
const CITIES = [
  { name: "Jaipur, India", lat: 26.9124, lon: 75.7873 }, { name: "Mumbai, India", lat: 19.076, lon: 72.8777 },
  { name: "Delhi, India", lat: 28.6139, lon: 77.209 }, { name: "Chennai, India", lat: 13.0827, lon: 80.2707 },
  { name: "Kolkata, India", lat: 22.5726, lon: 88.3639 }, { name: "Bengaluru, India", lat: 12.9716, lon: 77.5946 },
  { name: "Hyderabad, India", lat: 17.385, lon: 78.4867 }, { name: "Guwahati, India", lat: 26.1445, lon: 91.7362 },
  { name: "Jakarta, Indonesia", lat: -6.2088, lon: 106.8456 }, { name: "Lagos, Nigeria", lat: 6.5244, lon: 3.3792 },
  { name: "London, UK", lat: 51.5074, lon: -0.1278 }, { name: "New Orleans, USA", lat: 29.9511, lon: -90.0715 },
];
const LANGS = ["English", "Hindi", "Tamil", "Bengali", "Marathi", "Telugu", "Gujarati", "Kannada", "Malayalam", "Punjabi",
               "Urdu", "Spanish", "French", "Portuguese", "Arabic", "Indonesian", "Swahili"];
// Scenario presets per hazard: [label, value]; 0 = live data
const PRESETS = {
  flood: [["Live", 0], ["Light", 30], ["Heavy", 80], ["Extreme", 150]],
  heat: [["Live", 0], ["Hot 41°", 41], ["Heatwave 45°", 45], ["Severe 48°", 48]],
  drought: [["Live", 0], ["Normal", 100], ["Dry 60%", 60], ["Severe 30%", 30]],
};
const SLIDER = {
  flood: { min: 0, max: 150, step: 10, label: "Simulated rainfall in 24 hours" },
  heat: { min: 0, max: 50, step: 1, label: "Simulated afternoon temperature" },
  drought: { min: 0, max: 100, step: 10, label: "Simulated rainfall as percent of normal" },
};
const scnText = (h, v) => v === 0 ? "Live forecast" : {
  flood: `Simulated storm: ${v} mm in 24 h`,
  heat: `Simulated heatwave: ${v}°C afternoon air temperature`,
  drought: `Simulated: ${v}% of normal rainfall over the last 3 months`,
}[h];
const TIPS = {
  flood: {
    low: ["Normal travel is fine.", "Keep an eye on weather updates."],
    medium: ["Avoid underpasses and low roads if rain continues.", "Park vehicles on higher ground.", "Charge your phone."],
    high: ["Avoid travelling through this area in heavy rain.", "Move vehicles and valuables to higher ground.", "Follow official advisories."],
  },
  heat: {
    low: ["Normal activity is fine.", "Drink water regularly."],
    medium: ["Avoid outdoor work from noon to 4 pm.", "Drink water often and wear light clothing.", "Check on elderly neighbours."],
    high: ["Stay indoors in the hottest hours.", "Drink water and ORS regularly.", "Never leave children or pets in parked vehicles.", "Seek medical help for dizziness, confusion or very hot dry skin."],
  },
  drought: {
    low: ["Normal water use is fine.", "Fix leaking taps and pipes anyway."],
    medium: ["Fix leaks.", "Water plants and wash vehicles in the early morning or evening only.", "Store some drinking water."],
    high: ["Cut non-essential water use.", "Fix every leak.", "Store drinking water.", "Follow municipal water-supply notices."],
  },
};
const COPY = {
  flood: "Click anywhere on the map to see its flood risk. The colour grid covers the dashed area.",
  heat: "Click anywhere on the map to see its heat risk. Spots far from parks and water score higher.",
};
const NO_GRID = (h) => h === "drought" || h === "leak";

export default function App() {
  const [hazard, setHazard] = useState("flood");
  const [scn, setScn] = useState({ flood: 0, heat: 0, drought: 0 }); // 0 = live data
  const [drought, setDrought] = useState(null);
  const [place, setPlace] = useState(CITIES[0]);
  const center = [place.lat, place.lon];
  const area = useMemo(() => boxAround([place.lat, place.lon]), [place.lat, place.lon]);
  const [map, setMap] = useState(null);
  const [query, setQuery] = useState("");
  const [found, setFound] = useState([]);
  const [lang, setLang] = useState("English");
  const [brief, setBrief] = useState(null);
  const [leakData, setLeakData] = useState(null);
  const [draft, setDraft] = useState(null);
  const [leakKind, setLeakKind] = useState("steady");
  const [leakNote, setLeakNote] = useState("");
  const [leakPhoto, setLeakPhoto] = useState(null);
  const val = scn[hazard] ?? 0;
  const rainMm = scn.flood; // routing is flood-only
  const [mode, setMode] = useState("inspect");
  const [showZones, setShowZones] = useState(true);
  const [zones, setZones] = useState(null);
  const [point, setPoint] = useState(null);
  const [risk, setRisk] = useState(null);
  const [advice, setAdvice] = useState(null);
  const [safe, setSafe] = useState(null);
  const [focus, setFocus] = useState(null);
  const [start, setStart] = useState(null);
  const [end, setEnd] = useState(null);
  const [route, setRoute] = useState(null);
  const [busy, setBusy] = useState("");
  const [error, setError] = useState("");

  const run = async (label, fn) => {
    setBusy(label); setError("");
    try { await fn(); } catch (e) { setError(e.message); } finally { setBusy(""); }
  };

  // Switching hazard or city clears everything that belonged to the previous one
  useEffect(() => {
    setZones(null); setDrought(null); setPoint(null); setRisk(null); setAdvice(null); setSafe(null);
    setStart(null); setEnd(null); setRoute(null); setError(""); setDraft(null);
  }, [hazard, place]);
  useEffect(() => { setBrief(null); setLeakData(null); }, [place]);

  const loadLeaks = () => run("Loading leak reports", async () => setLeakData(await getLeaks(area)));
  useEffect(() => { if (hazard === "leak") loadLeaks(); }, [hazard, place]);

  // Reload map zones / drought index when the hazard or its scenario changes (debounced while dragging the slider)
  useEffect(() => {
    let live = true;
    if (hazard === "leak") return;
    const t = setTimeout(() => run(hazard === "drought" ? "Loading drought index" : "Loading risk zones", async () => {
      if (hazard === "flood") { const z = await getRiskZones(area, val); if (live) setZones(z); }
      else if (hazard === "heat") { const z = await getHeatZones(area, val); if (live) setZones(z); }
      else { const d = await getDrought(place.lat, place.lon, val); if (live) setDrought(d); }
    }), 400);
    return () => { live = false; clearTimeout(t); };
  }, [hazard, val, place]);

  // Risk at the clicked spot (ignores answers that arrive after the user clicked elsewhere)
  useEffect(() => {
    if (!point || NO_GRID(hazard)) return;
    let live = true;
    run("Checking this spot", async () => {
      const r = hazard === "heat" ? await getHeatRisk(point[0], point[1], val) : await getFloodRisk(point[0], point[1], val);
      if (live) setRisk(r);
    });
    return () => { live = false; };
  }, [point, val, hazard]);

  useEffect(() => {
    if (!(start && end)) return;
    let live = true;
    run("Finding routes", async () => {
      const r = await getSafeRoute(start, end, rainMm);
      if (live) setRoute(r);
    });
    return () => { live = false; };
  }, [start, end, rainMm]);

  const pickPoint = (p) => { setPoint(p); setRisk(null); setAdvice(null); setSafe(null); };

  const onMapClick = (p) => {
    if (hazard === "drought") return;
    if (hazard === "leak") return setDraft(p);
    if (mode === "inspect") return pickPoint(p);
    if (!start || (start && end)) { setStart(p); setEnd(null); setRoute(null); }
    else setEnd(p);
  };

  const askAdvice = (p = point) => run("Asking Amazon Bedrock", async () => {
    setAdvice(await getAdvisory(p[0], p[1], hazard, val, place.name, lang));
  });

  const findSafe = () => run("Finding safe places", async () => setSafe(await getSafePlaces(point[0], point[1])));
  const km1 = (m) => (m >= 1000 ? `${(m / 1000).toFixed(1)} km` : `${Math.round(m / 10) * 10} m`);

  const choosePlace = (p) => {
    setPlace(p); setFound([]); setQuery(""); setMode("inspect"); setFocus({ pos: [p.lat, p.lon], zoom: 13, t: Date.now() });
  };
  const doSearch = (e) => {
    e.preventDefault();
    if (query.trim().length < 2) return;
    run("Searching", async () => {
      const r = await searchPlaces(query.trim());
      if (!r.length) setError("No city found. Try a different spelling.");
      setFound(r);
    });
  };
  const analyzeHere = () => {
    if (!map) return;
    const c = map.getCenter();
    choosePlace({ name: `Map area (${c.lat.toFixed(3)}, ${c.lng.toFixed(3)})`, lat: c.lat, lon: c.lng });
  };
  const askBrief = () => run("Building briefing", async () => setBrief(await getBriefing(place.lat, place.lon, scn, place.name, lang)));

  // returns the API result (or undefined on error) so the panel can show a message
  const subscribe = async (contact, minLevel, alertLang) => {
    setBusy("Subscribing"); setError("");
    try { return await subscribeAlerts(contact, place.lat, place.lon, place.name, minLevel, alertLang); }
    catch (e) { setError(e.message); } finally { setBusy(""); }
  };
  const alertNow = async () => {
    setBusy("Sending alert"); setError("");
    try { return await sendAlertNow(place.lat, place.lon, scn, place.name); }
    catch (e) { setError(e.message); } finally { setBusy(""); }
  };

  const submitLeak = () => run("Saving report", async () => {
    let key = "";
    if (leakPhoto) {
      try { key = await uploadPhoto(leakPhoto); }
      catch (e) { setError(`${e.message} The leak was reported without the photo.`); }
    }
    await reportLeak(draft[0], draft[1], leakKind, leakNote, key);
    setDraft(null); setLeakNote(""); setLeakPhoto(null); setLeakData(await getLeaks(area));
  });
  const markFixed = (id) => run("Updating", async () => { await fixLeak(id); setLeakData(await getLeaks(area)); });
  const loadDemoLeaks = () => run("Adding demo reports", async () => { await seedLeaks(place.lat, place.lon); setLeakData(await getLeaks(area)); });

  const useMyLocation = () => {
    if (!navigator.geolocation) return setError("Location is not available in this browser.");
    navigator.geolocation.getCurrentPosition(
      (pos) => {
        const p = [pos.coords.latitude, pos.coords.longitude];
        setError(""); setPlace({ name: "My location", lat: p[0], lon: p[1] }); setMode("inspect");
        setFocus({ pos: p, zoom: 14, t: Date.now() });
      },
      () => setError("Could not get your location. Check browser permission."),
    );
  };

  // Summary of the loaded risk zones (no extra API calls)
  const summary = useMemo(() => {
    if (!zones) return null;
    const counts = { low: 0, medium: 0, high: 0 };
    const cells = zones.features.map((f) => {
      counts[f.properties.level]++;
      const ring = f.geometry.coordinates[0];
      return { ...f.properties, center: [(ring[0][1] + ring[2][1]) / 2, (ring[0][0] + ring[2][0]) / 2] };
    });
    const hotspots = cells.filter((c) => c.score >= 0.25).sort((a, b) => b.score - a.score).slice(0, 5);
    return { counts, total: cells.length, hotspots };
  }, [zones]);

  const goTo = (center) => { setMode("inspect"); pickPoint(center); setFocus({ pos: center, t: Date.now() }); };

  const ctx = zones?.rain || zones?.heat;
  const isGrid = !NO_GRID(hazard);

  // Content of the box that opens on the map when a spot is clicked
  const rows = !risk ? [] : hazard === "heat"
    ? [["Feels like", `${risk.heat.feels_like_c} °C`], ["Heat hazard", risk.factors.heat],
       ["Exposure", risk.factors.exposure], ["Green/water cover", risk.factors.green_cover]]
    : [["Elevation", `${risk.elevation_m} m`], ["Rain factor", risk.factors.rain],
       ["Low-lying", risk.factors.low_lying], ["Flatness", risk.factors.flatness]];
  const popup = !risk ? <p className="hint">Checking this spot…</p> : (
    <div className="pop">
      <div className="badge" style={{ background: COLORS[risk.level] }}>{risk.level} risk</div>
      <p>{risk.explanation}</p>
      <dl>{rows.map(([k, v]) => <Fragment key={k}><dt>{k}</dt><dd>{v}</dd></Fragment>)}</dl>
      <h3>What to do</h3>
      <ul>{TIPS[hazard][risk.level].map((t) => <li key={t}>{t}</li>)}</ul>
      {hazard === "flood" && (
        <div className="safe">
          {!safe && <button className="btn" onClick={findSafe} disabled={!!busy}>Find safe places nearby</button>}
          {safe && (
            <>
              <h3>Safe places nearby</h3>
              {safe.places.length === 0 && <p className="hint">{safe.osm_available ? "No hospitals or shelters found within a few km in OpenStreetMap." : "OpenStreetMap is unavailable right now."}</p>}
              <ul className="safelist">
                {safe.places.map((p) => (
                  <li key={p.kind + p.lat + p.lon}>
                    <i style={{ background: SAFE_COLORS[p.kind] }} />
                    <a href={p.directions_url} target="_blank" rel="noreferrer">{p.name}</a>
                    <span> · {p.label} · {km1(p.distance_m)}{p.lower ? " · lower than you, may flood first" : p.rise_m >= 1 ? " · higher ground" : ""}{p.emergency ? " · emergency" : ""}</span>
                  </li>
                ))}
                {safe.higher_ground && (
                  <li><i style={{ background: SAFE_COLORS.higher }} />
                    <a href={safe.higher_ground.directions_url} target="_blank" rel="noreferrer">Higher ground</a>
                    <span> · about {km1(safe.higher_ground.distance_m)} {safe.higher_ground.bearing}, ~{Math.round(safe.higher_ground.rise_m)} m higher</span></li>
                )}
              </ul>
              <p className="hint">{safe.disclaimer}</p>
            </>
          )}
        </div>
      )}
      {!advice && <button className="btn" onClick={() => askAdvice()} disabled={!!busy}>Get AI advisory (Amazon Bedrock)</button>}
      {advice && (
        <>
          <p className="advice">{advice.advisory}</p>
          <p className="hint">Source: {advice.source}</p>
        </>
      )}
    </div>
  );

  return (
    <div className="app">
      <aside className="panel">
        <h1>FloodSense</h1>
        <p className="sub">Heat, flood, drought and water-leak intelligence for any city</p>

        <section className="place">
          <h2>Where</h2>
          <select aria-label="Choose a city" value={CITIES.some((c) => c.name === place.name) ? place.name : ""}
            onChange={(e) => choosePlace(CITIES.find((c) => c.name === e.target.value))}>
            {!CITIES.some((c) => c.name === place.name) && <option value="">{place.name}</option>}
            {CITIES.map((c) => <option key={c.name}>{c.name}</option>)}
          </select>
          <form className="row" onSubmit={doSearch}>
            <input value={query} onChange={(e) => setQuery(e.target.value)} placeholder="Search any city or town" aria-label="Search any city or town" />
            <button className="btn" type="submit" disabled={!!busy}>Go</button>
          </form>
          {found.length > 0 && <ul className="results">{found.map((f) => (
            <li key={f.name + f.lat}><button className="link" onClick={() => choosePlace(f)}>{f.name}</button></li>))}</ul>}
          <div className="row">
            <button className="link" onClick={analyzeHere}>Analyze this map view</button>
            <button className="link" onClick={useMyLocation}>Use my location</button>
          </div>
        </section>

        <section className="briefing">
          <h2>AI briefing: all hazards</h2>
          <div className="row">
            <select aria-label="Language" value={lang} onChange={(e) => { setLang(e.target.value); setBrief(null); setAdvice(null); }}>
              {LANGS.map((l) => <option key={l}>{l}</option>)}
            </select>
            <button className="btn" onClick={askBrief} disabled={!!busy}>Brief me</button>
          </div>
          {brief && (
            <>
              {brief.resilience?.score != null && (
                <div className="gauge" aria-label={`Resilience score ${brief.resilience.score} out of 100`}>
                  <b style={{ color: COLORS[brief.overall] }}>{brief.resilience.score}</b>
                  <span>/100 resilience · {brief.resilience.label}</span>
                  <div className="bar"><i style={{ width: `${brief.resilience.score}%`, background: COLORS[brief.overall] }} /></div>
                </div>
              )}
              <div className="chips">
                {Object.entries(brief.levels).map(([h, l]) => (
                  <span key={h} className="chip" style={{ background: l ? COLORS[l] : "#8a98a6" }}>{h} {l || "n/a"}</span>))}
              </div>
              <p className="advice">{brief.briefing}</p>
              <p className="hint">Source: {brief.source}. {brief.disclaimer}</p>
            </>
          )}
        </section>
        <AskPanel place={place} onAsk={(q, history) => askFloodSense(q, place.lat, place.lon, scn, place.name, lang, history)} />
        <AlertsPanel place={place} langs={LANGS} defaultLang={lang} onSubscribe={subscribe} onSendNow={alertNow} busy={busy} />
        <div className="seg hz" role="tablist" aria-label="Hazard">
          {HAZARDS.map(([k, name]) => (
            <button key={k} role="tab" aria-selected={hazard === k} className={hazard === k ? "on" : ""}
              onClick={() => { setHazard(k); setMode("inspect"); }}>{name}</button>
          ))}
        </div>

        {hazard !== "leak" && <section>
          <h2>{hazard === "flood" ? "Rain scenario" : hazard === "heat" ? "Heat scenario" : "Rainfall scenario"}</h2>
          <div className="presets">
            {PRESETS[hazard].map(([name, v]) => (
              <button key={name} className={val === v ? "on" : ""} onClick={() => setScn({ ...scn, [hazard]: v })}>{name}</button>
            ))}
          </div>
          <input type="range" min={SLIDER[hazard].min} max={SLIDER[hazard].max} step={SLIDER[hazard].step} value={val}
            onChange={(e) => setScn({ ...scn, [hazard]: +e.target.value })} aria-label={SLIDER[hazard].label} />
          <p className="hint">
            {scnText(hazard, val)}
            {ctx && val === 0 && hazard === "flood" && ` · ${ctx.rain_24h_mm} mm expected`}
            {ctx && val === 0 && hazard === "heat" && ` · peak ${ctx.tmax_c}°C, feels like ${ctx.feels_like_c}°C`}
          </p>
        </section>}

        {hazard === "drought" && (
          <section>
            <h2>Drought index (city level)</h2>
            <DroughtPanel data={drought} tips={TIPS.drought[drought?.level || "low"]} />
            {drought && !advice && <button className="btn" onClick={() => askAdvice(center)} disabled={!!busy}>Get AI advisory (Amazon Bedrock)</button>}
            {advice && hazard === "drought" && <><p className="advice">{advice.advisory}</p><p className="hint">Source: {advice.source}</p></>}
          </section>
        )}

        {hazard === "leak" && (
          <section>
            <LeakPanel data={leakData} draft={draft} kind={leakKind} setKind={setLeakKind} note={leakNote} setNote={setLeakNote} photo={leakPhoto} setPhoto={setLeakPhoto}
              onSubmit={submitLeak} onCancel={() => { setDraft(null); setLeakPhoto(null); }} onSeed={loadDemoLeaks} busy={busy}
              onGo={(c) => setFocus({ pos: c, t: Date.now() })} />
          </section>
        )}

        {isGrid && <section>
          <h2>What do you want to do?</h2>
          {hazard === "flood" && <div className="seg">
            <button className={mode === "inspect" ? "on" : ""} onClick={() => setMode("inspect")}>Check a spot</button>
            <button className={mode === "route" ? "on" : ""} onClick={() => setMode("route")}>Plan a route</button>
          </div>}
          <label className="check">
            <input type="checkbox" checked={showZones} onChange={(e) => setShowZones(e.target.checked)} /> Show risk zones
          </label>
        </section>}

        {isGrid && mode === "inspect" && (
          <section>
            <h2>Check a spot</h2>
            <p className="hint">{COPY[hazard]}</p>
          </section>
        )}

        {hazard === "flood" && mode === "route" && (
          <section>
            <h2>Safer route</h2>
            {!start && <p className="hint">Click your starting point.</p>}
            {start && !end && <p className="hint">Now click your destination.</p>}
            {route && (
              <>
                {route.same_route
                  ? <p>The shortest route is also the lowest-risk option here.</p>
                  : <p>The safer route is {route.extra_distance_pct}% longer but avoids {km(route.shortest.high_risk_m - route.safer.high_risk_m)} of high-risk road.</p>}
                <table>
                  <thead><tr><th></th><th>Shortest</th><th>Safer</th></tr></thead>
                  <tbody>
                    <tr><td>Distance</td><td>{km(route.shortest.distance_m)}</td><td>{km(route.safer.distance_m)}</td></tr>
                    <tr><td>High-risk road</td><td>{km(route.shortest.high_risk_m)}</td><td>{km(route.safer.high_risk_m)}</td></tr>
                    <tr><td>Peak risk</td><td>{route.shortest.max_risk}</td><td>{route.safer.max_risk}</td></tr>
                  </tbody>
                </table>
                <p className="legend"><span className="swatch dash" /> shortest <span className="swatch solid" /> safer</p>
              </>
            )}
            {(start || end) && <button className="link" onClick={() => { setStart(null); setEnd(null); setRoute(null); }}>Clear route</button>}
          </section>
        )}

        {isGrid && summary && (
          <section>
            <h2>Area overview</h2>
            <div className="counts">
              {["high", "medium", "low"].map((l) => (
                <div key={l}><b style={{ color: COLORS[l] }}>{summary.counts[l]}</b><span>{l}</span></div>
              ))}
            </div>
            <p className="hint">of {summary.total} map cells in this scenario</p>
            {summary.hotspots.length > 0 ? (
              <>
                <h2 className="mt">Top hotspots</h2>
                <ol className="hot">
                  {summary.hotspots.map((h, i) => (
                    <li key={i}>
                      <button className="link" onClick={() => goTo(h.center)}>
                        <i style={{ background: COLORS[h.level] }} />{h.level} · {h.elevation_m != null ? `${h.elevation_m} m · ` : ""}score {h.score}
                      </button>
                    </li>
                  ))}
                </ol>
              </>
            ) : <p className="hint">No medium or high risk cells. Try a stronger scenario.</p>}
          </section>
        )}

        {busy && <p className="status">{busy}…</p>}
        {error && <p className="error">{error}</p>}
        <footer>
          Estimates from public weather, terrain and map data only. Not an official forecast, warning or evacuation
          guarantee. Follow IMD and local authority advisories.
        </footer>
      </aside>
      <FloodMap hazard={hazard} zones={zones} area={area} center={center} point={mode === "inspect" && isGrid ? point : null}
        popup={popup} focus={focus} start={hazard === "flood" ? start : null} end={hazard === "flood" ? end : null}
        route={hazard === "flood" ? route : null} showZones={showZones && isGrid} leaks={hazard === "leak" ? leakData?.leaks : null}
        draft={hazard === "leak" ? draft : null} safe={hazard === "flood" ? safe : null} onFix={markFixed} onClick={onMapClick} onMap={setMap} />
    </div>
  );
}
