# FloodSense AI: Heat and Water

## Deploy on Render (simplest, free)

1. Push this folder to a GitHub repo.
2. Render dashboard -> **New -> Blueprint** -> select the repo. It reads `render.yaml` and creates two services:
   `floodsense-api` (FastAPI) and `floodsense-web` (React site).
3. When asked, fill the two variables:
   - `VITE_API_URL` = the API URL, e.g. `https://floodsense-api.onrender.com` (no trailing slash)
   - `ALLOWED_ORIGIN` = the website URL, e.g. `https://floodsense-web.onrender.com`
   (If the names differ, copy the real URLs from each service's page, then redeploy the website.)
4. Open the website URL. Check `https://<api>/health` returns `{"ok": true}`.

Notes: on Render the app runs in local mode (no AWS needed). Advice uses the rule-based text (`USE_BEDROCK=0`),
leak reports and alert sign-ups are kept in memory (reset on restart/sleep), photo upload is off, and email/SMS
alerts are simulated. Free tier sleeps after 15 min idle (first request takes ~30 s) and has 512 MB RAM, so the
safe-route feature may run out of memory; use the Starter plan for that. The AWS files (`template.yaml`,
`deploy.sh`) still work unchanged.

---


Heatwaves, floods, droughts and every leak in between. **Works for any city in the world**: pick one, search any
town, click "Analyze this map view", or use your location. Rule-based and explainable, with Amazon Bedrock turning the
numbers into plain-language advice in 17 languages (with a rule-based fallback if AWS is unavailable).

**Amazon Web Services used:** Lambda (container) + Function URL, Amazon Bedrock (Nova Lite), DynamoDB, **Amazon SNS**, **Amazon EventBridge**, **Amazon Rekognition**, **Bedrock Guardrails**, S3, CloudFront.

## What it does
| Layer | Inputs (all free, no API key) | Output |
|---|---|---|
| Flood | Open-Meteo rain forecast + Copernicus DEM elevation | Risk map, hotspots, safer route (OSMnx) |
| Heatwave | Open-Meteo temperature/humidity, heat index, days at 40 C+ in next 7, OpenStreetMap parks/forests/water | Risk map: spots with little green/water cover score higher |
| Drought | Open-Meteo: last 91 days of rain vs the 10-year average, dry-spell length, evaporation | City-level drought index, weekly rain vs normal chart |
| **Water leaks** | Citizen reports stored in **DynamoDB** + the drought index at that spot | Map of leaks ranked by litres wasted per day, raised in priority when the area is also dry; "mark fixed" |
| **Safe places** | OpenStreetMap hospitals, shelters, assembly points (community centres and schools as *possible* shelters) + Copernicus terrain | Nearest places with distance and directions, whether they sit lower than you, and the nearest higher ground; added to flood and heat alert emails |
| **Photo evidence** | A photo of the leak, uploaded from the browser to a private **S3** bucket | **Rekognition** checks for water and a pipe/tap/hose (and blocks inappropriate images); reports get a verified badge |
| **Ask FloodSense** | Live flood/heat/drought facts, leak reports, nearby safe places | Bedrock answers only from those facts (Guardrails on), rule-based fallback |
| **Early-warning alerts** | Email or SMS subscribers per ~11 km area, each in their own language; EventBridge re-checks every 3 h | Amazon SNS email (full text) or SMS (about 250 characters) only when risk rises (or once a day if it stays high), filtered per area, level and language. Amazon Bedrock translates; emails keep the English original underneath |
| **Resilience score** | Flood + heat + drought scores | One 0-100 score with a label, shown with the AI briefing |
| **AI briefing** | All three hazards for the chosen place | One short Bedrock briefing in your language, highest risk first |

Every hazard has a **scenario slider** (storm mm, heatwave temperature, % of normal rain) so you can demo it on any day.
Scenarios adapt to the place: heat scenarios use the local humidity, drought scenarios use the local 10-year normal.

**SMS notes:** new AWS accounts are in the SNS SMS sandbox, so add and verify your test number under SNS > Text messaging (SMS) > Sandbox destination phone numbers first. In India, real SMS delivery also needs DLT sender and template registration, so use email for India demos if it is not set up. Unicode SMS (Hindi, Tamil...) is billed per 70-character segment. Translations come from a language model: check one in a language you read, and note that emails include the English original.

**Limitations (say these in your demo):** estimates only, not official forecasts or warnings (follow your national weather service, IMD in India).
Flood uses rain and 90 m terrain, with no drainage data. Heat uses a green/water-cover proxy for urban heat, not measured
surface temperature, and a simplified 40 C threshold. Drought is regional, so it is one city-level index, not a map,
and it does not see reservoir or groundwater levels. Litres lost per leak type are rough planning assumptions, not measurements. Safe places depend on OpenStreetMap coverage; community centres and schools are only possible shelters, and higher ground is a hint from 90 m terrain (it may be private land or water). Always confirm with local authorities. The photo check is a helper, not proof: Rekognition can miss a real leak or accept a puddle, so a person still decides.
OpenStreetMap coverage (parks, roads) varies by city.

## Run locally (2 terminals)
```bash
# Backend (Python 3.10+). Without LEAKS_TABLE leak reports are kept in memory.
cd backend && python -m venv .venv && source .venv/bin/activate   # Windows: .venv\Scripts\activate
pip install -r requirements.txt
USE_BEDROCK=0 uvicorn main:app --reload        # http://localhost:8000/docs   (drop USE_BEDROCK=0 if `aws configure` is done)

# Frontend (Node 18+)
cd frontend && cp .env.example .env && npm install && npm run dev      # http://localhost:5173
```

## Deploy to AWS (one command)
Prerequisites: AWS CLI logged in (`aws configure`), [SAM CLI](https://docs.aws.amazon.com/serverless-application-model/latest/developerguide/install-sam-cli.html), Docker running, Node 18+.
In the Bedrock console (us-east-1) make sure **Amazon Nova Lite** is available to your account.
```bash
./deploy.sh
```
It builds the backend as a Lambda container image, creates a public Function URL and a DynamoDB table, builds the
frontend pointing at the API, uploads it to a private S3 bucket and serves it through CloudFront. It prints the live URL.
First deploy takes about 5 to 10 minutes (the image is large because of osmnx). Re-run the same command to update.
Tear down: empty the S3 bucket, then `sam delete --stack-name floodsense`.

**Hardening included:** CORS limited to the CloudFront site, per-IP / per-contact / per-area rate limits (DynamoDB counters), bbox size limits, a shared DynamoDB cache for weather, drought and OpenStreetMap, a grid-cell index for leak queries (no table scans), private S3 buckets, security headers. If the Bedrock Guardrail resource fails to deploy in your account, redeploy with `sam deploy --parameter-overrides EnableGuardrail=false`.

If the API returns 403, the account needs the `lambda:InvokeFunction` permission for Function URLs; the template already
adds it (`ApiInvokePermission`). Env vars: `BEDROCK_MODEL_ID` (default `amazon.nova-lite-v1:0`), `USE_BEDROCK=0` to turn Bedrock off, `LEAKS_TABLE`, `WATCH_TABLE`, `ALERTS_TOPIC_ARN`, `PHOTO_BUCKET`, `CACHE_TABLE`, `ALLOWED_ORIGIN`, `GUARDRAIL_ID` (all set by the template). Without them, alerts run in local mode (nothing is emailed).
The demo API is public and unauthenticated (so anyone can trigger alerts to an area's subscribers; the scenario ones are labelled [SIMULATED]). For production add Cognito for staff, AWS WAF (put CloudFront in front of the API) and reserved concurrency as a cost ceiling.

## API
| Endpoint | Purpose |
|---|---|
| `GET /weather?lat=&lon=&rain_mm=` | 24h rainfall (rain_mm > 0 simulates a storm) |
| `GET /flood-risk?lat=&lon=&rain_mm=` | Flood risk at a point |
| `GET /risk-zones?bbox=s,w,n,e&rain_mm=` | Flood risk GeoJSON grid |
| `POST /safe-route` `{start,end,rain_mm}` | Shortest vs safer route |
| `GET /heat-risk?lat=&lon=&temp_c=` | Heat risk at a point (temp_c > 0 simulates a heatwave) |
| `GET /heat-zones?bbox=s,w,n,e&temp_c=` | Heat risk GeoJSON grid |
| `GET /drought?lat=&lon=&rain_pct=` | Drought index (rain_pct > 0 simulates "% of normal rain") |
| `GET /advisory?lat=&lon=&hazard=flood\|heat\|drought&place=&lang=` | 2-3 sentence advice via Amazon Bedrock |
| `GET /briefing?lat=&lon=&place=&lang=` | Combined flood + heat + drought briefing via Amazon Bedrock |
| `GET /leaks?bbox=` / `POST /leaks` / `POST /leaks/{id}/fix` | Water-leak reports (DynamoDB) |
| `GET /safe-places?lat=&lon=` | Nearest hospitals / shelters / higher ground |
| `POST /leaks/photo-upload` | Presigned S3 POST (one jpeg, max 4 MB, 5 min). `POST /leaks` then takes `photo_key` and runs Rekognition |
| `POST /ask` `{question,lat,lon,place,lang,history}` | Grounded Q&A via Bedrock (Guardrails) |
| `POST /alerts/subscribe` `{contact,lat,lon,place,min_level,lang}` | Subscribe an email (SNS sends a confirmation) or a phone number (+country code), in one of 17 languages |
| `POST /alerts/send-now?lat=&lon=` | Demo: publish an alert for this spot now (scenario values are marked [SIMULATED]) |
| `GET /leaks?bbox=` also returns `impact` | Leaks fixed, litres/day stopped, litres saved, tanker-trip equivalent |
| `POST /leaks-demo?lat=&lon=` | Sample leak reports around a point, for demos |

## 3-minute demo script
1. Pick **Mumbai**, Flood tab, slider to **Extreme**: hotspots appear; click one, press *Get AI advisory*.
2. Click a spot, press **Find safe places nearby** (hospitals, shelters, higher ground on the map). **Plan a route**: shortest vs safer route.
3. Switch city to **Jaipur**, Heatwave tab, **Severe 48 C**: spots far from parks glow red.
4. Drought tab, **Severe 30%**: rain vs 10-year average chart.
5. **Leaks** tab: *Load demo reports*, show litres lost per day, report a new leak **with a photo** (verified badge appears in its popup), mark one fixed.
6. **Early-warning alerts**: subscribe your email (choose Hindi), confirm the SNS email, move the slider to Extreme, press *Send an alert now*. Fix a leak and show **Impact so far**.
7. Language **Hindi** + **Brief me**: one briefing across all hazards.
8. Type any town in the search box to prove it is not tied to one city.

## Next
Validate against known waterlogging spots and weather-service heat records, use satellite land-surface temperature for
heat, add reservoir levels for drought, WhatsApp alerts, cache OSM graphs on S3. See `docs/` for the architecture, pitch package and demo script.
