import logging
import os
import time # Make sure time is imported
import requests # Make sure requests is imported
from dotenv import load_dotenv
from telegram import Update
from telegram.ext import Application, CommandHandler, ContextTypes, MessageHandler, filters
 
# --- Configuration ---
load_dotenv() # Load variables from .env file
 
TELEGRAM_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
PROMETHEUS_URL = "http://localhost:9090" # Default Prometheus URL
 
# Mapping of user-friendly names to Prometheus agent_host labels
DEVICE_MAP = {
    "cisco_s1": "192.168.0.45",
    "huawei_ne40": "192.168.0.50", # Add Huawei using its IP
    # --- Placeholders ---
    # Add other devices here later if needed
}
 
# Mapping of SNMP interface operational status codes to readable text
OPER_STATUS_MAP = {
    1: "UP",
    2: "DOWN",
    3: "TESTING",
    4: "UNKNOWN",
    5: "DORMANT",
    6: "NOT PRESENT",
    7: "LOWER LAYER DOWN"
}
 
# How old (in seconds) can the last metric be to consider the device "reachable"
REACHABILITY_THRESHOLD = 120 # 2 minutes
 
# Enable logging
logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s", level=logging.INFO
)
# set higher logging level for httpx to avoid all GET and POST requests being logged
logging.getLogger("httpx").setLevel(logging.WARNING)
logger = logging.getLogger(__name__) # Use standard __name__
 
# --- Prometheus Query Function ---
def query_prometheus(query):
    """Sends a query to Prometheus and returns the JSON response."""
    api_url = f"{PROMETHEUS_URL}/api/v1/query"
    params = {'query': query}
    logger.info(f"Querying Prometheus: {query}") # Log the query being sent
    try:
        response = requests.get(api_url, params=params, timeout=10) # 10 second timeout
        response.raise_for_status() # Raise HTTPError for bad responses (4xx or 5xx)
        return response.json()
    except requests.exceptions.Timeout:
        logger.error(f"Timeout error querying Prometheus API at {api_url} with query: {query}")
        return {"status": "error", "errorType": "timeout", "error": "Prometheus query timed out"}
    except requests.exceptions.ConnectionError:
        logger.error(f"Connection error querying Prometheus API at {api_url}. Is Prometheus running?")
        return {"status": "error", "errorType": "connection", "error": "Could not connect to Prometheus"}
    except requests.exceptions.RequestException as e:
        logger.error(f"HTTP error querying Prometheus: {e}")
        # Try to get more specific error from response if possible
        error_detail = str(e)
        try:
            if e.response is not None:
               error_detail = f"{e} - {e.response.text}"
        except Exception:
            pass # Ignore errors trying to get more details
        return {"status": "error", "errorType": "http", "error": error_detail}
    except Exception as e:
        logger.error(f"An unexpected error occurred during Prometheus query: {e}")
        return {"status": "error", "errorType": "unexpected", "error": str(e)}
 
# --- Helper to extract metric value ---
def get_metric_value(prom_response, metric_type="value"):
    """Extracts the value or timestamp from a Prometheus query response."""
    if not prom_response or prom_response.get('status') != 'success':
        logger.warning(f"Prometheus query failed or returned error: {prom_response}")
        return None # Indicate query failure
 
    try:
        result = prom_response['data']['result']
        if result:
            # Handle instant vector results (most common for current values)
            if prom_response['data']['resultType'] == 'vector':
                if metric_type == "value":
                    return float(result[0]['value'][1]) # [1] is the value
                elif metric_type == "timestamp":
                    return float(result[0]['value'][0]) # [0] is the timestamp
            # Add handling for other types like scalar if needed later
            else:
                 logger.warning(f"Unsupported result type: {prom_response['data']['resultType']}")
                 return None
        else:
            # Query succeeded but returned no data
            logger.info("Prometheus query returned no data.")
            return None # Indicate no data found
    except (IndexError, KeyError, TypeError, ValueError) as e:
        logger.error(f"Error parsing metric value from response: {prom_response}. Error: {e}")
    return None # Indicate parsing failure
 
