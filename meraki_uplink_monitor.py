import os
import requests
import smtplib
import json
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from email.utils import formataddr
from datetime import datetime, timezone, timedelta
import time
import tempfile
import glob

# Load configuration from config.json
_CONFIG_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "config.json")
try:
    with open(_CONFIG_FILE, "r") as _f:
        _cfg = json.load(_f)
except FileNotFoundError:
    raise SystemExit(f"ERROR: Config file not found: {_CONFIG_FILE}")
except json.JSONDecodeError as _e:
    raise SystemExit(f"ERROR: Invalid JSON in config file: {_e}")

MERAKI_API_KEY   = _cfg["meraki"]["api_key"]
ORG_ID           = _cfg["meraki"]["org_id"]

CACHE_FILE       = _cfg["paths"]["cache_file"]
LOG_FOLDER       = _cfg["paths"]["log_folder"]
EXCEPTIONS_FILE  = _cfg["paths"]["exceptions_file"]

MAX_LOG_FILES    = _cfg["logging"]["max_log_files"]

SMTP_SERVER      = _cfg["smtp"]["server"]
SMTP_PORT        = _cfg["smtp"]["port"]
EMAIL_SENDER     = _cfg["smtp"]["sender"]
DISPLAY_NAME     = _cfg["smtp"]["display_name"]

EMAIL_RECIPIENTS       = _cfg["email_uplink_alerts"]["recipients"]
EMAIL_CC               = _cfg["email_uplink_alerts"]["cc"]
EMAIL_BCC              = _cfg["email_uplink_alerts"]["bcc"]

CACHE_ALERT_RECIPIENTS = _cfg["email_cache_alerts"]["recipients"]
CACHE_ALERT_CC         = _cfg["email_cache_alerts"]["cc"]
CACHE_ALERT_BCC        = _cfg["email_cache_alerts"]["bcc"]

SNOW_ENDPOINT    = _cfg["servicenow"]["endpoint"]
SNOW_USERNAME    = _cfg["servicenow"]["username"]
SNOW_PASSWORD    = _cfg["servicenow"]["password"]

# Ensure log folder exists
os.makedirs(LOG_FOLDER, exist_ok=True)
current_time = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
LOG_FILE = os.path.join(LOG_FOLDER, f"uplink_status_log_{current_time}.log")

def log_message(message):
    with open(LOG_FILE, "a") as log_file:
        log_file.write(f"{datetime.now():%Y-%m-%d %H:%M:%S} - {message}\n")

def cleanup_old_logs():
    """Clean up old log files - keep only MAX_LOG_FILES, delete oldest first"""
    try:
        log_message("INFO: Starting log cleanup process")
        
        # Get all log files matching the pattern
        log_pattern = os.path.join(LOG_FOLDER, "uplink_status_log_*.log")
        log_files = glob.glob(log_pattern)
        
        if not log_files:
            log_message("DEBUG: No log files found for cleanup")
            return
        
        log_message(f"DEBUG: Found {len(log_files)} log files")
        
        # Only proceed if we exceed the maximum
        if len(log_files) <= MAX_LOG_FILES:
            log_message(f"DEBUG: Log file count ({len(log_files)}) within limit ({MAX_LOG_FILES})")
            return
        
        # Get file information (path, creation_time)
        file_info = []
        
        for log_file in log_files:
            try:
                stat = os.stat(log_file)
                creation_time = datetime.fromtimestamp(stat.st_ctime)
                file_info.append({
                    'path': log_file,
                    'creation_time': creation_time,
                    'size': stat.st_size
                })
            except OSError as e:
                log_message(f"WARNING: Could not get stats for {log_file}: {e}")
        
        # Sort by creation time (oldest first)
        file_info.sort(key=lambda x: x['creation_time'])
        
        # Calculate how many files to delete
        files_to_delete = len(file_info) - MAX_LOG_FILES
        files_deleted = 0
        space_freed = 0
        
        log_message(f"INFO: Need to delete {files_to_delete} oldest log files")
        
        # Delete the oldest files
        for file_data in file_info[:files_to_delete]:
            try:
                os.remove(file_data['path'])
                age_days = (datetime.now() - file_data['creation_time']).days
                log_message(f"INFO: Deleted old log file: {os.path.basename(file_data['path'])} (Age: {age_days} days)")
                files_deleted += 1
                space_freed += file_data['size']
            except OSError as e:
                log_message(f"ERROR: Could not delete {file_data['path']}: {e}")
        
        # Summary
        remaining_files = len(glob.glob(log_pattern))
        remaining_size = sum(os.path.getsize(f) for f in glob.glob(log_pattern))
        
        log_message(f"INFO: Log cleanup completed - Deleted: {files_deleted} files, "
                   f"Freed: {space_freed / 1024 / 1024:.2f} MB, "
                   f"Remaining: {remaining_files} files ({remaining_size / 1024 / 1024:.2f} MB)")
        
    except Exception as e:
        log_message(f"ERROR: Log cleanup failed: {e}")

