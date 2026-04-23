"""
HelperX Dashboard — Flask Backend mit Discord OAuth2
"""

from flask import Flask, jsonify, request, send_from_directory, session, redirect
from flask_cors import CORS
import json, os, copy, secrets
import urllib.request, urllib.error, urllib.parse
import requests as req
from functools import wraps

app = Flask(__name__, static_folder=".")
app.secret_key = os.environ.get("SECRET_KEY", secrets.token_hex(32))
CORS(app, supports_credentials=True)

# ── Discord OAuth2 Config (als Env-Variablen setzen!) ──────────────────────
DISCORD_CLIENT_ID     = os.environ.get("DISCORD_CLIENT_ID", "")
DISCORD_CLIENT_SECRET = os.environ.get("DISCORD_CLIENT_SECRET", "")
DISCORD_REDIRECT_URI  = os.environ.get("DISCORD_REDIRECT_URI", "http://localhost:5000/auth/callback")
DISCORD_API           = "https://discord.com/api/v10"
MANAGE_GUILD          = 0x20  # Permission-Bit: Server verwalten

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

# ── Hilfsfunktionen ────────────────────────────────────────────────────────

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

def get_user_guild_ids():
    return set(session.get("guild_ids", []))

# ── Auth-Decorators ────────────────────────────────────────────────────────

