import json
from pathlib import Path
from urllib.parse import urlparse
from zoneinfo import ZoneInfo


class SettingsService:
    def __init__(self, settings_path: str | Path, default_timezone: str = "UTC") -> None:
        self.settings_path = Path(settings_path)
        self.default_timezone = default_timezone

    def get_timezone(self) -> str:
        settings = self._read_settings()
        return settings.get("timezone", self.default_timezone)

    def set_timezone(self, timezone_name: str) -> str:
        self._validate_timezone(timezone_name)
        settings = self._read_settings()
        settings["timezone"] = timezone_name
        self._write_settings(settings)
        return timezone_name

    def get_calendar_urls(self) -> list[str]:
        settings = self._read_settings()
        calendar_urls = settings.get("calendar_urls", [])
        if not isinstance(calendar_urls, list):
            return []
        return [url for url in calendar_urls if isinstance(url, str)]

    def add_calendar_url(self, calendar_url: str) -> list[str]:
        self._validate_calendar_url(calendar_url)
        settings = self._read_settings()
        calendar_urls = settings.get("calendar_urls", [])
        if not isinstance(calendar_urls, list):
            calendar_urls = []

        if calendar_url not in calendar_urls:
            calendar_urls.append(calendar_url)

        settings["calendar_urls"] = calendar_urls
        self._write_settings(settings)
        return calendar_urls

    def remove_calendar_url(self, index: int) -> list[str]:
        settings = self._read_settings()
        calendar_urls = settings.get("calendar_urls", [])
        if not isinstance(calendar_urls, list):
            raise ValueError("No calendars configured")
        if index < 0 or index >= len(calendar_urls):
            raise ValueError("Calendar index out of range")

        calendar_urls.pop(index)
        settings["calendar_urls"] = calendar_urls
        self._write_settings(settings)
        return calendar_urls

    def _validate_timezone(self, timezone_name: str) -> None:
        try:
            ZoneInfo(timezone_name)
        except Exception as error:
            raise ValueError(f"Invalid timezone: {timezone_name}") from error

    def _validate_calendar_url(self, calendar_url: str) -> None:
        parsed_url = urlparse(calendar_url)
        if parsed_url.scheme not in {"http", "https", "webcal"} or not parsed_url.netloc:
            raise ValueError(f"Invalid calendar URL: {calendar_url}")

    def _read_settings(self) -> dict:
        if not self.settings_path.exists():
            return {}

        with self.settings_path.open("r", encoding="utf-8") as file:
            return json.load(file)

    def _write_settings(self, settings: dict) -> None:
        self.settings_path.parent.mkdir(parents=True, exist_ok=True)

        with self.settings_path.open("w", encoding="utf-8") as file:
            json.dump(settings, file, indent=2)
