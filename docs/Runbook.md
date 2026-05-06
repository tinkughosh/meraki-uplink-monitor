# Runbook — Meraki Uplink Failure Monitoring

**Audience:** Network Engineers (non-coding)
**Owner:** Network Operations / Automation Team

---

## 1. What This System Does

Automated monitoring system that watches the status of all WAN uplinks (internet connections) on Cisco Meraki MX appliances. Runs every **15 minutes** automatically.

When an uplink fails:
1. Sends an HTML email alert to the Network Operations team
2. Raises an event in ServiceNow Event Management

When a suppression rule matches, **no alert is sent** for that item.

---

## 2. How It Works (Plain English)

```
Every 15 minutes (cron-driven):

  1. Reads settings from config.json (API key, email list, file paths)
  2. Reads suppression rules from the exception file
  3. Calls Meraki Dashboard API (read-only) for current uplink status,
     device names, and network names
  4. Compares current status against the cached previous status
  5. For each uplink that changed to FAILED or NOT CONNECTED:
       - Checks suppression rules → skip if matched
       - Sends email alert
       - Raises ServiceNow event
  6. Saves updated status to cache for next comparison
```

> **Key behaviour:** The system alerts only on **status change**. If a link is already down from the previous run, no repeat alert is sent.

---

## 3. Meraki API Endpoints (All Read-Only)

| What It Fetches | Endpoint |
|---|---|
| WAN uplink status for all appliances | `GET /organizations/{orgId}/appliance/uplink/statuses` |
| Device names, serials, and notes | `GET /organizations/{orgId}/devices` |
| Network names and IDs | `GET /organizations/{orgId}/networks` |

No `POST`, `PUT`, `PATCH`, or `DELETE` is ever sent to Meraki.

---

## 4. Alert Email

**Subject format:**
```
Meraki Uplink Failure Alert - {Network} - {Device} - {Interface} - Failed
```

**Example:**
```
Meraki Uplink Failure Alert - Region-A - Site-1 - SITE1-FW01 - wan2 - Failed
```

**Body fields:**

| Field | Description |
|---|---|
| Network | Meraki network name |
| Device | Firewall/appliance name |
| Serial | Device serial number |
| Interface | WAN interface (wan1, wan2, etc.) |
| IP | Current IP address of the link |
| Status | Current status (Failed / Not Connected) |
| Previous | What the status was before |
| Notes | Device notes from Meraki dashboard |

---

## 5. ServiceNow Integration

When an uplink fails, an event is automatically raised with:

- **Short Description:** Same as email subject line
- **Source:** `Meraki`
- **Assignment Group:** `Network Operations` (configurable in script)
- **Category / Subcategory:** `network` / `WAN`
- **Severity:** 1
- **Additional Info:** Device serial, network, interface, IP, and device notes

---

## 6. Suppression / Exception System

| Type | Suppresses | Example |
|---|---|---|
| **NET** | Entire network — all devices and all links | `NET: Region-A - Site-1` |
| **KW** | Any network whose name contains this keyword | `KW: Not-Live` |
| **INTF** | One specific WAN link on one specific device | `INTF: Region-A - Site-1 - SITE1-FW01 - wan2` |

For step-by-step instructions see [SOP-Exception-Management.md](SOP-Exception-Management.md).

---

## 7. Files and Locations on Server

| File | Path | Purpose |
|---|---|---|
| Main script | `/opt/meraki-uplink-monitor/meraki_uplink_monitor.py` | The monitoring script |
| Config file | `/opt/meraki-uplink-monitor/config.json` | All settings |
| Exception file | `/opt/meraki-uplink-monitor/inputs/exceptions.txt` | Suppression rules |
| Cache file | `/opt/meraki-uplink-monitor/inputs/uplink_status_cache.json` | Last known uplink status |
| Log files | `/opt/meraki-uplink-monitor/logs/` | One log per execution |

---

## 8. Log Files

A new log file is created **every run** (every 15 minutes):
```
uplink_status_log_YYYY-MM-DD_HH-MM-SS.log
```

**Log levels:**

| Level | Meaning |
|---|---|
| `INFO` | Normal operation |
| `DEBUG` | Detailed trace |
| `WARNING` | Non-critical issue |
| `ERROR` | Operation failed but script continued |
| `SUCCESS` | Email or ServiceNow event sent |
| `ALERT` | Uplink failure detected and being processed |
| `CRITICAL` | Script-level failure |

**Read latest log:**
```bash
ls -lt /opt/meraki-uplink-monitor/logs/ | head -5
cat /opt/meraki-uplink-monitor/logs/<latest_log_file>
```

The system retains the most recent log files (configurable via `max_log_files`) and deletes the oldest automatically.

---

## 9. Cache File

Stores the **last known status** of every uplink. Used to detect status changes.

- **Do not edit manually.**
- If corrupted, the script detects it, rebuilds from API data, sends a Cache Corruption Alert email to the technical team, and skips uplink alerts for that one cycle to prevent a false-alarm flood.
- Normal alerting resumes the next run.

---

## 10. Cron Schedule

```bash
crontab -l
```

Expected entry:
```cron
*/15 * * * * /usr/bin/python3 /opt/meraki-uplink-monitor/meraki_uplink_monitor.py
```

---

## 11. Common Scenarios

| Situation | What Happens | Action |
|---|---|---|
| WAN link goes down | Email + ServiceNow event raised | Investigate the link |
| WAN link already down last cycle | No repeat alert | Normal behaviour |
| Network is in exception list | No alert sent | None — suppressed intentionally |
| Cache corruption detected | Cache rebuilt, corruption email sent to tech team | Check tech email, monitor next run |
| Script fails to run | No alert sent | Check cron and log files |
| Meraki API rate limit hit | Script retries automatically (up to 5×) | None — handled automatically |

---

## 12. Escalation

| Role | Contact |
|---|---|
| Script owner / technical | `network-automation@example.com` |
| Network operations alerts | `network-ops@example.com` |
| NOC | `noc@example.com` |
