# SOP — Exception File Management

**Audience:** Network Engineers
**Owner:** Network Operations / Automation Team

---

## Purpose

How to add, update, or remove suppression rules in the Meraki Uplink Monitoring exception file. Entries here tell the script to skip alerts for specific networks or WAN interfaces.

---

## Exception File Location

| Item | Detail |
|---|---|
| Server | `<your-monitoring-server>` |
| Account | `<service-account>` (e.g. `appuser`) |
| File path | `/opt/meraki-uplink-monitor/inputs/exceptions.txt` |

---

## Step 1 — Log In to the Server

```bash
ssh <service-account>@<your-monitoring-server>
```

If using a key file:
```bash
ssh -i /path/to/your-key.pem <service-account>@<your-monitoring-server>
```

---

## Step 2 — Navigate to the Exception File

```bash
cd /opt/meraki-uplink-monitor/inputs/
ls -l exceptions.txt
```

---

## Step 3 — Open the File for Editing

```bash
nano exceptions.txt
```

(or `vi exceptions.txt` if preferred)

---

## Step 4 — Three Exception Types

Every rule line must start with `NET:`, `KW:`, or `INTF:`

### Type 1 — `NET:` (Suppress Entire Network)

Suppresses ALL alerts from a specific network.

```
NET: <Exact Network Name>    #<TicketID> <Reason>
```

Example:
```
NET: Region-A - Site-1    #CHG0012345 Monitoring disabled per request
```

> Copy the exact network name from the **Network** column of an alert email or from the Meraki Dashboard.

### Type 2 — `KW:` (Suppress by Keyword)

Any network whose name **contains** this keyword will be suppressed. Matching is **case-sensitive**.

```
KW: <Keyword>    #<TicketID> <Reason>
```

Example:
```
KW: Not-Live    #CHG0012346 All non-live networks excluded
```

### Type 3 — `INTF:` (Suppress One Specific Interface)

Suppresses one interface on one device in one network. Other interfaces on the same device still alert.

```
INTF: <Network Name> - <Device Name> - <Interface>    #<TicketID> <Reason>
```

How to get the values — copy directly from the email subject line:
```
Meraki Uplink Failure Alert - Region-A - Site-1 - SITE1-FW01 - wan2 - Failed
                              [Network Name]    [Device Name]   [Intf]
```

Example:
```
INTF: Region-A - Site-1 - SITE1-FW01 - wan2    #INC0012345 FWA backup circuit
```

---

## Step 5 — Add the New Exception (Mandatory Format)

Scroll to the correct section (`NET:`, `KW:`, or `INTF:`) and add your line.

> **MANDATORY:** Every exception line **must** include a `#` comment with:
> 1. The request/ticket ID (INC, CHG, or SR number)
> 2. A brief reason
>
> Never add a line without a `#` comment — required for audit trail.

Correct examples:
```
NET: Region-B - Decommissioned Site    #CHG0098765 Site decommissioned
KW: Lab                                #SR0011001 All lab networks suppressed
INTF: Region-A - Site-1 - SITE1-FW01 - wan2    #INC0012345 FWA secondary circuit
```

---

## Step 6 — Save the File

**nano:** `Ctrl+O`, `Enter`, `Ctrl+X`
**vi:** `Esc`, `:wq`, `Enter`

---

## Step 7 — Verify the Change

```bash
cat /opt/meraki-uplink-monitor/inputs/exceptions.txt
```

---

## Step 8 — Confirm It Takes Effect

The script runs every 15 minutes — no restart needed. After the next run:

```bash
ls -lt /opt/meraki-uplink-monitor/logs/ | head -3
grep "Skipping" /opt/meraki-uplink-monitor/logs/<latest_log_file>
```

You should see lines like:
```
INFO: Skipping network (NET exact match): Region-A - Site-1
INFO: Skipping network (KW match): Not-Live-Region-A (keyword: Not-Live)
INFO: Skipping interface (INTF rule): SITE1-FW01 wan2 in Region-A - Site-1
```

---

## Step 9 — Removing an Exception

To remove permanently — delete the entire line.

To disable temporarily without deleting — prepend a `#`:
```
# NET: Region-A - Site-1    #CHG0012345 Temporarily disabled for testing
```

Lines starting with `#` are ignored by the script.

---

## Rules and Compliance

| Rule | Requirement |
|---|---|
| Ticket ID | Every exception line MUST include a ticket/request ID in the `#` comment |
| Reason | Every exception line MUST include a brief reason in the `#` comment |
| Case sensitivity | Values are case-sensitive — copy exactly from the dashboard or alert email |
| Review | Exception list should be reviewed quarterly to remove stale entries |
| Approval | Exceptions require a CHG or INC ticket before being added |

---

## Troubleshooting

| Problem | What to Check |
|---|---|
| Alert still coming after adding exception | Wait for next 15-min run, then check logs for "Skipping" message |
| Typo in network name | Copy the exact name from the email subject |
| KW keyword not matching | Check case — matching is case-sensitive |
| INTF rule not working | Network, Device, and Interface must all match exactly |
| File cannot be saved | Check permissions: `ls -l exceptions.txt` |
