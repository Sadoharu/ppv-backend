# backend/services/media_security.py
import hashlib
import time
import base64
from urllib.parse import urljoin
from backend.core.config import settings

class BunnySecurityService:
    @staticmethod
    def generate_signed_url(video_path: str, expire_seconds: int = 10800) -> str:
        """
        Генерує підписаний URL для Bunny CDN.
        
        :param video_path: Шлях до файлу або папки (наприклад, '/video-123/playlist.m3u8')
        :param expire_seconds: Час життя посилання в секундах (за замовчуванням 3 години)
        """
        
        # Якщо ключі не задані (наприклад, локальний дев без стрімінгу), повертаємо як є або пустий рядок
        if not settings.bunny_security_key or not settings.bunny_pull_zone_host:
            # Можна кидати помилку або повертати заглушку
            return video_path
        
        # Видаляємо слеш на початку, якщо він є, для коректної конкатенації
        path = video_path.strip("/")
        
        expires = int(time.time()) + expire_seconds
        
        # Формування токена для Bunny CDN (Token Authentication)
        # Логіка: sha256(securityKey + path + expires)
        
        token_content = f"{settings.bunny_security_key}{path}{expires}"
        
        md5_hash = hashlib.md5(token_content.encode('utf-8')).digest()
        token = base64.b64encode(md5_hash).decode('utf-8') \
            .replace("\n", "") \
            .replace("+", "-") \
            .replace("/", "_") \
            .replace("=", "")

        # Формування фінального URL
        # Bunny CDN формат: https://host/path?token=XYZ&expires=123
        base_url = urljoin(settings.bunny_pull_zone_host, path)
        signed_url = f"{base_url}?token={token}&expires={expires}"
        
        return signed_url

    @staticmethod
    def get_mux_metadata(event_title: str, video_id: str, user_id: str = None):
        """
        Формує метадані для Mux Data, які будуть передані на фронтенд.
        """
        return {
            "env_key": settings.mux_env_key,
            "metadata": {
                "video_id": video_id,
                "video_title": event_title,
                "viewer_user_id": str(user_id) if user_id else "anonymous",
                "player_name": "videojs-ppv-player"
            }
        }
