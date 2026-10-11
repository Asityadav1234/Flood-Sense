const BASE = (import.meta.env.VITE_API_URL || "http://localhost:8000").replace(/\/+$/, ""); // tolerate a trailing slash

async function call(path, opts) {
  const res = await fetch(BASE + path, opts);
  if (!res.ok) {
    const body = await res.json().catch(() => ({}));
    throw new Error(body.detail || `Request failed (${res.status})`);
  }
  return res.json();
}

export const getFloodRisk = (lat, lon, rainMm) =>
  call(`/flood-risk?lat=${lat}&lon=${lon}&rain_mm=${rainMm}`);

export const getRiskZones = (bbox, rainMm) =>
  call(`/risk-zones?bbox=${bbox.join(",")}&rain_mm=${rainMm}`);

export const getSafeRoute = (start, end, rainMm) =>
  call("/safe-route", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ start, end, rain_mm: rainMm }),
  });


export const getHeatRisk = (lat, lon, tempC) =>
  call(`/heat-risk?lat=${lat}&lon=${lon}&temp_c=${tempC}`);

export const getHeatZones = (bbox, tempC) =>
  call(`/heat-zones?bbox=${bbox.join(",")}&temp_c=${tempC}`);

export const getDrought = (lat, lon, rainPct) =>
  call(`/drought?lat=${lat}&lon=${lon}&rain_pct=${rainPct}`);

// hazard: "flood" | "heat" | "drought"; scn = the active scenario value (mm, deg C or % of normal)
export const getAdvisory = (lat, lon, hazard, scn, place = "", lang = "English") => {
  const q = { flood: "rain_mm", heat: "temp_c", drought: "rain_pct" }[hazard];
  return call(`/advisory?lat=${lat}&lon=${lon}&hazard=${hazard}&${q}=${scn}&place=${encodeURIComponent(place)}&lang=${lang}`);
};

// One AI briefing across flood + heat + drought for a spot (scn = { flood, heat, drought } scenario values)
export const getBriefing = (lat, lon, scn, place = "", lang = "English") =>
  call(`/briefing?lat=${lat}&lon=${lon}&rain_mm=${scn.flood}&temp_c=${scn.heat}&rain_pct=${scn.drought}` +
       `&place=${encodeURIComponent(place)}&lang=${lang}`);

// Water-leak layer
export const getLeaks = (bbox) => call(`/leaks?bbox=${bbox.join(",")}`);
export const reportLeak = (lat, lon, kind, note, photoKey = "") =>
  call("/leaks", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ lat, lon, kind, note, photo_key: photoKey }) });

// Shrink the photo in the browser (max 1280 px, JPEG) so uploads are fast on mobile data
function shrink(file, max = 1280) {
  return new Promise((resolve, reject) => {
    const img = new Image();
    img.onload = () => {
      const k = Math.min(1, max / Math.max(img.width, img.height));
      const c = document.createElement("canvas");
      c.width = Math.round(img.width * k); c.height = Math.round(img.height * k);
      c.getContext("2d").drawImage(img, 0, 0, c.width, c.height);
      c.toBlob((b) => (b ? resolve(b) : reject(new Error("Could not read this photo."))), "image/jpeg", 0.8);
      URL.revokeObjectURL(img.src);
    };
    img.onerror = () => reject(new Error("Could not read this photo."));
    img.src = URL.createObjectURL(file);
  });
}

// Browser -> S3 directly with a presigned POST; returns the key to send with the report
export async function uploadPhoto(file) {
  const up = await call("/leaks/photo-upload", { method: "POST" });
  const blob = await shrink(file);
  const fd = new FormData();
  Object.entries(up.fields).forEach(([k, v]) => fd.append(k, v));
  fd.append("file", blob, "leak.jpg"); // the file field must come last
  const r = await fetch(up.url, { method: "POST", body: fd });
  if (!r.ok) throw new Error("Photo upload failed.");
  return up.key;
}
export const fixLeak = (id) => call(`/leaks/${id}/fix`, { method: "POST" });
export const seedLeaks = (lat, lon) => call(`/leaks-demo?lat=${lat}&lon=${lon}`, { method: "POST" });

// Ask FloodSense: a grounded Q&A answered by Amazon Bedrock from the live data for this place
export const askFloodSense = (question, lat, lon, scn, place = "", lang = "English", history = []) =>
  call("/ask", { method: "POST", headers: { "Content-Type": "application/json" },
                 body: JSON.stringify({ question, lat, lon, place, lang, rain_mm: scn.flood, temp_c: scn.heat, rain_pct: scn.drought, history }) });

// Hospitals, shelters and higher ground near a spot (OpenStreetMap + terrain)
export const getSafePlaces = (lat, lon) => call(`/safe-places?lat=${lat}&lon=${lon}`);

// Proactive alerts (Amazon SNS)
// contact = an email address or a phone number with country code (+91...); lang = language of the alerts
export const subscribeAlerts = (contact, lat, lon, place, minLevel, lang = "English") =>
  call("/alerts/subscribe", { method: "POST", headers: { "Content-Type": "application/json" },
                              body: JSON.stringify({ contact, lat, lon, place, min_level: minLevel, lang }) });
export const sendAlertNow = (lat, lon, scn, place = "") =>
  call(`/alerts/send-now?lat=${lat}&lon=${lon}&rain_mm=${scn.flood}&temp_c=${scn.heat}&rain_pct=${scn.drought}&place=${encodeURIComponent(place)}`,
       { method: "POST" });

// City search: Open-Meteo geocoding (free, no key, worldwide)
export async function searchPlaces(q) {
  const r = await fetch(`https://geocoding-api.open-meteo.com/v1/search?name=${encodeURIComponent(q)}&count=6&language=en&format=json`);
  if (!r.ok) throw new Error("City search is unavailable right now.");
  return ((await r.json()).results || []).map((x) => ({
    name: [x.name, x.admin1, x.country].filter(Boolean).join(", "), lat: x.latitude, lon: x.longitude,
  }));
}