def cleanup_cache_backups():
    """Clean up old cache backup files"""
    try:
        backup_pattern = f"{CACHE_FILE}.backup.*"
        backup_files = glob.glob(backup_pattern)
        
        if len(backup_files) > 5:  # Keep only 5 most recent backups
            # Sort by creation time
            backup_info = []
            for backup_file in backup_files:
                try:
                    creation_time = os.path.getctime(backup_file)
                    backup_info.append((backup_file, creation_time))
                except OSError:
                    continue
            
            backup_info.sort(key=lambda x: x[1], reverse=True)  # Newest first
            
            # Delete old backups
            for backup_file, _ in backup_info[5:]:
                try:
                    os.remove(backup_file)
                    log_message(f"DEBUG: Deleted old cache backup: {os.path.basename(backup_file)}")
                except OSError as e:
                    log_message(f"WARNING: Could not delete backup {backup_file}: {e}")
    
    except Exception as e:
        log_message(f"WARNING: Cache backup cleanup failed: {e}")

def get_log_folder_stats():
    """Get statistics about the log folder"""
    try:
        log_pattern = os.path.join(LOG_FOLDER, "uplink_status_log_*.log")
        log_files = glob.glob(log_pattern)
        
        if not log_files:
            return {"file_count": 0, "total_size_mb": 0, "oldest_file": None, "newest_file": None}
        
        total_size = 0
        oldest_time = None
        newest_time = None
        
        for log_file in log_files:
            try:
                stat = os.stat(log_file)
                total_size += stat.st_size
                creation_time = datetime.fromtimestamp(stat.st_ctime)
                
                if oldest_time is None or creation_time < oldest_time:
                    oldest_time = creation_time
                if newest_time is None or creation_time > newest_time:
                    newest_time = creation_time
                    
            except OSError:
                continue
        
        return {
            "file_count": len(log_files),
            "total_size_mb": total_size / 1024 / 1024,
            "oldest_file": oldest_time.strftime("%Y-%m-%d %H:%M:%S") if oldest_time else None,
            "newest_file": newest_time.strftime("%Y-%m-%d %H:%M:%S") if newest_time else None
        }
    except Exception as e:
        log_message(f"WARNING: Could not get log folder stats: {e}")
        return {"error": str(e)}

def create_structured_cache_template():
    """Create a properly structured cache template"""
    return {
        "metadata": {
            "last_updated": datetime.now(timezone.utc).isoformat(),
            "script_version": "2.0",
            "total_devices": 0,
            "total_networks": 0,
            "cache_status": "healthy",
            "last_corruption_check": datetime.now(timezone.utc).isoformat()
        },
        "devices": {},
        "network_summary": {},
        "statistics": {
            "total_uplinks": 0,
            "active_uplinks": 0,
            "failed_uplinks": 0,
            "not_connected_uplinks": 0,
            "devices_all_uplinks_down": 0,
            "networks_with_issues": 0
        }
    }

def validate_cache_structure(data):
    """Comprehensive cache structure validation"""
    try:
        if not isinstance(data, dict):
            log_message("ERROR: Cache root is not a dictionary")
            return False, "Root is not a dictionary"
        
        required_keys = ["metadata", "devices", "network_summary", "statistics"]
        missing_keys = [key for key in required_keys if key not in data]
        
        if missing_keys:
            log_message(f"ERROR: Missing required cache keys: {missing_keys}")
            return False, f"Missing keys: {missing_keys}"
        
        # Validate metadata structure
        metadata = data.get("metadata", {})
        required_metadata = ["last_updated", "script_version", "total_devices"]
        missing_metadata = [key for key in required_metadata if key not in metadata]
        
        if missing_metadata:
            log_message(f"WARNING: Missing metadata keys: {missing_metadata}")
        
        # Validate devices structure
        devices = data.get("devices", {})
        if not isinstance(devices, dict):
            log_message("ERROR: Devices section is not a dictionary")
            return False, "Devices section invalid"
        
        # Validate device entries
        for serial, device_data in devices.items():
            if not isinstance(device_data, dict):
                log_message(f"ERROR: Device {serial} data is not a dictionary")
                return False, f"Invalid device data for {serial}"
            
            if "device_info" not in device_data or "uplinks" not in device_data:
                log_message(f"ERROR: Device {serial} missing required sections")
                return False, f"Invalid structure for device {serial}"
        
        log_message("DEBUG: Cache structure validation passed")
        return True, "Valid"
        
    except Exception as e:
        log_message(f"ERROR: Cache validation exception: {e}")
        return False, f"Validation exception: {e}"

