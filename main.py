import os
import time
import json
import logging
import requests
from datetime import datetime, timedelta
from flask import Flask
import threading
# ========== Configuration ==========

YOUTUBE_API_KEY = os.getenv("YOUTUBE_API_KEY", "YOUR_YOUTUBE_API_KEY")
CHANNEL_ID = os.getenv("CHANNEL_ID", "YOUR_CHANNEL_ID")
DISCORD_WEBHOOK_URL = os.getenv("DISCORD_WEBHOOK_URL", "YOUR_DISCORD_WEBHOOK_URL")


POLL_INTERVAL = 900  # default: 15 minutes
# Filename to persist last notified video ID 
STATE_FILE = "last_notified.json"
MAX_BACKOFF = 3600  # max backoff 1 hour

# Logging
logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
# Flask app for Render web service
app = Flask(__name__)

# ========== Persistent State ==========

def load_state():
    if os.path.exists(STATE_FILE):
        try:
            with open(STATE_FILE, "r") as f:
                return json.load(f)
        except Exception as e:
            logging.warning("Could not load state file: %s", e)
    return {}

def save_state(state):
    """
    Save state to disk.
    """
    try:
        with open(STATE_FILE, "w") as f:
            json.dump(state, f)
    except Exception as e:
        logging.warning("Failed to save state file: %s", e)


# ========== YouTube API ==========

def get_current_live_stream(channel_id, api_key):
    """
    Returns (video_id, title) if channel is currently live, else None.
    """
    url = "https://www.googleapis.com/youtube/v3/search"
    params = {
        "part": "snippet",
        "channelId": channel_id,
        "type": "video",
        "eventType": "live",
        "key": api_key,
        "maxResults": 1,
    }
    resp = requests.get(url, params=params, timeout=10)
    if resp.status_code != 200:
        logging.error("YouTube API error %d: %s", resp.status_code, resp.text)
        return None

    data = resp.json()
    items = data.get("items", [])
    if not items:
        return None

    video = items[0]
    video_id = video["id"]["videoId"]
    title = video["snippet"]["title"]
    return video_id, title


# ========== Discord ==========

def send_discord_notification(video_id, title):
    content = "@everyone Join the stream now!"
    embed = {
        "title": "🔴 GoatyaGG is LIVE!",
        "description": title,
        "url": f"https://youtu.be/{video_id}",
    }
    payload = {
        "content": content,
        "embeds": [embed],
        "allowed_mentions": {"parse": ["everyone"] # this lets @everyone actually ping
            }    
            }
    headers = {"Content-Type": "application/json"}
    # resp = requests.post(DISCORD_WEBHOOK_URL, json=payload, headers=headers)
    resp = requests.post(DISCORD_WEBHOOK_URL, data=json.dumps(payload), headers=headers)
    if resp.status_code not in (200, 204):
        logging.warning("Discord webhook failed: %d %s", resp.status_code, resp.text)


# ========== Polling Loop (Background Thread) ==========

def run_poll_loop():
    state = load_state()
    last_notified_video = state.get("last_notified_video_id")

    backoff = POLL_INTERVAL

    logging.info("Starting polling loop. Base interval = %d seconds", POLL_INTERVAL)

    # try:
    while True:
        try:
            live = get_current_live_stream(CHANNEL_ID, YOUTUBE_API_KEY)
            if live is not None:
                vid, title = live
                if vid != last_notified_video:
                    logging.info("New live stream found: %s — notifying", vid)
                    send_discord_notification(vid, title)
                    last_notified_video = vid
                    # Update state
                    state["last_notified_video_id"] = vid
                    save_state(state)
                else:
                    logging.debug("Already notified for %s", vid)

            else:
                logging.debug("No live stream currently.")

            # Reset backoff on success
            backoff = POLL_INTERVAL

        except Exception as e:
            logging.error("Exception in poll loop: %s", e)
            backoff = min(backoff * 2, MAX_BACKOFF)  # exponential backoff

        logging.info("Sleeping %d seconds before next check", backoff)
        time.sleep(backoff)

    # except KeyboardInterrupt:
    #     logging.info("Shutting down gracefully...")

# ========== Flask Routes ==========

@app.route("/")
def home():
    return "✅ YouTube → Discord notifier is running."


# ========== Entry Point ==========

if __name__ == "__main__":
    # Basic check of config
    if not (YOUTUBE_API_KEY and CHANNEL_ID and DISCORD_WEBHOOK_URL):
        logging.error("Missing configuration: please set YOUTUBE_API_KEY, CHANNEL_ID, DISCORD_WEBHOOK_URL")
        exit(1)

    # Start polling loop in background thread
    threading.Thread(target=run_poll_loop, daemon=True).start()

    # Start Flask server (Render expects a web server)
    port = int(os.getenv("PORT", 8000))
    app.run(host="0.0.0.0", port=port)
