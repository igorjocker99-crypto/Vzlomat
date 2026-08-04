import os
import json
import asyncio
import logging
from typing import Optional, Dict, List
from datetime import datetime
from telethon import TelegramClient, errors
from telethon.sessions import StringSession

logger = logging.getLogger(__name__)

class SessionManager:
    def __init__(self, sessions_dir: str = "sessions/valid", data_dir: str = "data"):
        self.sessions_dir = sessions_dir
        self.data_dir = data_dir
        self.db_path = os.path.join(data_dir, "db.json")
        os.makedirs(sessions_dir, exist_ok=True)
        os.makedirs(data_dir, exist_ok=True)
        self.db = self._load_db()
        self.api_id = 0
        self.api_hash = ""

    def configure(self, api_id: int, api_hash: str):
        self.api_id = api_id
        self.api_hash = api_hash

    def _load_db(self) -> Dict:
        if os.path.exists(self.db_path):
            with open(self.db_path, "r", encoding="utf-8") as f:
                return json.load(f)
        return {"sessions": {}, "stats": {"total": 0, "valid": 0, "invalid": 0}}

    def _save_db(self):
        with open(self.db_path, "w", encoding="utf-8") as f:
            json.dump(self.db, f, indent=2, ensure_ascii=False)

    def save_session(self, phone: str, session_string: str) -> bool:
        try:
            filename = f"session_{phone.replace('+', '')}.session"
            filepath = os.path.join(self.sessions_dir, filename)
            with open(filepath, "w", encoding="utf-8") as f:
                f.write(session_string)
            self.db["sessions"][phone] = {
                "phone": phone,
                "file": filename,
                "created_at": datetime.now().isoformat(),
                "valid": True
            }
            self.db["stats"]["total"] = len(self.db["sessions"])
            self.db["stats"]["valid"] = sum(1 for s in self.db["sessions"].values() if s.get("valid", False))
            self._save_db()
            logger.info(f"Сессия сохранена: {phone}")
            return True
        except Exception as e:
            logger.error(f"Ошибка сохранения сессии {phone}: {e}")
            return False

    async def validate_session(self, session_string: str, phone: str) -> bool:
        if not self.api_id or not self.api_hash:
            return False
        client = TelegramClient(StringSession(session_string), self.api_id, self.api_hash)
        try:
            await client.connect()
            return await client.is_user_authorized()
        except Exception:
            return False
        finally:
            await client.disconnect()

    def get_valid_sessions(self) -> List[Dict]:
        return [
            {"phone": p, "file": d.get("file", ""), "created_at": d.get("created_at", "")}
            for p, d in self.db["sessions"].items()
            if d.get("valid", False)
        ]

    def mark_invalid(self, phone: str):
        if phone in self.db["sessions"]:
            self.db["sessions"][phone]["valid"] = False
            filename = self.db["sessions"][phone].get("file", "")
            if filename:
                filepath = os.path.join(self.sessions_dir, filename)
                if os.path.exists(filepath):
                    os.remove(filepath)
            self.db["stats"]["valid"] = sum(1 for s in self.db["sessions"].values() if s.get("valid", False))
            self.db["stats"]["invalid"] = len(self.db["sessions"]) - self.db["stats"]["valid"]
            self._save_db()

    async def check_all_sessions(self) -> Dict:
        result = {"total": 0, "valid": 0, "invalid": 0}
        for phone, data in self.db["sessions"].items():
            result["total"] += 1
            if not data.get("valid", True):
                result["invalid"] += 1
                continue
            filename = data.get("file", "")
            if not filename:
                self.mark_invalid(phone)
                result["invalid"] += 1
                continue
            filepath = os.path.join(self.sessions_dir, filename)
            if not os.path.exists(filepath):
                self.mark_invalid(phone)
                result["invalid"] += 1
                continue
            with open(filepath, "r", encoding="utf-8") as f:
                session_string = f.read().strip()
            is_valid = await self.validate_session(session_string, phone)
            if is_valid:
                result["valid"] += 1
            else:
                self.mark_invalid(phone)
                result["invalid"] += 1
        self.db["stats"] = result
        self._save_db()
        return result

    def get_stats(self) -> Dict:
        return self.db.get("stats", {"total": 0, "valid": 0, "invalid": 0})

    def get_session_file(self, phone: str) -> Optional[str]:
        data = self.db["sessions"].get(phone)
        if not data or not data.get("valid", False):
            return None
        filename = data.get("file", "")
        if not filename:
            return None
        filepath = os.path.join(self.sessions_dir, filename)
        if not os.path.exists(filepath):
            self.mark_invalid(phone)
            return None
        with open(filepath, "r", encoding="utf-8") as f:
            return f.read().strip()

    def get_session_by_index(self, index: int) -> Optional[Dict]:
        valid = self.get_valid_sessions()
        if 0 <= index < len(valid):
            return valid[index]
        return None