def load_and_validate_cache():
    """Load cache with comprehensive validation and corruption detection"""
    cache_status = {
        "is_valid": False,
        "is_empty": False,
        "is_corrupted": False,
        "error_message": "",
        "data": None,
        "needs_repair": False
    }
    
    try:
        # Check if cache file exists
        if not os.path.exists(CACHE_FILE):
            log_message("INFO: Cache file does not exist - first run detected")
            cache_status["is_empty"] = True
            cache_status["data"] = create_structured_cache_template()
            return cache_status
        
        # Check file size
        file_size = os.path.getsize(CACHE_FILE)
        log_message(f"DEBUG: Cache file size: {file_size} bytes")
        
        if file_size == 0:
            log_message("WARNING: Cache file is empty")
            cache_status["is_empty"] = True
            cache_status["needs_repair"] = True
            cache_status["error_message"] = "Empty cache file"
            cache_status["data"] = create_structured_cache_template()
            return cache_status
        
        # Read and parse JSON
        with open(CACHE_FILE, 'r') as f:
            content = f.read()
        
        if not content.strip():
            log_message("ERROR: Cache file contains only whitespace")
            cache_status["is_corrupted"] = True
            cache_status["needs_repair"] = True
            cache_status["error_message"] = "File contains only whitespace"
            cache_status["data"] = create_structured_cache_template()
            return cache_status
        
        # Parse JSON
        try:
            data = json.loads(content)
        except json.JSONDecodeError as e:
            log_message(f"ERROR: JSON parsing failed - {e}")
            cache_status["is_corrupted"] = True
            cache_status["needs_repair"] = True
            cache_status["error_message"] = f"JSON parsing error: {e}"
            cache_status["data"] = create_structured_cache_template()
            return cache_status
        
        # Validate structure
        is_valid, validation_message = validate_cache_structure(data)
        
        if not is_valid:
            log_message(f"ERROR: Cache structure validation failed - {validation_message}")
            cache_status["is_corrupted"] = True
            cache_status["needs_repair"] = True
            cache_status["error_message"] = f"Structure validation failed: {validation_message}"
            
            # Try to migrate old format
            migrated_data = attempt_migration(data)
            if migrated_data:
                cache_status["data"] = migrated_data
                log_message("INFO: Successfully migrated old cache format")
            else:
                cache_status["data"] = create_structured_cache_template()
            return cache_status
        
        # Cache is valid
        cache_status["is_valid"] = True
        cache_status["data"] = data
        log_message("INFO: Cache loaded and validated successfully")
        
        # Check if cache is suspiciously empty
        if len(data.get("devices", {})) == 0:
            log_message("WARNING: Cache has no device data - possible data loss")
            cache_status["is_empty"] = True
        
        return cache_status
        
    except Exception as e:
        log_message(f"ERROR: Unexpected error loading cache: {e}")
        cache_status["is_corrupted"] = True
        cache_status["needs_repair"] = True
        cache_status["error_message"] = f"Unexpected error: {e}"
        cache_status["data"] = create_structured_cache_template()
        return cache_status

def attempt_migration(old_data):
    """Attempt to migrate old cache format to new structure"""
    try:
        log_message("INFO: Attempting to migrate old cache format")
        
        if isinstance(old_data, list):
            # Migrate from old array format
            new_cache = create_structured_cache_template()
            
            for device in old_data:
                if isinstance(device, dict) and 'serial' in device:
                    serial = device['serial']
                    
                    device_entry = {
                        "device_info": {
                            "serial": serial,
                            "name": device.get('name', 'Unknown'),
                            "network_id": device.get('networkId', ''),
                            "network_name": device.get('network_name', 'Unknown'),
                            "model": device.get('model', 'Unknown'),
                            "notes": device.get('notes', ''),
                            "last_seen": datetime.now(timezone.utc).isoformat()
                        },
                        "uplinks": {},
                        "alert_history": {
                            "last_alert_sent": None,
                            "alert_count_24h": 0,
                            "suppressed_alerts": 0
                        }
                    }
                    
                    # Process uplinks
                    for uplink in device.get('uplinks', []):
                        if isinstance(uplink, dict) and 'interface' in uplink:
                            interface = uplink['interface']
                            device_entry["uplinks"][interface] = {
                                "interface": interface,
                                "status": uplink.get('status', 'unknown'),
                                "ip": uplink.get('ip', ''),
                                "last_status_change": datetime.now(timezone.utc).isoformat(),
                                "consecutive_failures": 0
                            }
                    
                    new_cache["devices"][serial] = device_entry
            
            new_cache["metadata"]["total_devices"] = len(new_cache["devices"])
            new_cache["metadata"]["cache_status"] = "migrated"
            
            log_message(f"INFO: Successfully migrated {len(new_cache['devices'])} devices")
            return new_cache
            
    except Exception as e:
        log_message(f"ERROR: Migration failed: {e}")
        return None

