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
        
        # Якщо ключі не задані, повертаємо шлях як є (fallback)
        if not settings.bunny_security_key or not settings.bunny_pull_zone_host:
            return video_path
        
        # Видаляємо слеш на початку для коректної конкатенації
        path = video_path.strip("/")
        
        expires = int(time.time()) + expire_seconds
        
        # Формування токена: sha256(securityKey + path + expires)
        token_content = f"{settings.bunny_security_key}{path}{expires}"
        
        md5_hash = hashlib.md5(token_content.encode('utf-8')).digest()
        token = base64.b64encode(md5_hash).decode('utf-8') \
            .replace("\n", "") \
            .replace("+", "-") \
            .replace("/", "_") \
            .replace("=", "")

        # Формування фінального URL
        base_url = urljoin(settings.bunny_pull_zone_host, path)
        signed_url = f"{base_url}?token={token}&expires={expires}"
        
        return signed_url

    @staticmethod
    def get_mux_metadata(event_title: str, video_id: str, env_key: str = None, user_id: str = None):
        """
        Формує метадані для Mux Data.
        """
        # Використовуємо переданий ключ (пріоритет), або глобальний з налаштувань
        final_key = env_key or settings.mux_env_key
        
        if not final_key:
            return None

        return {
            "env_key": final_key,
            "metadata": {
                "video_id": video_id,
                "video_title": event_title,
                "viewer_user_id": str(user_id) if user_id else "anonymous",
                "player_name": "videojs-ppv-player"
            }
        }