# --- Command Handlers ---
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Sends a welcome message when the /start command is issued."""
    user = update.effective_user
    await update.message.reply_html( # Use reply_html for the mention
        f"Hi {user.mention_html()}! I'm your Network Status Bot.",
    )
    await update.message.reply_text( # Plain text for the next message
        "Use the /status command to check device health."
    )
 
async def status(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Fetches and returns the status of a specified device from Prometheus."""
    if not context.args:
        # Define known_devices_str first
        known_devices_str = ", ".join(DEVICE_MAP.keys())
        # Send the usage message as plain text
        await update.message.reply_text(
            f'Please specify a device name. Usage: /status <device_name>\n'
            f'Known devices: {known_devices_str}'
            # No parse_mode needed
        )
        return
 
    device_name_req = context.args[0].lower()
    agent_host_ip = DEVICE_MAP.get(device_name_req)

    if not agent_host_ip:
        # Get known devices again for the error message
        known_devices_str = ", ".join(DEVICE_MAP.keys())
        await update.message.reply_text(
            f'Unknown device: "{device_name_req}".\n'
            f'Known devices: {known_devices_str}'
            # No parse_mode needed here either
        )
        return

    # Send initial feedback (Using HTML here is fine)
    processing_msg = await update.message.reply_text(
        f'🔄 Fetching status for <b>{device_name_req.upper()}</b> ({agent_host_ip})...',
        parse_mode='HTML'
    )
 
    # --- Build Queries (using agent_host label now) ---
    reachability_query = f'snmp_sysUpTime{{agent_host="{agent_host_ip}"}}'
    cpu_query = f'snmp_cpuUtil5Sec{{agent_host="{agent_host_ip}"}}'
    if0_status_query = f'snmp_if0_oper_status{{agent_host="{agent_host_ip}"}}' # Corrected name if Option B used
    if1_status_query = f'snmp_if1_oper_status{{agent_host="{agent_host_ip}"}}' # Corrected name if Option B used

    # --- Execute Queries ---
    reachability_resp = query_prometheus(reachability_query)
    cpu_resp = query_prometheus(cpu_query)
    if0_status_resp = query_prometheus(if0_status_query)
    if1_status_resp = query_prometheus(if1_status_query)
 
    # Check if any query failed critically (e.g., connection error)
    if any(resp and resp.get('status') == 'error' and resp.get('errorType') in ['connection', 'timeout'] for resp in [reachability_resp, cpu_resp, if0_status_resp, if1_status_resp]):
         await context.bot.edit_message_text(
             chat_id=processing_msg.chat_id,
             message_id=processing_msg.message_id,
             text=f"❌ Error connecting to Prometheus at {PROMETHEUS_URL}. Please check if it's running and accessible.",
         )
         return
 
    # --- Process Results & Format Message - Fixed HTML ---
    reply_lines = [f"📊 <b>Status for {device_name_req.upper()} ({agent_host_ip})</b>:"] # Use <b>
 
    # Reachability
    last_seen_ts = get_metric_value(reachability_resp, metric_type="timestamp")
    reachable = "❓ Unknown"
    last_seen_ago_str = "N/A"
    if last_seen_ts is not None:
        time_diff = time.time() - last_seen_ts
        last_seen_ago_str = f"{int(time_diff)} seconds ago"
        if time_diff < REACHABILITY_THRESHOLD:
            reachable = "✅ Yes"
        else:
            reachable = f"❌ No (Stale Data > {REACHABILITY_THRESHOLD}s)" # Use > for >
    elif reachability_resp and reachability_resp.get('status') == 'success':
         reachable = "❌ No (No Data)"
    else:
         reachable = "⚠️ Error"
 
    reply_lines.append(f"  <i>Device Reachable</i>: {reachable} (Last data: {last_seen_ago_str})") # Use <i>
 
    # CPU
    cpu_value = get_metric_value(cpu_resp)
    cpu_str = f"{int(cpu_value)} %" if cpu_value is not None else "N/A"
    reply_lines.append(f"  <i>CPU Usage (5s)</i>: {cpu_str}") # Use <i>
 
    reply_lines.append("  --- <i>Interfaces</i> ---") # Use <i>
 
    # Interface 0 Status
    if0_status_code = get_metric_value(if0_status_resp)
    if0_name = "if0"
    if0_status_str = "N/A"
    if if0_status_code is not None:
        if0_status_str_base = OPER_STATUS_MAP.get(int(if0_status_code), f"Unknown Code ({int(if0_status_code)})")
        if int(if0_status_code) == 1: if0_status_str = f"🟢 {if0_status_str_base}"
        elif int(if0_status_code) == 2: if0_status_str = f"🔴 {if0_status_str_base}"
        else: if0_status_str = f"🟡 {if0_status_str_base}"
    reply_lines.append(f"  <code>{if0_name}</code>: {if0_status_str}") # Use <code>
 
    # Interface 1 Status
    if1_status_code = get_metric_value(if1_status_resp)
    if1_name = "if1"
    if1_status_str = "N/A"
    if if1_status_code is not None:
        if1_status_str_base = OPER_STATUS_MAP.get(int(if1_status_code), f"Unknown Code ({int(if1_status_code)})")
        if int(if1_status_code) == 1: if1_status_str = f"🟢 {if1_status_str_base}"
        elif int(if1_status_code) == 2: if1_status_str = f"🔴 {if1_status_str_base}"
        else: if1_status_str = f"🟡 {if1_status_str_base}"
    reply_lines.append(f"  <code>{if1_name}</code>: {if1_status_str}") # Use <code>
 
    # Final edit call - Ensure parse_mode is HTML
    await context.bot.edit_message_text(
        chat_id=processing_msg.chat_id,
        message_id=processing_msg.message_id,
        text="\n".join(reply_lines),
        parse_mode='HTML'
    )
 
async def unknown(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handles any command that wasn't recognized."""
    await context.bot.send_message(chat_id=update.effective_chat.id, text="Sorry, I didn't understand that command.")
 
# --- Main Function ---
def main() -> None:
    """Start the bot."""
    if not TELEGRAM_TOKEN:
        logger.error("FATAL: TELEGRAM_BOT_TOKEN environment variable not set!")
        return
 
    logger.info("Creating Telegram Application...")
    application = Application.builder().token(TELEGRAM_TOKEN).build()
 
    # --- Register Handlers ---
    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("status", status))
    application.add_handler(MessageHandler(filters.COMMAND, unknown))
 
    # --- Start Polling ---
    logger.info("Starting Telegram bot polling...")
    application.run_polling(allowed_updates=Update.ALL_TYPES)
 
if __name__ == "__main__": # Corrected if __name__ == "__main__": check
    main()
#TELEGRAM_BOT_TOKEN=7883405256:AAGvP4rftxkfBcdxWIEatpTb5LvDaTJEVLs