def save_structured_cache(current_status, device_details, network_details):
    """Save cache in structured format with atomic write"""
    try:
        # Load existing cache to preserve history
        cache_status = load_and_validate_cache()
        existing_cache = cache_status["data"]
        
        # Create device and network maps
        device_map = {d["serial"]: d for d in device_details if "serial" in d}
        network_map = {n["id"]: n["name"] for n in network_details}
        
        # Update metadata
        existing_cache["metadata"].update({
            "last_updated": datetime.now(timezone.utc).isoformat(),
            "total_devices": len(current_status),
            "total_networks": len(network_map),
            "cache_status": "healthy",
            "last_corruption_check": datetime.now(timezone.utc).isoformat()
        })
        
        # Statistics counters
        stats = {
            "total_uplinks": 0,
            "active_uplinks": 0,
            "failed_uplinks": 0,
            "not_connected_uplinks": 0,
            "devices_all_uplinks_down": 0,
            "networks_with_issues": set()
        }
        
        # Process each device
        for device_status in current_status:
            serial = device_status.get("serial", "")
            network_id = device_status.get("networkId", "")
            network_name = network_map.get(network_id, "Unknown")
            device_info = device_map.get(serial, {})
            
            # Get existing device data or create new
            if serial in existing_cache["devices"]:
                device_entry = existing_cache["devices"][serial]
            else:
                device_entry = {
                    "device_info": {},
                    "uplinks": {},
                    "alert_history": {
                        "last_alert_sent": None,
                        "alert_count_24h": 0,
                        "suppressed_alerts": 0
                    }
                }
            
            # Update device info
            device_entry["device_info"].update({
                "serial": serial,
                "name": device_info.get("name", "Unknown"),
                "network_id": network_id,
                "network_name": network_name,
                "model": device_info.get("model", "Unknown"),
                "notes": device_info.get("notes", ""),
                "last_seen": datetime.now(timezone.utc).isoformat()
            })
            
            # Process uplinks
            device_has_issues = False
            device_all_down = True
            
            for uplink in device_status.get("uplinks", []):
                interface = uplink.get("interface", "")
                current_status_str = uplink.get("status", "unknown").lower()
                
                # Get previous uplink data
                prev_uplink = device_entry["uplinks"].get(interface, {})
                prev_status = prev_uplink.get("status", "unknown").lower()
                
                # Update uplink data
                uplink_data = {
                    "interface": interface,
                    "status": current_status_str,
                    "ip": uplink.get("ip", ""),
                    "gateway": uplink.get("gateway", ""),
                    "public_ip": uplink.get("publicIp", ""),
                    "last_status_change": prev_uplink.get("last_status_change", 
                                                         datetime.now(timezone.utc).isoformat()),
                    "consecutive_failures": prev_uplink.get("consecutive_failures", 0)
                }
                
                # Update status change time and failure count
                if prev_status != current_status_str:
                    uplink_data["last_status_change"] = datetime.now(timezone.utc).isoformat()
                    if current_status_str in ["failed", "not connected"]:
                        uplink_data["consecutive_failures"] = prev_uplink.get("consecutive_failures", 0) + 1
                    else:
                        uplink_data["consecutive_failures"] = 0
                
                device_entry["uplinks"][interface] = uplink_data
                
                # Update statistics
                stats["total_uplinks"] += 1
                if current_status_str == "active":
                    stats["active_uplinks"] += 1
                    device_all_down = False
                elif current_status_str == "failed":
                    stats["failed_uplinks"] += 1
                    device_has_issues = True
                elif current_status_str == "not connected":
                    stats["not_connected_uplinks"] += 1
                    device_has_issues = True
            
            if device_has_issues:
                stats["networks_with_issues"].add(network_id)
            
            if device_all_down and device_entry["uplinks"]:
                stats["devices_all_uplinks_down"] += 1
            
            existing_cache["devices"][serial] = device_entry
        
        # Update final statistics
        stats["networks_with_issues"] = len(stats["networks_with_issues"])
        existing_cache["statistics"] = {k: v for k, v in stats.items() if k != "networks_with_issues"}
        existing_cache["statistics"]["networks_with_issues"] = stats["networks_with_issues"]
        
        # Save with atomic write
        atomic_save_cache(existing_cache)
        
        log_message(f"INFO: Structured cache saved - {stats['total_uplinks']} uplinks, "
                   f"{stats['failed_uplinks']} failed, {stats['active_uplinks']} active")
        
        return True
        
    except Exception as e:
        log_message(f"ERROR: Could not save structured cache: {e}")
        return False

def atomic_save_cache(data):
    """Save cache with atomic write to prevent corruption"""
    try:
        # Create backup of current cache
        if os.path.exists(CACHE_FILE):
            backup_file = f"{CACHE_FILE}.backup.{int(time.time())}"
            os.rename(CACHE_FILE, backup_file)
            log_message(f"DEBUG: Created backup: {backup_file}")
        
        # Write to temporary file first
        temp_dir = os.path.dirname(CACHE_FILE)
        with tempfile.NamedTemporaryFile(mode='w', suffix='.tmp', 
                                       dir=temp_dir, delete=False) as tmp_file:
            # Save with proper formatting for readability
            json.dump(data, tmp_file, indent=2, sort_keys=True)
            tmp_filename = tmp_file.name
        
        # Validate the temporary file
        with open(tmp_filename, 'r') as test_file:
            test_data = json.load(test_file)
            is_valid, validation_msg = validate_cache_structure(test_data)
            if not is_valid:
                raise ValueError(f"Validation failed: {validation_msg}")
        
        # Atomic move to replace cache file
        os.replace(tmp_filename, CACHE_FILE)
        log_message("INFO: Cache saved successfully with atomic write")
        
    except Exception as e:
        log_message(f"ERROR: Atomic save failed: {e}")
        if 'tmp_filename' in locals() and os.path.exists(tmp_filename):
            os.remove(tmp_filename)
        raise

