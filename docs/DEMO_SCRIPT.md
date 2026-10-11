# 3-minute demo script

## Before you record (30 minutes, do it once)
1. `./deploy.sh`, open the CloudFront URL, check `API-URL/health`.
2. In your inbox, confirm the SNS subscription email. For SMS: verify your number in the SNS SMS sandbox (India also needs DLT, so use email for India if not set up).
3. Warm the caches: for **Jaipur** and **Mumbai** open Flood, Heat, Drought once, click a spot, press *Find safe places nearby* once (first OpenStreetMap lookup can take several seconds).
4. Upload one real tap/pipe photo as a leak report to confirm the "verified" badge. Mark one leak fixed so *Impact so far* shows.
5. Subscribe your email with **Hindi** and check one translation in a language you read.
6. Browser at 100% zoom, sound check, close other tabs. Keep the README limitations handy.

## Script (about 3:00)
| Time | On screen | Say |
|---|---|---|
| 0:00 | Map of Mumbai, Flood tab | "Floods, heat, drought and leaking pipes are handled separately and in one language. FloodSense puts them in one map for any city and warns people early." |
| 0:15 | Slider to Extreme, hotspots appear, click one | "Risk comes from rain forecast and terrain, and every score is explainable." |
| 0:30 | *Find safe places nearby* | "It shows the nearest hospitals, shelters and the closest higher ground, and flags places lower than you that may flood first." |
| 0:50 | Click *Get AI advisory* | "Amazon Bedrock turns the numbers into plain advice. If Bedrock is down it falls back to rule-based text." |
| 1:05 | Jaipur, Heatwave Severe 48 C, then Drought Severe 30% | "Same engine for heatwaves and drought. Scenario sliders let us show any day." |
| 1:30 | Leaks tab, report a leak with a photo, open its popup | "Citizens report leaks with a photo. Amazon Rekognition checks for water and a pipe. Leaks are ranked by litres wasted and ranked higher when the area is in drought." |
| 1:55 | Mark fixed, show *Impact so far* | "Every fix adds up: litres per day stopped and tanker trips avoided." |
| 2:10 | Alerts box: subscribe, choose Hindi, Extreme scenario, *Send an alert now* | "An EventBridge job re-checks every 3 hours. SNS sends email or SMS only when risk rises, and Bedrock translates it into the subscriber's language." Show the email arriving. |
| 2:35 | Ask FloodSense: "Is it safe to travel now?" | "Answers come only from the live data, behind Bedrock Guardrails. It says when it does not know." |
| 2:50 | Architecture diagram | "Serverless: Lambda, Bedrock, DynamoDB, S3, Rekognition, SNS, EventBridge, CloudFront. Estimates, not official warnings. We would validate with the city next." |

## If something breaks live
- Bedrock slow or off: say "this is the rule-based fallback by design" and continue.
- OpenStreetMap slow: use the city you warmed up.
- Email delayed: show the SNS publish message in the app and switch to the recorded clip.
- Always record a backup take.
