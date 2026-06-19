from services.api_client import api_client
from services.artwork_service import ArtworkService
from services.download_service import DownloadService
from services.error_notifier import UploadErrorNotifier
from services.lyrics_service import lyrics_service
from services.music_adapter import MusicAdapter
from services.odesli_service import OdesliService
from services.rate_limiter import search_rate_limiter, download_rate_limiter
from services.registration_service import UserRegistrationService
from services.search_cache_service import search_cache_service
from services.tagging_service import tagging_service
from services.task_manager import task_manager
from services.tracker import album_tracker
from services.user_settings_service import user_settings_service
from services.direct_download_service import DirectDownloadService

def init_services(bot):
    artwork_service = ArtworkService(api_client, user_settings_service)
    error_notifier = UploadErrorNotifier(api_client)
    download_service = DownloadService(
        bot, api_client, user_settings_service, artwork_service,
        tagging_service, error_notifier, album_tracker, download_rate_limiter
    )
    direct_download_service = DirectDownloadService(bot, tagging_service)
    registration_service = UserRegistrationService(api_client, user_settings_service)

    return {
        "api_client": api_client,
        "artwork_service": artwork_service,
        "download_service": download_service,
        "direct_download_service": direct_download_service,
        "error_notifier": error_notifier,
        "lyrics_service": lyrics_service,
        "music_adapter": MusicAdapter(),
        "odesli_service": OdesliService(),
        "search_rate_limiter": search_rate_limiter,
        "download_rate_limiter": download_rate_limiter,
        "registration_service": registration_service,
        "search_cache_service": search_cache_service,
        "tagging_service": tagging_service,
        "task_manager": task_manager,
        "album_tracker": album_tracker,
        "user_settings_service": user_settings_service
    }