def send_corruption_alert(cache_status):
    """Send cache corruption alert to specific cache alert recipients"""
    try:
        subject = "ALERT: Meraki Cache File Corruption Detected and Repaired"
        
        corruption_details = f"""
        <html><body>
        <h2 style="color:#FF4500;">Cache Corruption Alert</h2>
        <p><strong>Dear Technical Team,</strong></p>
        <p>The Meraki uplink monitoring script detected cache file corruption and has automatically repaired it.</p>
        
        <h3>Corruption Details:</h3>
        <table border="1" cellpadding="5" cellspacing="0">
            <tr style="background:#FF4500; color:#fff; font-weight:bold;">
                <th>Property</th><th>Value</th>
            </tr>
            <tr><td>Cache File</td><td>{CACHE_FILE}</td></tr>
            <tr><td>Detection Time</td><td>{datetime.now()}</td></tr>
            <tr><td>Corruption Type</td><td>{'Corrupted' if cache_status['is_corrupted'] else 'Empty'}</td></tr>
            <tr><td>Error Message</td><td>{cache_status.get('error_message', 'N/A')}</td></tr>
            <tr><td>Repair Status</td><td>{'Completed' if cache_status['needs_repair'] else 'N/A'}</td></tr>
            <tr><td>Alert Suppression</td><td>Active - No uplink alerts sent this cycle</td></tr>
        </table>
        
        <h3>Actions Taken:</h3>
        <ul>
            <li>Cache file corruption detected and logged</li>
            <li>New structured cache file created with proper formatting</li>
            <li>Backup of corrupted file saved with timestamp</li>
            <li>Alert suppression activated for this cycle to prevent false alarms</li>
            <li>System will resume normal alerting in next cycle</li>
            <li>Cache now uses atomic writes to prevent future corruption</li>
        </ul>
        
        <h3>Technical Details:</h3>
        <ul>
            <li><strong>Structured Format:</strong> JSON is now properly organized and readable</li>
            <li><strong>Data Validation:</strong> Built-in structure validation prevents corruption</li>
            <li><strong>Backup System:</strong> Automatic backups before each write operation</li>
            <li><strong>Atomic Writes:</strong> Prevents partial writes that cause corruption</li>
        </ul>
        
        <h3>Log File Location:</h3>
        <p><code>{LOG_FILE}</code></p>
        
        <p><strong>Next Steps:</strong></p>
        <p>1. The system has automatically created a new structured cache file</p>
        <p>2. Normal alerting will resume on the next script execution (within 15 minutes)</p>
        <p>3. Please monitor the next few runs to ensure proper functionality</p>
        <p>4. The new cache format prevents future corruption and is human-readable for debugging</p>
        
        <p><strong>Cache Health Status:</strong> ? Healthy and Structured</p>
        
        <p>Best regards,<br>Meraki Monitoring System</p>
        </body></html>
        """
        
        log_message("INFO: Sending cache corruption alert to technical team")
        
        sender = formataddr((DISPLAY_NAME, EMAIL_SENDER))
        msg = MIMEMultipart()
        msg["From"] = sender
        msg["To"] = ", ".join(CACHE_ALERT_RECIPIENTS)
        if CACHE_ALERT_CC:
            msg["Cc"] = ", ".join(CACHE_ALERT_CC)
        if CACHE_ALERT_BCC:
            msg["Bcc"] = ", ".join(CACHE_ALERT_BCC)
        msg["Subject"] = subject
        msg.attach(MIMEText(corruption_details, "html"))
        
        with smtplib.SMTP(SMTP_SERVER, SMTP_PORT) as server:
            all_recipients = CACHE_ALERT_RECIPIENTS + CACHE_ALERT_CC + CACHE_ALERT_BCC
            server.sendmail(EMAIL_SENDER, all_recipients, msg.as_string())
        
        log_message(f"SUCCESS: Cache corruption alert sent to: {', '.join(CACHE_ALERT_RECIPIENTS)}")
        
    except Exception as e:
        log_message(f"ERROR: Failed to send cache corruption alert: {e}")

def get_previous_uplink_status(serial, interface, cache_data):
    """Get previous uplink status from structured cache"""
    try:
        device_data = cache_data["devices"].get(serial, {})
        uplink_data = device_data.get("uplinks", {}).get(interface, {})
        return uplink_data.get("status", "").lower()
    except Exception:
        return None

def validate_servicenow_config():
    """Validate ServiceNow configuration with logging"""
    missing_vars = []
    
    if not SNOW_ENDPOINT:
        missing_vars.append("SNOW_ENDPOINT_URL")
    if not SNOW_USERNAME:
        missing_vars.append("SNOW_USERNAME")
    if not SNOW_PASSWORD:
        missing_vars.append("SNOW_PASSWORD")
    
    if missing_vars:
        log_message(f"ERROR: Missing ServiceNow environment variables: {missing_vars}")
        log_message("WARNING: ServiceNow events will not be created")
        return False
    else:
        log_message("INFO: ServiceNow configuration validated successfully")
        log_message(f"DEBUG: ServiceNow endpoint configured: {SNOW_ENDPOINT}")
        return True

