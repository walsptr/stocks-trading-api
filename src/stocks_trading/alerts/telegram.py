import asyncio
import json
import urllib.error
import urllib.parse
import urllib.request


class TelegramDeliveryError(RuntimeError):
    pass


class TelegramClient:
    def __init__(self, bot_token: str | None, chat_id: str | None) -> None:
        self.bot_token = bot_token
        self.chat_id = chat_id

    @property
    def configured(self) -> bool:
        return bool(self.bot_token and self.chat_id)

    async def send(self, message: str) -> None:
        if not self.configured:
            raise TelegramDeliveryError("Telegram credentials are not configured")
        await asyncio.to_thread(self._send_sync, message)

    def _send_sync(self, message: str) -> None:
        url = f"https://api.telegram.org/bot{self.bot_token}/sendMessage"
        payload = urllib.parse.urlencode({"chat_id": self.chat_id, "text": message}).encode()
        request = urllib.request.Request(url, data=payload, method="POST")
        try:
            with urllib.request.urlopen(request, timeout=15) as response:
                body = json.loads(response.read().decode("utf-8"))
        except (urllib.error.URLError, TimeoutError, ValueError) as error:
            raise TelegramDeliveryError(f"Telegram delivery failed: {error}") from error
        if not body.get("ok"):
            description = body.get("description", "unknown Telegram error")
            raise TelegramDeliveryError(f"Telegram delivery failed: {description}")
