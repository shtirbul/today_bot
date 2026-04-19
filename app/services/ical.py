from dataclasses import dataclass
from datetime import date, datetime, time, timedelta
from urllib.parse import urlparse, urlunparse
from zoneinfo import ZoneInfo

import recurring_ical_events
import requests
from icalendar import Calendar


@dataclass
class CalendarEvent:
    calendar_name: str
    summary: str
    start_at: datetime
    end_at: datetime
    all_day: bool


@dataclass
class CalendarFetchError:
    source: str
    message: str


class IcalService:
    def __init__(self, timeout: int = 30) -> None:
        self.timeout = timeout

    def get_events_for_today(
        self, calendar_urls: list[str], timezone_name: str
    ) -> tuple[list[CalendarEvent], list[CalendarFetchError]]:
        timezone = ZoneInfo(timezone_name)
        day_start = datetime.combine(
            datetime.now(timezone).date(),
            time.min,
            tzinfo=timezone,
        )
        day_end = day_start + timedelta(days=1)

        events: list[CalendarEvent] = []
        errors: list[CalendarFetchError] = []

        for calendar_url in calendar_urls:
            try:
                calendar_events = self._get_calendar_events(
                    calendar_url=calendar_url,
                    timezone=timezone,
                    day_start=day_start,
                    day_end=day_end,
                )
            except Exception as error:
                errors.append(CalendarFetchError(source=calendar_url, message=str(error)))
                continue

            events.extend(calendar_events)

        events.sort(key=lambda event: (event.start_at, event.calendar_name, event.summary))
        return events, errors

    def _get_calendar_events(
        self,
        calendar_url: str,
        timezone: ZoneInfo,
        day_start: datetime,
        day_end: datetime,
    ) -> list[CalendarEvent]:
        response = requests.get(self._normalize_calendar_url(calendar_url), timeout=self.timeout)
        if not response.ok:
            raise Exception(f"Failed to fetch calendar: {response.status_code}")

        calendar = Calendar.from_ical(response.text)
        calendar_name = str(calendar.get("X-WR-CALNAME", "Calendar"))
        raw_events = recurring_ical_events.of(calendar).between(day_start, day_end)

        events: list[CalendarEvent] = []

        for raw_event in raw_events:
            start_value = raw_event.decoded("DTSTART")
            end_value = raw_event.decoded("DTEND", None)
            event_start, event_end, all_day = self._normalize_event_bounds(
                start_value=start_value,
                end_value=end_value,
                timezone=timezone,
            )

            if event_end <= day_start or event_start >= day_end:
                continue

            events.append(
                CalendarEvent(
                    calendar_name=calendar_name,
                    summary=str(raw_event.get("SUMMARY", "Untitled event")),
                    start_at=event_start,
                    end_at=event_end,
                    all_day=all_day,
                )
            )

        return events

    def _normalize_calendar_url(self, calendar_url: str) -> str:
        parsed_url = urlparse(calendar_url)
        if parsed_url.scheme != "webcal":
            return calendar_url

        return urlunparse(parsed_url._replace(scheme="https"))

    def _normalize_event_bounds(
        self,
        start_value: datetime | date,
        end_value: datetime | date | None,
        timezone: ZoneInfo,
    ) -> tuple[datetime, datetime, bool]:
        all_day = isinstance(start_value, date) and not isinstance(start_value, datetime)

        if all_day:
            start_at = datetime.combine(start_value, time.min, tzinfo=timezone)
            if isinstance(end_value, date) and not isinstance(end_value, datetime):
                end_at = datetime.combine(end_value, time.min, tzinfo=timezone)
            else:
                end_at = start_at + timedelta(days=1)
            return start_at, end_at, True

        start_at = self._ensure_datetime_timezone(start_value, timezone)
        if isinstance(end_value, datetime):
            end_at = self._ensure_datetime_timezone(end_value, timezone)
        else:
            end_at = start_at + timedelta(hours=1)

        return start_at, end_at, False

    def _ensure_datetime_timezone(
        self, value: datetime | date, timezone: ZoneInfo
    ) -> datetime:
        if isinstance(value, datetime):
            if value.tzinfo is None:
                return value.replace(tzinfo=timezone)
            return value.astimezone(timezone)

        return datetime.combine(value, time.min, tzinfo=timezone)