def load_all_exceptions():
    """
    Loads all suppression rules from exceptions.txt.

    Three rule types, identified by prefix:

      NET:  Exact network name match — suppresses ALL alerts from that network.
            Example:  NET: Region-A - Site-1

      KW:   Keyword match — suppresses ALL alerts from any network whose name
            contains this keyword (case-sensitive substring).
            Example:  KW: Not-Live

      INTF: Interface suppression — suppresses only the named interface on the
            named device in the named network (exact match on all three fields).
            Format:   INTF: <NetworkName> - <DeviceName> - <Interface>
            Example:  INTF: Region-A - Site-1 - SITE1-FW01 - wan2  #INC0012345

    General rules:
      - Text after '#' is a comment and is ignored.
      - Lines without a recognised prefix are ignored with a warning.
    """
    rules = {"net_exact": [], "keywords": [], "interfaces": []}
    counts = {"net_exact": 0, "keywords": 0, "interfaces": 0}

    try:
        with open(EXCEPTIONS_FILE, "r") as f:
            for raw_line in f:
                line = raw_line.split("#")[0].strip()
                if not line:
                    continue

                if line.upper().startswith("NET:"):
                    value = line[4:].strip()
                    if value:
                        rules["net_exact"].append(value)
                        counts["net_exact"] += 1

                elif line.upper().startswith("KW:"):
                    value = line[3:].strip()
                    if value:
                        rules["keywords"].append(value)
                        counts["keywords"] += 1

                elif line.upper().startswith("INTF:"):
                    value = line[5:].strip()
                    parts = [p.strip() for p in value.split(" - ")]
                    if len(parts) >= 3:
                        network = " - ".join(parts[:-2])
                        device  = parts[-2]
                        intf    = parts[-1]
                        rules["interfaces"].append({"network": network, "device": device, "intf": intf, "raw": value})
                        counts["interfaces"] += 1
                    else:
                        log_message(f"WARNING: INTF rule needs Network - Device - Interface, got: {value}")

                else:
                    log_message(f"WARNING: Unrecognised exception line (missing NET/KW/INTF prefix): {line}")

        log_message(f"INFO: Loaded exceptions — NET: {counts['net_exact']}, KW: {counts['keywords']}, INTF: {counts['interfaces']}")

    except FileNotFoundError:
        log_message(f"WARNING: Exceptions file not found at {EXCEPTIONS_FILE}; no suppression rules loaded.")

    return rules

def fetch_with_backoff(url, headers, retries=5, initial_delay=30):
    delay = initial_delay
    for attempt in range(retries):
        resp = requests.get(url, headers=headers)
        if resp.status_code == 429:
            log_message(f"INFO: Rate limit hit; retrying in {delay} seconds...")
            time.sleep(delay)
            delay *= 2
            continue
        if resp.status_code == 200:
            return resp.json()
        log_message(f"ERROR: HTTP {resp.status_code} for {url}")
        break
    return []

def fetch_appliance_uplink_status():
    log_message("INFO: Fetching appliance uplink status from Meraki API")
    url = f"https://api.meraki.com/api/v1/organizations/{ORG_ID}/appliance/uplink/statuses"
    headers = {
        "X-Cisco-Meraki-API-Key": MERAKI_API_KEY,
        "Content-Type": "application/json",
    }
    data = fetch_with_backoff(url, headers)
    log_message(f"INFO: Retrieved {len(data)} appliance uplink statuses")
    return data

def fetch_device_details():
    log_message("INFO: Fetching device details from Meraki API")
    base_url = f"https://api.meraki.com/api/v1/organizations/{ORG_ID}/devices"
    headers = {
        "X-Cisco-Meraki-API-Key": MERAKI_API_KEY,
        "Content-Type": "application/json",
    }

    all_devices = []
    starting_after = None
    session = requests.Session()

    while True:
        params = {"perPage": 1000}
        if starting_after:
            params["startingAfter"] = starting_after

        for attempt in range(5):
            response = session.get(base_url, headers=headers, params=params)
            if response.status_code == 429:
                retry_after = int(response.headers.get("Retry-After", "30"))
                log_message(f"INFO: Rate limit hit. Retrying in {retry_after} seconds...")
                time.sleep(retry_after)
                continue
            elif response.status_code != 200:
                log_message(f"ERROR: HTTP {response.status_code} while retrieving devices.")
                return all_devices
            break

        data = response.json()
        if not data:
            break

        all_devices.extend(data)
        log_message(f"INFO: Retrieved {len(data)} devices from page. Total so far: {len(all_devices)}")

        if len(data) < 1000:
            break

        starting_after = data[-1]["serial"]

    log_message(f"INFO: Total devices retrieved: {len(all_devices)}")
    return all_devices

def fetch_network_details():
    log_message("INFO: Fetching network details from Meraki API")
    url = f"https://api.meraki.com/api/v1/organizations/{ORG_ID}/networks"
    headers = {
        "X-Cisco-Meraki-API-Key": MERAKI_API_KEY,
        "Content-Type": "application/json",
    }
    data = fetch_with_backoff(url, headers)
    log_message(f"INFO: Retrieved {len(data)} network details")
    return data

def send_email_alert(subject, body):
    """Send regular uplink alert to normal recipients"""
    try:
        log_message(f"INFO: Preparing to send uplink alert: {subject}")
        sender = formataddr((DISPLAY_NAME, EMAIL_SENDER))
        msg = MIMEMultipart()
        msg["From"] = sender
        msg["To"] = ", ".join(EMAIL_RECIPIENTS)
        msg["Cc"] = ", ".join(EMAIL_CC)
        msg["Bcc"] = ", ".join(EMAIL_BCC)
        msg["Subject"] = subject
        msg.attach(MIMEText(body, "html"))
        
        with smtplib.SMTP(SMTP_SERVER, SMTP_PORT) as server:
            server.sendmail(EMAIL_SENDER,
                            EMAIL_RECIPIENTS + EMAIL_CC + EMAIL_BCC,
                            msg.as_string())
        log_message(f"SUCCESS: Uplink alert sent successfully to operations team")
    except Exception as e:
        log_message(f"ERROR: Uplink alert failed: {e}")

