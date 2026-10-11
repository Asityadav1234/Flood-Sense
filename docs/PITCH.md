# FloodSense AI: pitch package

> Items in [square brackets] are for you to fill in with real, sourced facts before submitting. I did not invent statistics.

## One line
One map that tells any city's residents what the **flood, heat and drought** risk is, where to go, and which **water leaks** to fix first, and warns them **by email or SMS in their own language** before it gets worse.

## Problem
Floods, heatwaves, droughts and water waste are usually handled by separate tools and separate agencies, in one language, after the event starts. Residents get a rainfall number but not "what should I do, where do I go, and who is fixing the leaking main on my street?"
[Add 1 or 2 sourced statistics for your city or country, e.g. from IMD, NDMA, CWC or your municipal water board, with the source name.]

## Solution (what is built)
| Layer | What it does |
|---|---|
| Flood | Risk map from rain forecast + terrain, hotspots, safer route, nearest hospitals / shelters / higher ground |
| Heatwave | Risk map from heat index and nearby green or water cover |
| Drought | City drought index from 3 months of rain vs the 10-year normal |
| Water leaks | Citizen reports with a **photo checked by Amazon Rekognition**, ranked by litres wasted per day (higher when the area is dry); fixed leaks add up to **water saved** |
| Early warning | EventBridge re-checks every 3 h; Amazon SNS sends **email or SMS** only when risk rises, translated by Bedrock into 17 languages |
| Ask FloodSense | Questions answered by Bedrock **only from live data**, behind Bedrock Guardrails |
| Resilience score | One 0-100 number combining the three hazards |

Works for any city in the world (free public data, no API keys). Every hazard has a scenario slider so it can be demoed on a dry day.

## Why it can win
1. **Four climate problems, one workflow:** the drought index raises leak priority, so water saving is tied to real stress.
2. **Proactive, not a dashboard:** it warns people (SNS + EventBridge) instead of waiting for them to look.
3. **Inclusive:** 17 languages, SMS for people without smartphones data, plain-language advice.
4. **Trustworthy AI:** explainable rule-based scores, Bedrock only explains, grounded answers, Guardrails, honest limitations, English original kept under translations.
5. **Measurable impact:** litres per day stopped, tanker-trip equivalents, alerts delivered, time from risk rise to alert (at most 3 h).
6. **Serverless and cheap to run:** pay per use, nothing idle.

## AWS services and why each one
| Service | Role |
|---|---|
| Lambda (container) + Function URL | The API, plus the scheduled monitor (same image) |
| Amazon Bedrock (Nova Lite) | Advice, briefings, translations, Ask |
| Bedrock Guardrails | Keeps Ask on topic, blocks prompt attacks and harmful content, hides emails and phone numbers |
| DynamoDB | Leak reports (grid-cell index), watch list, shared cache and rate limits (all with TTL) |
| S3 | Website, private leak photos (30-day expiry) |
| Amazon Rekognition | Checks leak photos for water + pipe, blocks inappropriate images |
| Amazon SNS | Email and SMS alerts, filtered by area, level and language |
| Amazon EventBridge | Runs the early-warning monitor every 3 hours |
| CloudFront | HTTPS website with security headers |

## Impact (how to measure and claim it honestly)
- Water: "Impact so far" card = litres per day stopped by fixed leaks and litres saved since they were fixed. Based on stated leak-size assumptions (drip 20, steady stream 2,000, overflow 1,000, burst 50,000 L/day), not metered. Convert to **people's daily need** (135 L/person/day planning norm) and **tanker trips** (10,000 L).
- Safety: alerts sent, areas covered, languages used.
- Pilot plan to describe: [name a ward / residents' welfare association / college campus / municipal zone], 4 weeks, measure leaks reported, leaks fixed, median days to fix, alerts delivered, and a short resident survey.

## Cost (order of magnitude: verify on the AWS Pricing Calculator before quoting)
Everything is pay per use. Rough shape for a small city pilot: the main costs are Lambda time (about 2 GB x a few seconds per map request), Bedrock tokens (one briefing is roughly 700 tokens in, 150 out, a tiny fraction of a cent on Nova Lite), Rekognition (about a tenth of a cent per photo for labels + moderation), DynamoDB on-demand requests, and SMS (varies a lot by country and is the most expensive part). Email via SNS is almost free at pilot volumes. With the free tier, a hackathon demo should cost very little. [Plug your own numbers from the calculator: requests per day, photos per day, subscribers, alerts per week.]

## Responsible AI and limitations (say these out loud)
- Estimates only: not an official forecast, warning or evacuation plan. Follow IMD / local authorities.
- Flood: rain + 90 m terrain, no drainage data. Heat: green/water cover proxy, simplified 40 C threshold. Drought: city-level index, no reservoir or groundwater data.
- Leak sizes are planning assumptions. Rekognition can miss a real leak or accept a puddle, so the photo check is a helper and a person decides.
- Shelters: only places tagged as shelters in OpenStreetMap are called shelters; schools and community centres are "possible". Coverage varies by city.
- Translations come from a language model; emails include the English original.
- Public demo API has rate limits, but no user login yet.

## Roadmap
Validate against known waterlogging spots and heat records; satellite land-surface temperature; reservoir levels; WhatsApp channel; Cognito login for municipal staff with a work-order view; WAF; per-area fan-out for thousands of watch areas; official feeds (IMD, CWC).

## Likely judge questions
| Question | Answer |
|---|---|
| Is the risk model validated? | Not yet. It is explainable and rule-based on purpose; the plan is to validate against known waterlogging spots and heat records. We state it as an estimate everywhere. |
| Why Bedrock if scores are rule-based? | To explain in plain language and translate. If Bedrock is down, the app falls back to rule-based text. |
| What stops fake leak reports or alert spam? | Photo check, rate limits per IP/contact/area, SNS needs email confirmation, alerts only on rising risk. A login for staff is on the roadmap. |
| Will it scale to a big city? | Leak queries use a grid-cell index, answers are cached, SNS and Lambda scale; the monitor fans out with SQS for thousands of areas. |
| What does it cost? | Pay per use; see Cost above. SMS is the main variable. |
| How is it different from a weather app? | It joins flood, heat, drought and leaks, tells you what to do and where to go, and warns you in your language. |
| What if a translation is wrong? | The email carries the English original; the SMS is short and numeric; the prompt forbids changing numbers or names. |
| Data privacy? | Phone/email are only held by SNS; the app stores area keys and language; the sign-up throttle stores only a hash; Guardrails anonymise emails and phones in Ask. |

## Submission text (edit to match what your team really did)
**Short description:** FloodSense AI warns any city's residents about flood, heat and drought risk, shows the nearest hospitals, shelters and higher ground, and ranks citizen-reported water leaks (with photo checks) by litres wasted, then sends early-warning email or SMS alerts in 17 languages. Built serverless on AWS with Lambda, Bedrock, DynamoDB, S3, Rekognition, SNS, EventBridge and CloudFront.

**Challenges we solved (technical, all real in this codebase):** keeping AI advice consistent with the numbers (scores are the source of truth); alerting without spamming (only when risk rises); translating safety alerts without losing facts (English original kept, numbers locked in the prompt); abuse limits on a public API (DynamoDB rate limits); a shared cache so Lambda cold starts do not hammer free data APIs.

**What is next:** see Roadmap.