def require_auth(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        if "user_id" not in session:
            return jsonify({"error": "Nicht eingeloggt", "login": "/auth/login"}), 401
        return f(*args, **kwargs)
    return decorated

def require_guild_access(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        if "user_id" not in session:
            return jsonify({"error": "Nicht eingeloggt", "login": "/auth/login"}), 401
        guild_id = str(kwargs.get("guild_id", ""))
        if guild_id not in get_user_guild_ids():
            return jsonify({"error": "Kein Zugriff auf diesen Server"}), 403
        return f(*args, **kwargs)
    return decorated

# ── OAuth2 Routes ──────────────────────────────────────────────────────────

@app.route("/auth/login")
def auth_login():
    state = secrets.token_urlsafe(16)
    session["oauth_state"] = state
    params = urllib.parse.urlencode({
        "client_id":     DISCORD_CLIENT_ID,
        "redirect_uri":  DISCORD_REDIRECT_URI,
        "response_type": "code",
        "scope":         "identify guilds",
        "state":         state,
    })
    return redirect(f"https://discord.com/oauth2/authorize?{params}")

@app.route("/auth/callback")
def auth_callback():
    code  = request.args.get("code")
    state = request.args.get("state")

    if not code or state != session.pop("oauth_state", None):
        return "Ungültiger Login-Versuch (State mismatch).", 400

    # Code gegen Access Token tauschen
    token_resp = req.post(f"{DISCORD_API}/oauth2/token", data={
        "client_id":     DISCORD_CLIENT_ID,
        "client_secret": DISCORD_CLIENT_SECRET,
        "grant_type":    "authorization_code",
        "code":          code,
        "redirect_uri":  DISCORD_REDIRECT_URI,
    }, headers={"Content-Type": "application/x-www-form-urlencoded"})

    if token_resp.status_code != 200:
        return f"Token-Fehler: {token_resp.text}", 400

    access_token = token_resp.json()["access_token"]
    headers = {"Authorization": f"Bearer {access_token}"}

    # User-Info + Guilds von Discord holen
    user   = req.get(f"{DISCORD_API}/users/@me", headers=headers).json()
    guilds = req.get(f"{DISCORD_API}/users/@me/guilds", headers=headers).json()

    # Nur Guilds wo User MANAGE_GUILD hat (Admin / Owner)
    managed_ids = [
        g["id"] for g in guilds
        if int(g.get("permissions", 0)) & MANAGE_GUILD
    ]

    session["user_id"]   = user["id"]
    session["username"]  = user.get("global_name") or user["username"]
    session["avatar"]    = user.get("avatar")
    session["guild_ids"] = managed_ids

    return redirect("/")

@app.route("/auth/logout")
def auth_logout():
    session.clear()
    return redirect("/login.html")

@app.route("/auth/me")
def auth_me():
    if "user_id" not in session:
        return jsonify({"logged_in": False})
    return jsonify({
        "logged_in": True,
        "user_id":   session["user_id"],
        "username":  session["username"],
        "avatar":    session["avatar"],
        "guild_ids": session["guild_ids"],
    })

# ── API Routes (geschützt) ─────────────────────────────────────────────────

@app.route("/api/guilds")
@require_auth
def get_guilds():
    """Gibt nur die Guilds des eingeloggten Users zurück."""
    all_data = load_json(FILES["guild"])
    user_ids = get_user_guild_ids()
    # Schnittmenge: existiert in config UND gehört dem User
    visible = [gid for gid in all_data.keys() if gid in user_ids]
    return jsonify(visible)

@app.route("/api/guild/<guild_id>", methods=["GET"])
@require_guild_access
def get_guild(guild_id):
    data = load_json(FILES["guild"])
    cfg  = copy.deepcopy(DEFAULT_GUILD)
    cfg.update(data.get(str(guild_id), {}))
    return jsonify(cfg)

@app.route("/api/guild/<guild_id>", methods=["POST"])
@require_guild_access
def save_guild(guild_id):
    data     = load_json(FILES["guild"])
    incoming = request.json or {}
    if str(guild_id) not in data:
        data[str(guild_id)] = copy.deepcopy(DEFAULT_GUILD)
    data[str(guild_id)].update(incoming)
    return jsonify({"success": save_json(FILES["guild"], data)})

@app.route("/api/automod/<guild_id>", methods=["GET"])
@require_guild_access
def get_automod(guild_id):
    data = load_json(FILES["automod"])
    return jsonify(data.get(str(guild_id), {}))

@app.route("/api/automod/<guild_id>", methods=["POST"])
@require_guild_access
def save_automod(guild_id):
    data     = load_json(FILES["automod"])
    incoming = request.json or {}
    if str(guild_id) not in data:
        data[str(guild_id)] = {}
    data[str(guild_id)].update(incoming)
    return jsonify({"success": save_json(FILES["automod"], data)})

@app.route("/api/stats")
@require_auth
def get_stats():
    guild_data = load_json(FILES["guild"])
    warnings   = load_json(FILES["warnings"])
    # Nur Stats für eigene Guilds
    user_ids   = get_user_guild_ids()
    own_guilds = {k: v for k, v in guild_data.items() if k in user_ids}
    return jsonify({
        "total_guilds":        len(own_guilds),
        "total_warnings":      sum(len(v) for v in warnings.values() if isinstance(v, list)),
        "guilds_with_welcome": sum(1 for g in own_guilds.values() if g.get("welcome_enabled")),
        "guilds_with_automod": sum(1 for g in own_guilds.values() if g.get("automod_enabled")),
        "guilds_with_logging": sum(1 for g in own_guilds.values() if g.get("log_enabled")),
    })

@app.route("/api/send-message", methods=["POST"])
@require_auth
def send_message():
    data       = request.json or {}
    channel_id = data.get("channel_id", "").strip()
    message    = data.get("message", "").strip()
    token      = data.get("token", "").strip()

    if not channel_id or not message or not token:
        return jsonify({"success": False, "error": "channel_id, message und token werden benötigt."})

    url     = f"https://discord.com/api/v10/channels/{channel_id}/messages"
    payload = json.dumps({"content": message}).encode("utf-8")
    req_obj = urllib.request.Request(
        url, data=payload,
        headers={
            "Authorization": f"Bot {token}",
            "Content-Type":  "application/json",
            "User-Agent":    "HelperXDashboard/1.0",
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(req_obj) as resp:
            resp_data = json.loads(resp.read().decode())
            return jsonify({"success": True, "message_id": resp_data.get("id")})
    except urllib.error.HTTPError as e:
        body = e.read().decode()
        return jsonify({"success": False, "error": f"Discord API {e.code}: {body}"})
    except Exception as e:
        return jsonify({"success": False, "error": str(e)})

# ── Static Files ───────────────────────────────────────────────────────────

@app.route("/")
def index():
    if "user_id" not in session:
        return redirect("/login.html")
    return send_from_directory(".", "index.html")

@app.route("/login.html")
def login_page():
    return send_from_directory(".", "login.html")

if __name__ == "__main__":
    print("🚀 HelperX Dashboard → http://localhost:5000")
    port = int(os.environ.get("PORT", 5000))
    app.run(debug=False, host="0.0.0.0", port=port)
