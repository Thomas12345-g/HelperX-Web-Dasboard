"""
HelperX Dashboard — Flask Backend
Startet mit: python app.py
Läuft auf:   http://localhost:5000
"""

from flask import Flask, jsonify, request, send_from_directory
from flask_cors import CORS
import json, os, copy, asyncio, threading
import urllib.request, urllib.error

app = Flask(__name__, static_folder=".")
CORS(app)

BASE_DIR = os.path.dirname(os.path.abspath(__file__))

FILES = {
    "guild":    os.path.join(BASE_DIR, "guild_config.json"),
    "automod":  os.path.join(BASE_DIR, "automod_config.json"),
    "tickets":  os.path.join(BASE_DIR, "ticket_config.json"),
    "warnings": os.path.join(BASE_DIR, "warnings.json"),
    "stats":    os.path.join(BASE_DIR, "ticket_stats.json"),
}

DEFAULT_GUILD = {
    "welcome_enabled": False, "welcome_channel": None,
    "welcome_title": "👋 Willkommen auf {server}!",
    "welcome_message": "Hey {user}, schön dass du da bist! Du bist Mitglied #{count}.",
    "welcome_color": "#5865F2", "welcome_thumbnail": None, "welcome_banner": None,
    "log_enabled": False, "log_channel": None, "mod_log_channel": None,
    "log_joins": True, "log_leaves": True, "log_bans": True,
    "log_msg_edit": True, "log_msg_delete": True,
    "automod_enabled": False, "automod_action": "delete",
    "automod_spam": True, "automod_spam_limit": 5, "automod_spam_window": 5,
    "automod_links": False, "automod_caps": False, "automod_caps_pct": 70,
    "automod_mute_minutes": 5, "automod_whitelist_roles": [],
}

def load_json(path, default=None):
    if os.path.exists(path):
        try:
            with open(path, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception as e:
            print(f"[Load] {path}: {e}")
    return default if default is not None else {}

def save_json(path, data):
    try:
        with open(path, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2, ensure_ascii=False)
        return True
    except Exception as e:
        print(f"[Save] {path}: {e}")
        return False

@app.route("/api/guilds")
def get_guilds():
    data = load_json(FILES["guild"])
    return jsonify(list(data.keys()))

@app.route("/api/guild/<guild_id>", methods=["GET"])
def get_guild(guild_id):
    data = load_json(FILES["guild"])
    cfg = copy.deepcopy(DEFAULT_GUILD)
    cfg.update(data.get(str(guild_id), {}))
    return jsonify(cfg)

@app.route("/api/guild/<guild_id>", methods=["POST"])
def save_guild(guild_id):
    data = load_json(FILES["guild"])
    incoming = request.json or {}
    if str(guild_id) not in data:
        data[str(guild_id)] = copy.deepcopy(DEFAULT_GUILD)
    data[str(guild_id)].update(incoming)
    return jsonify({"success": save_json(FILES["guild"], data)})

@app.route("/api/automod/<guild_id>", methods=["GET"])
def get_automod(guild_id):
    data = load_json(FILES["automod"])
    return jsonify(data.get(str(guild_id), {}))

@app.route("/api/automod/<guild_id>", methods=["POST"])
def save_automod(guild_id):
    data = load_json(FILES["automod"])
    incoming = request.json or {}
    if str(guild_id) not in data:
        data[str(guild_id)] = {}
    data[str(guild_id)].update(incoming)
    return jsonify({"success": save_json(FILES["automod"], data)})

@app.route("/api/stats")
def get_stats():
    guild_data = load_json(FILES["guild"])
    warnings   = load_json(FILES["warnings"])
    return jsonify({
        "total_guilds":         len(guild_data),
        "total_warnings":       sum(len(v) for v in warnings.values() if isinstance(v, list)),
        "guilds_with_welcome":  sum(1 for g in guild_data.values() if g.get("welcome_enabled")),
        "guilds_with_automod":  sum(1 for g in guild_data.values() if g.get("automod_enabled")),
        "guilds_with_logging":  sum(1 for g in guild_data.values() if g.get("log_enabled")),
    })

@app.route("/api/send-message", methods=["POST"])
def send_message():
    data = request.json or {}
    channel_id = data.get("channel_id", "").strip()
    message    = data.get("message", "").strip()
    token      = data.get("token", "").strip()

    if not channel_id or not message or not token:
        return jsonify({"success": False, "error": "channel_id, message und token werden benötigt."})

    url     = f"https://discord.com/api/v10/channels/{channel_id}/messages"
    payload = json.dumps({"content": message}).encode("utf-8")
    req     = urllib.request.Request(
        url,
        data    = payload,
        headers = {
            "Authorization": f"Bot {token}",
            "Content-Type":  "application/json",
            "User-Agent":    "HelperXDashboard/1.0",
        },
        method = "POST",
    )
    try:
        with urllib.request.urlopen(req) as resp:
            resp_data = json.loads(resp.read().decode())
            return jsonify({"success": True, "message_id": resp_data.get("id")})
    except urllib.error.HTTPError as e:
        body = e.read().decode()
        return jsonify({"success": False, "error": f"Discord API {e.code}: {body}"})
    except Exception as e:
        return jsonify({"success": False, "error": str(e)})

@app.route("/")
def index():
    return send_from_directory(".", "index.html")

if __name__ == "__main__":
    print("🚀 HelperX Dashboard → http://localhost:5000")
    port = int(os.environ.get("PORT", 5000))
    app.run(debug=False, host="0.0.0.0", port=port)