def send_event_to_servicenow(network_name, device_name, serial, intf, ip, status, notes):
    """Send event to ServiceNow with comprehensive logging"""
    
    log_message(f"DEBUG: Creating ServiceNow event for {device_name} {intf} - Status: {status}")
    
    # Generate event time
    event_time = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")
    
    # Create short description (subject line)
    short_description = f"Meraki Uplink Failure Alert - {network_name} - {device_name} - {intf} - {status.title()}"
    
    # Move detailed description into additional_info
    additional_info_block = f"""Location Name: {network_name}
Hostname: {device_name}
MX Serial Number: {serial}
Interface: {intf}
IP Address: {ip}
Link Status: {status.title()}
MX Note: {notes}"""

    additional_info = {
        "priority": 3,
        "assignment_group": "Network Operations",
        "category": "network",
        "subcategory": "WAN",
        "details": additional_info_block
    }

    payload = {
        "resolution_state": "New",
        "description": short_description,
        "source": "Meraki",
        "type": "",
        "metric_name": "Meraki Uplink Failure Alert",
        "severity": "1",
        "resource": device_name,
        "node": device_name,
        "additional_info": json.dumps(additional_info),
        "event_class": "Custom Meraki Event Management",
        "time_of_event": event_time
    }

    log_message(f"DEBUG: ServiceNow payload prepared for {device_name}")
    log_message(f"DEBUG: ServiceNow endpoint: {SNOW_ENDPOINT}")

    try:
        log_message(f"INFO: Sending ServiceNow event for {device_name} {intf}")
        
        response = requests.post(
            SNOW_ENDPOINT,
            auth=(SNOW_USERNAME, SNOW_PASSWORD),
            headers={"Content-Type": "application/json"},
            json=payload,
            timeout=30  # Add timeout for better error handling
        )
        
        log_message(f"DEBUG: ServiceNow response status: {response.status_code}")

        if response.status_code == 200:
            log_message(f"SUCCESS: ServiceNow event created successfully for {device_name} {intf}")
            try:
                response_data = response.json()
                if 'result' in response_data and 'sys_id' in response_data['result']:
                    event_id = response_data['result']['sys_id']
                    log_message(f"INFO: ServiceNow event ID: {event_id}")
            except Exception:
                log_message(f"DEBUG: Could not parse ServiceNow response JSON")
        elif response.status_code == 201:
            log_message(f"SUCCESS: ServiceNow event created (201) for {device_name} {intf}")
        else:
            log_message(f"ERROR: ServiceNow event creation failed for {device_name}. Status: {response.status_code}")
            log_message(f"ERROR: ServiceNow response: {response.text[:500]}")

    except requests.exceptions.Timeout:
        log_message(f"ERROR: ServiceNow request timeout for {device_name} {intf}")
    except requests.exceptions.ConnectionError:
        log_message(f"ERROR: ServiceNow connection error for {device_name} {intf}")
    except requests.exceptions.RequestException as e:
        log_message(f"ERROR: ServiceNow request exception for {device_name}: {e}")
    except Exception as e:
        log_message(f"ERROR: Unexpected ServiceNow error for {device_name}: {e}")

