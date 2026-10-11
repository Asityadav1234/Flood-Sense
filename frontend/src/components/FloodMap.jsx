import { useEffect } from "react";
import { MapContainer, TileLayer, GeoJSON, CircleMarker, Polyline, Rectangle, Popup, Tooltip, useMap, useMapEvents } from "react-leaflet";

export const COLORS = { low: "#2f9e62", medium: "#e3a21a", high: "#d23b2e" };

// Analysis area: a box of about 6.6 km around a centre point, in any city (south, west, north, east)
export const boxAround = ([lat, lon], half = 0.03) => {
  const dl = half / Math.max(0.2, Math.cos((lat * Math.PI) / 180));
  return [lat - half, lon - dl, lat + half, lon + dl];
};

function Clicks({ onClick }) {
  useMapEvents({ click: (e) => onClick([e.latlng.lat, e.latlng.lng]) });
  return null;
}

// Pans the map when `focus` = { pos, t, zoom? } changes (hotspots, city search, "use my location")
function FlyTo({ focus }) {
  const map = useMap();
  useEffect(() => {
    if (focus) map.flyTo(focus.pos, focus.zoom || Math.max(map.getZoom(), 15), { duration: 0.8 });
  }, [focus]);
  return null;
}

export const SAFE_COLORS = { hospital: "#8e24aa", shelter: "#00897b", possible: "#7cb342", higher: "#6d4c41" };

const PHOTO_TEXT = {
  verified: "Photo checked by Amazon Rekognition: water and a pipe or tap detected.",
  partial: "Photo checked by Amazon Rekognition: it shows water or a pipe, but not both.",
  unclear: "Amazon Rekognition could not confirm a leak in this photo.",
  unchecked: "Photo attached (automatic check unavailable).",
};

export default function FloodMap({ hazard, zones, area, center, point, popup, focus, start, end, route, showZones,
                                   leaks, draft, safe, onFix, onClick, onMap }) {
  return (
    <div className="mapwrap">
      <MapContainer center={center} zoom={13} className="map" ref={onMap}>
        <TileLayer attribution="&copy; OpenStreetMap contributors" url="https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png" />
        <Rectangle bounds={[[area[0], area[1]], [area[2], area[3]]]}
          pathOptions={{ color: "#16324f", weight: 1.5, fill: false, dashArray: "6 6" }} />
        {showZones && zones && (
          <GeoJSON key={hazard + JSON.stringify(zones.rain || zones.heat) + area.join()} data={zones}
            style={(f) => ({ color: COLORS[f.properties.level], weight: 0.5,
                             fillColor: COLORS[f.properties.level], fillOpacity: 0.1 + 0.5 * f.properties.score })} />
        )}
        {route && !route.same_route && (
          <Polyline positions={route.shortest.coords} pathOptions={{ color: "#d23b2e", weight: 4, dashArray: "8 8" }} />
        )}
        {route && <Polyline positions={route.safer.coords} pathOptions={{ color: "#0f6bbf", weight: 6 }} />}
        {point && <CircleMarker center={point} radius={8} pathOptions={{ color: "#16324f", fillColor: "#fff", fillOpacity: 1, weight: 3 }} />}
        {point && <Popup position={point} minWidth={260} maxWidth={300}>{popup}</Popup>}
        {start && <CircleMarker center={start} radius={9} pathOptions={{ color: "#fff", fillColor: "#16324f", fillOpacity: 1, weight: 3 }} />}
        {end && <CircleMarker center={end} radius={9} pathOptions={{ color: "#fff", fillColor: "#0f6bbf", fillOpacity: 1, weight: 3 }} />}
        {(leaks || []).map((l) => (
          <CircleMarker key={l.id} center={[l.lat, l.lon]} radius={7 + 3 * ["low", "medium", "high"].indexOf(l.level)}
            pathOptions={{ color: "#fff", weight: 2, fillColor: COLORS[l.level], fillOpacity: 0.95 }}>
            <Popup>
              <div className="pop">
                <div className="badge" style={{ background: COLORS[l.level] }}>{l.level} priority</div>
                <p><b>{l.label}</b>{l.demo ? " (demo report)" : ""}<br />About {l.lpd.toLocaleString()} L of water lost per day (rough estimate)</p>
                {l.note && <p>{l.note}</p>}
                {l.photo_url && <img className="leakphoto" src={l.photo_url} alt="Photo of the reported leak" loading="lazy" />}
                {l.photo_check && (
                  <p className="hint">{PHOTO_TEXT[l.photo_check.status] || PHOTO_TEXT.unchecked}
                    {l.photo_check.labels?.length > 0 && ` Saw: ${l.photo_check.labels.map((x) => `${x.name} ${x.confidence}%`).join(", ")}.`}</p>
                )}
                <button className="btn" onClick={() => onFix(l.id)}>Mark as fixed</button>
              </div>
            </Popup>
          </CircleMarker>
        ))}
        {(safe?.places || []).map((p) => (
          <CircleMarker key={p.kind + p.lat + p.lon} center={[p.lat, p.lon]} radius={9}
            pathOptions={{ color: "#fff", weight: 2, fillColor: SAFE_COLORS[p.kind], fillOpacity: 1 }}>
            <Tooltip>{p.name} · {p.label}</Tooltip>
          </CircleMarker>
        ))}
        {safe?.higher_ground && (
          <CircleMarker center={[safe.higher_ground.lat, safe.higher_ground.lon]} radius={9}
            pathOptions={{ color: "#fff", weight: 2, fillColor: SAFE_COLORS.higher, fillOpacity: 1 }}>
            <Tooltip>Higher ground (about {safe.higher_ground.rise_m} m higher)</Tooltip>
          </CircleMarker>
        )}
        {draft && <CircleMarker center={draft} radius={10} pathOptions={{ color: "#0f6bbf", fillColor: "#fff", fillOpacity: 1, weight: 4, dashArray: "3 3" }} />}
        <Clicks onClick={onClick} />
        <FlyTo focus={focus} />
      </MapContainer>
      <div className="maplegend" aria-label="Risk colour legend">
        {["low", "medium", "high"].map((l) => (
          <span key={l}><i style={{ background: COLORS[l] }} />{l}</span>
        ))}
      </div>
    </div>
  );
}
