# Source Catalog

Use the CTI tiering model as the ranking rule:

- Tier 1: CISA, NVD, MSRC, CERT/CC, vendor advisories
- Tier 2: vendor research blogs and lab reports
- Tier 3: security news and community writeups
- Tier 4: OSINT, PoC, sandbox, and specialist sources

## Seed Inputs

- `references/default-sources.csv`
- the source anchors listed in this file

## High-Value Anchors

Use these first when searching or refreshing a watchlist:

- CISA
- NVD
- MSRC
- CERT/CC Vulnerability Notes
- Unit 42
- Talos
- Securelist
- Mandiant
- Rapid7
- Trail of Bits
- Lakera
- Promptfoo
- SentinelOne Labs
- Volexity
- Red Canary
- Huntress
- watchTowr Labs
- Google Project Zero
- Elastic Security Labs
- Wiz
- Aikido
- BleepingComputer
- Krebs on Security
- The Hacker News
- SecurityWeek
- Attackerkb
- GreyNoise
- any.run
- Packet Storm

## Curated Sources From the CSV

### Security blogs and research

- Pillar
- Zenity Labs
- Embrace The Red
- The Hacker News
- Legit Security Blog
- Protect AI
- Lakera
- FreeBuf
- KOI
- Promptfoo
- Simon Willison’s Weblog
- 安全客
- HiddenLayer
- Mindgard
- Trustwave Blog
- SpiderLabs Blog
- LayerX
- Wiz
- SecurityOnline.info
- repello.ai
- splx.ai
- noma
- SecurityWeek
- Aikido

### Vendor research and labs

- Unit 42
- Talos
- Securelist
- Rapid7
- Trail of Bits
- Mandiant
- SentinelOne Labs
- Volexity
- Red Canary
- Huntress
- Sekoia
- watchTowr Labs
- Google Project Zero
- WithSecure Labs
- Elastic Security Labs
- Datadog Security Labs
- GreyNoise
- any.run Blog

### Vulnerability databases and advisories

- HackerOne
- Bugcrowd
- huntr
- CERT/CC Vulnerability Notes Database

## Normalization Notes

- Treat repeated names as duplicates unless the URL or publisher is materially different.
- Prefer canonical URLs over social reposts or mirrored pages.
- If a post is translated, keep both the translation and the original source.
- If a source has no URL, mark it as manual-review only.
- For live fetching, prefer feed-backed sources because they preserve title, date, and summary better than homepage scraping.