def check_and_alert():
    """Main function with cache corruption handling"""
    log_message("INFO: Starting uplink monitoring cycle")
    
    # Log folder statistics
    log_stats = get_log_folder_stats()
    if "error" not in log_stats:
        log_message(f"INFO: Log folder stats - Files: {log_stats['file_count']}, "
                   f"Size: {log_stats['total_size_mb']:.2f} MB, "
                   f"Oldest: {log_stats['oldest_file']}")
    
    # Cleanup old log files first (only based on count)
    cleanup_old_logs()
    
    # Cleanup old cache backups
    cleanup_cache_backups()
    
    # Validate ServiceNow configuration
    servicenow_enabled = validate_servicenow_config()
    
    # Step 1: Check cache integrity BEFORE API calls
    log_message("DEBUG: Checking cache integrity before API calls")
    cache_status = load_and_validate_cache()
    
    # Step 2: Handle corruption/empty cache scenarios
    if cache_status["is_corrupted"] or cache_status["is_empty"]:
        log_message("CRITICAL: Cache corruption or empty cache detected")
        log_message(f"CRITICAL: Error details - {cache_status['error_message']}")
        
        # Send cache corruption alert to technical team
        send_corruption_alert(cache_status)
        
        # Create new cache but DON'T send uplink alerts this cycle
        log_message("INFO: Proceeding with API calls to rebuild cache - NO UPLINK ALERTS WILL BE SENT")
        
        # Fetch current data to rebuild cache
        current_status = fetch_appliance_uplink_status()
        device_details = fetch_device_details()
        network_details = fetch_network_details()
        
        if current_status and device_details and network_details:
            # Save new structured cache
            if save_structured_cache(current_status, device_details, network_details):
                log_message("SUCCESS: Cache rebuilt successfully")
            else:
                log_message("ERROR: Failed to rebuild cache")
        else:
            log_message("ERROR: Failed to fetch API data for cache rebuild")
        
        log_message("INFO: Cache repair cycle completed - No uplink alerts sent")
        return
    
    # Step 3: Normal operation with valid cache
    log_message("INFO: Cache is healthy - proceeding with normal alert processing")
    
    exc = load_all_exceptions()
    current_status = fetch_appliance_uplink_status()
    device_details = fetch_device_details()
    network_details = fetch_network_details()
    
    if not current_status or not device_details or not network_details:
        log_message("ERROR: Failed to fetch required API data")
        return
    
    device_map = {d["serial"]: d for d in device_details if "serial" in d}
    network_map = {n["id"]: n["name"] for n in network_details}
    
    log_message(f"DEBUG: Processing {len(current_status)} devices for alerts")
    
    alerts_sent = 0
    cached_data = cache_status["data"]
    
    for dev in current_status:
        net_id = dev.get("networkId", "")
        network_name = network_map.get(net_id, "Unknown Network")

        # --- Type 1: Exact network name match ---
        if network_name in exc["net_exact"]:
            log_message(f"INFO: Skipping network (NET exact match): {network_name}")
            continue

        # --- Type 2: Keyword match ---
        matched_kw = [kw for kw in exc["keywords"] if kw in network_name]
        if matched_kw:
            log_message(f"INFO: Skipping network (KW match): {network_name} (keyword: {', '.join(matched_kw)})")
            continue

        serial = dev.get("serial", "")
        uplinks = dev.get("uplinks", [])
        device = device_map.get(serial, {})
        notes = device.get("notes", "No Notes")
        device_name = device.get("name", "Unknown")

        for upl in uplinks:
            intf = upl.get("interface", "")
            status = upl.get("status", "").lower()
            ip = upl.get("ip", "")

            # --- Type 3: Interface suppression ---
            matched_intf = next(
                (r for r in exc["interfaces"]
                 if r["network"] == network_name and r["device"] == device_name and r["intf"] == intf),
                None
            )
            if matched_intf:
                log_message(f"INFO: Skipping interface (INTF rule): {device_name} {intf} in {network_name} (rule: {matched_intf['raw']})")
                continue

            # Get previous status from structured cache
            prev_status = get_previous_uplink_status(serial, intf, cached_data)
            
            log_message(f"DEBUG: {serial} {intf} - Current: {status}, Previous: {prev_status}")

            if status in ["failed", "not connected"] and prev_status and prev_status != status:
                log_message(f"ALERT: Processing uplink alert for {device_name} {intf} - {prev_status} -> {status}")

                subject_line = f"Meraki Uplink Failure Alert - {network_name} - {device_name} - {intf} - {status.title()}"

                email_body = f"""
                <html><body>
                <h2 style="color:#1E90FF;">Meraki Uplink Alert</h2>
                <p><strong>Dear Team,</strong></p>
                <p>The following uplink issue was detected:</p>
                <table border="1" cellpadding="5" cellspacing="0">
                    <tr style="background:#1E90FF; color:#000; font-weight:bold;">
                        <th>Network</th><th>Device</th><th>Serial</th>
                        <th>Interface</th><th>IP</th><th>Status</th><th>Previous</th><th>Notes</th>
                    </tr>
                    <tr>
                        <td>{network_name}</td>
                        <td>{device_name}</td>
                        <td>{serial}</td>
                        <td>{intf}</td>
                        <td>{ip}</td>
                        <td>{status.title()}</td>
                        <td>{prev_status}</td>
                        <td>{notes}</td>
                    </tr>
                </table>
                <p>Best regards,<br>Meraki Monitoring System</p>
                </body></html>
                """

                # Send uplink alert to operations team
                try:
                    send_email_alert(subject_line, email_body)
                    log_message(f"SUCCESS: Uplink email alert sent for {device_name} {intf}")
                except Exception as e:
                    log_message(f"ERROR: Uplink email alert failed for {device_name} {intf}: {e}")

                # Send ServiceNow event
                if servicenow_enabled:
                    try:
                        send_event_to_servicenow(network_name, device_name, serial, intf, ip, status, notes)
                        log_message(f"INFO: ServiceNow event processing completed for {device_name} {intf}")
                    except Exception as e:
                        log_message(f"ERROR: ServiceNow event processing failed for {device_name} {intf}: {e}")
                else:
                    log_message(f"WARNING: ServiceNow disabled - skipping event creation for {device_name} {intf}")

                alerts_sent += 1
                log_message(f"SUMMARY: Uplink alert #{alerts_sent} processed for {device_name} {intf}")

    # Save updated cache
    save_structured_cache(current_status, device_details, network_details)
    
    log_message(f"INFO: Monitoring cycle completed - {alerts_sent} uplink alerts sent to operations team")

if __name__ == "__main__":
    log_message("INFO: Meraki uplink monitoring script started")
    try:
        check_and_alert()
        log_message("INFO: Script completed successfully")
    except Exception as e:
        log_message(f"CRITICAL: Script failed with exception: {e}")
        raise
