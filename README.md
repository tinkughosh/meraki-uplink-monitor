# Meraki Uplink Failure Monitor

A Python automation that polls the Cisco Meraki Dashboard API every 15 minutes, detects WAN uplink failures on MX appliances, and dispatches alerts to email and ServiceNow Event Management.

Designed to be safe for production: **all Meraki API calls are read-only (HTTP GET only)**, with atomic cache writes, exponential rate-limit backoff, automatic log rotation, and a flexible suppression engine for noisy or non-critical sites.

---

## Features

- **Read-only Meraki API** — only `GET` is ever issued; the script cannot modify Meraki configuration
- **Status-change alerting** — alerts only on `active → failed/not connected` transitions, no repeat alerts
- **Three-tier suppression** — exact network match, keyword match, or specific interface match
- **Email + ServiceNow** — HTML email to operations team and Event Management API event in parallel
- **Self-healing cache** — corruption detected, repaired, and reported automatically; alerts suppressed during recovery cycle to prevent false alarm floods
- **Atomic writes** — temp file + rename ensures cache is never corrupted by partial writes
- **Rate-limit aware** — exponential backoff on HTTP 429, respects `Retry-After` header
- **Log rotation** — keeps the most recent N log files, deletes the oldest

---

## How It Works

```
Every 15 minutes (cron-driven):

  1. Load config.json and exception file
  2. Validate cache integrity (rebuild + alert tech team if corrupt)
  3. Fetch from Meraki Dashboard API (read-only):
       GET /organizations/{orgId}/appliance/uplink/statuses
       GET /organizations/{orgId}/devices
       GET /organizations/{orgId}/networks
  4. Compare current uplink status against cached previous status
  5. For each uplink that transitioned to failed/not-connected:
       a. Check NET / KW / INTF suppression rules → skip if matched
       b. Send HTML email alert to operations team
       c. Raise ServiceNow event with full payload
  6. Persist updated status to cache atomically
```

---

## Repository Layout

```
.
├── meraki_uplink_monitor.py       Main script
├── config.example.json            Config template (copy to config.json)
├── examples/
│   └── exceptions.example.txt     Sample suppression rules
├── docs/
│   ├── Runbook.md                 Operational runbook
│   └── SOP-Exception-Management.md  How to add/remove suppression rules
├── .gitignore
├── LICENSE
└── README.md
```

---

## Quick Start

### 1. Clone & install

```bash
git clone https://github.com/<your-username>/meraki-uplink-monitor.git
cd meraki-uplink-monitor
pip install requests
```

### 2. Configure

```bash
cp config.example.json config.json
```

Edit `config.json` and fill in:
- Your Meraki API key and organization ID
- SMTP server, sender, and recipient lists
- ServiceNow Event Management endpoint and credentials
- Absolute paths to the cache file, log folder, and exception file

### 3. Create the suppression file

```bash
cp examples/exceptions.example.txt /path/to/exceptions.txt
```

Edit the suppression rules per your environment — see [SOP-Exception-Management.md](docs/SOP-Exception-Management.md).

### 4. First run

```bash
python3 meraki_uplink_monitor.py
```

The first run builds the cache and sends no alerts. From the second run onward, status transitions trigger emails and ServiceNow events.

### 5. Schedule via cron

```cron
*/15 * * * * /usr/bin/python3 /opt/meraki-uplink-monitor/meraki_uplink_monitor.py
```

---

## Suppression Engine

Three rule types — each line starts with a prefix:

| Prefix | Effect | Matching | Example |
|---|---|---|---|
| `NET:` | Suppresses entire network | Exact, case-sensitive | `NET: Region-A - Site-1` |
| `KW:` | Suppresses any network containing keyword | Substring, case-sensitive | `KW: Not-Live` |
| `INTF:` | Suppresses one interface on one device in one network | Exact on all 3 fields | `INTF: Region-A - Site-1 - SITE1-FW01 - wan2` |

Comments after `#` are ignored — use them to record the change-ticket ID and reason:

```
NET: Region-A - Lab Network    # CHG0012345 Lab — not customer-facing
KW: Not-Live                   # SR0011001 All non-live networks excluded
INTF: Region-A - Site-1 - SITE1-FW01 - wan2  # INC0012345 FWA backup circuit
```

---

## Configuration Reference

| Section | Key | Description |
|---|---|---|
| `meraki` | `api_key`, `org_id` | Dashboard API credentials |
| `paths` | `cache_file`, `log_folder`, `exceptions_file` | Absolute paths |
| `logging` | `max_log_files` | Log rotation limit |
| `smtp` | `server`, `port`, `sender`, `display_name` | Email server details |
| `email_uplink_alerts` | `recipients`, `cc`, `bcc` | Operations recipients |
| `email_cache_alerts` | `recipients`, `cc`, `bcc` | Tech-team recipients (cache corruption alerts only) |
| `servicenow` | `endpoint`, `username`, `password` | Event Management API |

---

## Read-Only API Guarantee

Only three Meraki endpoints are ever called, and all use `GET`:

```
GET /organizations/{orgId}/appliance/uplink/statuses
GET /organizations/{orgId}/devices
GET /organizations/{orgId}/networks
```

`grep -E "requests\.(post|put|patch|delete)" meraki_uplink_monitor.py` returns only the ServiceNow event POST — never a Meraki call. This is enforced by code review and is part of the project ruleset.

---

## License

MIT — see [LICENSE](LICENSE).

---

## Disclaimer

This is an independent open-source project. Cisco Meraki and ServiceNow are trademarks of their respective owners. The author is not affiliated with either company.
