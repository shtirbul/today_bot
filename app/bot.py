from collections import defaultdict
from datetime import date, datetime, time
import logging
from pathlib import Path
from urllib.parse import urlparse
from zoneinfo import ZoneInfo

from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram import ReplyKeyboardMarkup
from telegram.ext import (
    Application,
    ApplicationBuilder,
    CallbackQueryHandler,
    CommandHandler,
    ContextTypes,
    MessageHandler,
    filters,
)

try:
    from app.services.ical import CalendarEvent, IcalService
    from app.services.settings import SettingsService
    from app.services.todoist import TodoistService
except ImportError:
    from services.ical import CalendarEvent, IcalService
    from services.settings import SettingsService
    from services.todoist import TodoistService


logger = logging.getLogger(__name__)


def create_application(
    bot_token: str,
    ical_service: IcalService,
    todoist_service: TodoistService,
    settings_service: SettingsService,
    admin_user_id: int,
) -> Application:
    application = ApplicationBuilder().token(bot_token).build()
    application.bot_data["timezone"] = settings_service.get_timezone()
    tasks_button = "📋 Tasks"
    events_button = "📅 Events"
    admin_button = "⚙️ Admin"

    def is_admin(update: Update) -> bool:
        user = update.effective_user
        return user is not None and user.id == admin_user_id

    def clear_user_state(context: ContextTypes.DEFAULT_TYPE) -> None:
        context.user_data.pop("awaiting_timezone", None)
        context.user_data.pop("awaiting_calendar_url", None)

    def back_keyboard(target: str) -> InlineKeyboardMarkup:
        return InlineKeyboardMarkup(
            [[InlineKeyboardButton("⬅️ Назад", callback_data=f"nav:{target}")]]
        )

    def main_menu_keyboard() -> ReplyKeyboardMarkup:
        return ReplyKeyboardMarkup(
            [[tasks_button, events_button], [admin_button]],
            resize_keyboard=True,
        )

    def admin_menu_keyboard() -> InlineKeyboardMarkup:
        return InlineKeyboardMarkup(
            [
                [InlineKeyboardButton("🕒 Timezone", callback_data="admin:timezone")],
                [InlineKeyboardButton("🗓 Calendars", callback_data="admin:calendars")],
                [InlineKeyboardButton("🌅 Morning test", callback_data="admin:morning_test")],
                [InlineKeyboardButton("📥 Weekly inbox test", callback_data="admin:weekly_inbox_test")],
                [InlineKeyboardButton("⬅️ Назад", callback_data="nav:close")],
            ]
        )

    def calendars_menu_keyboard(calendar_urls: list[str]) -> InlineKeyboardMarkup:
        buttons = [[InlineKeyboardButton("➕ Add calendar", callback_data="admin:calendar:add")]]

        for index, _calendar_url in enumerate(calendar_urls):
            buttons.append(
                [
                    InlineKeyboardButton(
                        f"🗑 Remove {index + 1}",
                        callback_data=f"admin:calendar:remove:{index}",
                    )
                ]
            )

        buttons.append([InlineKeyboardButton("⬅️ Назад", callback_data="nav:admin")])
        return InlineKeyboardMarkup(buttons)

    def summarize_calendar_url(calendar_url: str) -> str:
        parsed_url = urlparse(calendar_url)
        host = parsed_url.netloc or "calendar"
        path = parsed_url.path.rstrip("/") or "/"
        summary = f"{host}{path}"
        if len(summary) > 60:
            return f"{summary[:57]}..."
        return summary

    def get_forward_source_label(update: Update) -> str:
        message = update.effective_message
        if message is None:
            return "Forwarded message"

        origin = getattr(message, "forward_origin", None)
        if origin is not None:
            sender_user = getattr(origin, "sender_user", None)
            if sender_user is not None:
                parts = [p for p in (sender_user.first_name, sender_user.last_name) if p]
                full_name = " ".join(parts).strip()
                if full_name:
                    return full_name
                if sender_user.username:
                    return f"@{sender_user.username}"
                return "Forwarded user"

            sender_user_name = getattr(origin, "sender_user_name", None)
            if sender_user_name:
                return str(sender_user_name)

            sender_chat = getattr(origin, "sender_chat", None)
            if sender_chat is not None and getattr(sender_chat, "title", None):
                return str(sender_chat.title)

            chat = getattr(origin, "chat", None)
            if chat is not None and getattr(chat, "title", None):
                return str(chat.title)

        if getattr(message, "forward_from_chat", None) is not None:
            return str(message.forward_from_chat.title)
        if getattr(message, "forward_sender_name", None):
            return str(message.forward_sender_name)
        if getattr(message, "forward_from", None) is not None:
            user = message.forward_from
            parts = [p for p in (user.first_name, user.last_name) if p]
            full_name = " ".join(parts).strip()
            if full_name:
                return full_name
            if user.username:
                return f"@{user.username}"
        return "Forwarded message"

    def get_forward_text(update: Update) -> str:
        message = update.effective_message
        if message is None:
            return "(no text)"
        body = (message.text or message.caption or "").strip()
        if body:
            return body
        return "(no text)"

    def read_recent_logs(context: ContextTypes.DEFAULT_TYPE, *, line_count: int = 80) -> str:
        log_path_value = context.application.bot_data.get("log_path")
        if not log_path_value:
            return "Log file is not configured."

        log_path = Path(log_path_value)
        if not log_path.exists():
            return "Log file does not exist yet."

        with log_path.open("r", encoding="utf-8") as file:
            lines = file.readlines()

        if not lines:
            return "Log file is empty."

        return "".join(lines[-line_count:]).strip()

    async def send_text_chunks(
        update: Update, text: str, *, chunk_size: int = 3500
    ) -> None:
        message = update.effective_message
        if message is None:
            return

        if not text:
            await message.reply_text("No log output.")
            return

        for start in range(0, len(text), chunk_size):
            chunk = text[start : start + chunk_size]
            await message.reply_text(chunk)

    def schedule_morning_digest() -> None:
        job_queue = application.job_queue
        if job_queue is None:
            return

        for job in job_queue.get_jobs_by_name("morning_digest"):
            job.schedule_removal()

        timezone_name = application.bot_data["timezone"]
        job_queue.run_daily(
            morning_digest_callback,
            time=time(hour=10, minute=0, tzinfo=ZoneInfo(timezone_name)),
            name="morning_digest",
        )

    def schedule_weekly_inbox_reminder() -> None:
        job_queue = application.job_queue
        if job_queue is None:
            return

        for job in job_queue.get_jobs_by_name("weekly_inbox_reminder"):
            job.schedule_removal()

        timezone_name = application.bot_data["timezone"]
        # python-telegram-bot run_daily days: 0=Monday ... 6=Sunday
        job_queue.run_daily(
            weekly_inbox_reminder_callback,
            time=time(hour=20, minute=0, tzinfo=ZoneInfo(timezone_name)),
            days=(6,),
            name="weekly_inbox_reminder",
        )

    def parse_task_date(date_value: str, timezone_name: str) -> date | None:
        if not date_value:
            return None

        if len(date_value) == 10:
            return date.fromisoformat(date_value)

        parsed_datetime = datetime.fromisoformat(date_value.replace("Z", "+00:00"))
        return parsed_datetime.astimezone(ZoneInfo(timezone_name)).date()

    def is_task_for_today_or_overdue(task: dict, timezone_name: str) -> bool:
        today = datetime.now(ZoneInfo(timezone_name)).date()

        for field_name in ("due", "deadline"):
            field = task.get(field_name)
            if not isinstance(field, dict):
                continue

            task_date = parse_task_date(field.get("date"), timezone_name)
            if task_date is not None and task_date <= today:
                return True

        return False

    def format_event_line(event: CalendarEvent, timezone_name: str) -> str:
        timezone = ZoneInfo(timezone_name)
        start_at = event.start_at.astimezone(timezone)
        end_at = event.end_at.astimezone(timezone)
        today = datetime.now(timezone).date()

        if event.all_day:
            return f"• All day - {event.summary}"

        if start_at.date() < today and end_at.date() == today:
            return f"• Started earlier - until {end_at:%H:%M} - {event.summary}"

        if start_at.date() == today and end_at.date() > today:
            return f"• {start_at:%H:%M} - continues tomorrow - {event.summary}"

        return f"• {start_at:%H:%M}-{end_at:%H:%M} - {event.summary}"

    def format_digest_event_line(event: CalendarEvent, timezone_name: str) -> str:
        timezone = ZoneInfo(timezone_name)
        start_at = event.start_at.astimezone(timezone)
        end_at = event.end_at.astimezone(timezone)

        if event.all_day:
            return f"🕐 Весь день - {event.summary} ({event.calendar_name})"

        return (
            f"🕐 {start_at:%H:%M} - {end_at:%H:%M} - "
            f"{event.summary} ({event.calendar_name})"
        )

    def get_tasks_grouped_for_today(timezone_name: str) -> dict[str, list[str]]:
        tasks = todoist_service.get_tasks()
        projects = todoist_service.get_projects()
        tasks = [
            task for task in tasks if is_task_for_today_or_overdue(task, timezone_name)
        ]

        project_names = {
            project["id"]: project["name"] for project in projects if "id" in project
        }
        grouped_tasks: dict[str, list[str]] = defaultdict(list)

        for task in tasks:
            project_name = project_names.get(task.get("project_id"), "No Project")
            grouped_tasks[project_name].append(task.get("content", "Untitled task"))

        return grouped_tasks

    def get_inbox_task_count() -> int:
        tasks = todoist_service.get_tasks()
        projects = todoist_service.get_projects()

        inbox_project_ids: set[str] = set()
        for project in projects:
            if not isinstance(project, dict):
                continue
            project_id = project.get("id")
            if project_id is None:
                continue

            if project.get("is_inbox_project") is True:
                inbox_project_ids.add(str(project_id))
                continue

            project_name = str(project.get("name", "")).strip().lower()
            if project_name in {"inbox", "входящие"}:
                inbox_project_ids.add(str(project_id))

        if not inbox_project_ids:
            return 0

        return sum(1 for task in tasks if str(task.get("project_id")) in inbox_project_ids)

    def get_calendar_events_for_today(
        timezone_name: str,
    ) -> tuple[dict[str, list[CalendarEvent]], list[str]]:
        calendar_urls = settings_service.get_calendar_urls()
        if not calendar_urls:
            return {}, []

        events, errors = ical_service.get_events_for_today(calendar_urls, timezone_name)
        grouped_events: dict[str, list[CalendarEvent]] = defaultdict(list)

        for event in events:
            grouped_events[event.calendar_name].append(event)

        warning_sources = [summarize_calendar_url(error.source) for error in errors]
        return grouped_events, warning_sources

    def build_tasks_message(timezone_name: str) -> str:
        grouped_tasks = get_tasks_grouped_for_today(timezone_name)
        if not grouped_tasks:
            return "📋 No tasks for today or overdue"

        lines = ["📋 Tasks for today and overdue:", ""]

        for project_name, project_tasks in grouped_tasks.items():
            lines.append(f"📁 {project_name}:")
            lines.extend(f"• {task_name}" for task_name in project_tasks)
            lines.append("")

        return "\n".join(lines).rstrip()

    def build_events_message(timezone_name: str) -> str:
        calendar_urls = settings_service.get_calendar_urls()
        if not calendar_urls:
            return "📅 No calendars configured"

        grouped_events, warning_sources = get_calendar_events_for_today(timezone_name)
        if not grouped_events and not warning_sources:
            return "📅 No events for today"

        lines = ["📅 Events for today:", ""]

        for calendar_name, calendar_events in grouped_events.items():
            lines.append(f"🗓 {calendar_name}:")
            lines.extend(
                format_event_line(event, timezone_name) for event in calendar_events
            )
            lines.append("")

        if warning_sources:
            lines.append("Warnings:")
            lines.extend(f"• {source}" for source in warning_sources)

        return "\n".join(lines).rstrip()

    def build_morning_digest_message(timezone_name: str) -> str:
        lines = ["🌅 Доброе утро!", ""]

        try:
            grouped_tasks = get_tasks_grouped_for_today(timezone_name)
        except Exception:
            logger.exception("Failed to fetch Todoist tasks for morning digest")
            grouped_tasks = {}
            lines.extend(
                [
                    "📋 Задачи на сегодня:",
                    "",
                    "Не удалось загрузить задачи.",
                    "",
                ]
            )
        else:
            lines.extend(["📋 Задачи на сегодня:", ""])
            if grouped_tasks:
                for project_name, project_tasks in grouped_tasks.items():
                    lines.append(f"📁 {project_name}:")
                    lines.extend(f"• {task_name}" for task_name in project_tasks)
                    lines.append("")
            else:
                lines.extend(["Нет задач на сегодня.", ""])

        try:
            grouped_events, warning_sources = get_calendar_events_for_today(timezone_name)
        except Exception:
            logger.exception("Failed to fetch calendar events for morning digest")
            grouped_events = {}
            warning_sources = []
            lines.extend(["📅 События календаря:", "", "Не удалось загрузить события."])
        else:
            lines.extend(["📅 События календаря:", ""])
            if grouped_events:
                for calendar_events in grouped_events.values():
                    lines.extend(
                        format_digest_event_line(event, timezone_name)
                        for event in calendar_events
                    )
            else:
                lines.append("Нет событий на сегодня.")

            if warning_sources:
                lines.append("")
                lines.append("Warnings:")
                lines.extend(f"• {source}" for source in warning_sources)

        return "\n".join(lines).rstrip()

    async def morning_digest_callback(context: ContextTypes.DEFAULT_TYPE) -> None:
        timezone_name = context.application.bot_data["timezone"]
        message = build_morning_digest_message(timezone_name)
        await context.bot.send_message(chat_id=admin_user_id, text=message)

    async def weekly_inbox_reminder_callback(context: ContextTypes.DEFAULT_TYPE) -> None:
        try:
            inbox_count = get_inbox_task_count()
        except Exception:
            logger.exception("Failed to build weekly inbox reminder")
            await context.bot.send_message(
                chat_id=admin_user_id,
                text="🔔 Weekly reminder: не удалось получить количество задач во входящих.",
            )
            return

        await context.bot.send_message(
            chat_id=admin_user_id,
            text=(
                "🔔 Weekly reminder\n"
                "Разбери входящие в Todoist.\n"
                f"Сейчас во входящих: {inbox_count} задач(и)."
            ),
        )

    async def send_weekly_inbox_reminder_to_chat(
        context: ContextTypes.DEFAULT_TYPE, chat_id: int
    ) -> None:
        inbox_count = get_inbox_task_count()
        await context.bot.send_message(
            chat_id=chat_id,
            text=(
                "🔔 Weekly reminder\n"
                "Разбери входящие в Todoist.\n"
                f"Сейчас во входящих: {inbox_count} задач(и)."
            ),
        )

    async def send_morning_digest_to_chat(
        context: ContextTypes.DEFAULT_TYPE, chat_id: int
    ) -> None:
        timezone_name = context.application.bot_data["timezone"]
        message = build_morning_digest_message(timezone_name)
        await context.bot.send_message(chat_id=chat_id, text=message)

    async def show_admin_menu(
        update: Update, context: ContextTypes.DEFAULT_TYPE, *, as_edit: bool
    ) -> None:
        clear_user_state(context)
        text = "Admin settings:"

        if as_edit and update.callback_query is not None:
            await update.callback_query.edit_message_text(
                text=text,
                reply_markup=admin_menu_keyboard(),
            )
            return

        await update.effective_message.reply_text(
            text=text,
            reply_markup=admin_menu_keyboard(),
        )

    async def show_timezone_menu(
        update: Update, context: ContextTypes.DEFAULT_TYPE, *, as_edit: bool
    ) -> None:
        clear_user_state(context)
        context.user_data["awaiting_timezone"] = True
        current_timezone = context.application.bot_data["timezone"]
        text = (
            "Timezone settings\n\n"
            f"Current timezone: {current_timezone}\n"
            "Send a new timezone, for example: Europe/Berlin"
        )

        if as_edit and update.callback_query is not None:
            await update.callback_query.edit_message_text(
                text=text,
                reply_markup=back_keyboard("admin"),
            )
            return

        await update.effective_message.reply_text(
            text=text,
            reply_markup=back_keyboard("admin"),
        )

    async def show_calendars_menu(
        update: Update, context: ContextTypes.DEFAULT_TYPE, *, as_edit: bool
    ) -> None:
        clear_user_state(context)
        calendar_urls = settings_service.get_calendar_urls()

        if calendar_urls:
            lines = ["Calendar sources:", ""]
            lines.extend(
                f"{index + 1}. {summarize_calendar_url(calendar_url)}"
                for index, calendar_url in enumerate(calendar_urls)
            )
            text = "\n".join(lines)
        else:
            text = "Calendar sources:\n\nNo calendars configured yet."

        reply_markup = calendars_menu_keyboard(calendar_urls)

        if as_edit and update.callback_query is not None:
            await update.callback_query.edit_message_text(
                text=text,
                reply_markup=reply_markup,
            )
            return

        await update.effective_message.reply_text(
            text=text,
            reply_markup=reply_markup,
        )

    async def show_add_calendar_menu(
        update: Update, context: ContextTypes.DEFAULT_TYPE, *, as_edit: bool
    ) -> None:
        clear_user_state(context)
        context.user_data["awaiting_calendar_url"] = True
        text = "Send an ICS URL for the calendar you want to add. Supports https:// and webcal:// links."

        if as_edit and update.callback_query is not None:
            await update.callback_query.edit_message_text(
                text=text,
                reply_markup=back_keyboard("admin_calendars"),
            )
            return

        await update.effective_message.reply_text(
            text=text,
            reply_markup=back_keyboard("admin_calendars"),
        )

    async def tasks_command(
        update: Update, context: ContextTypes.DEFAULT_TYPE
    ) -> None:
        if not is_admin(update):
            await update.message.reply_text("❌ Access denied")
            return

        timezone_name = context.application.bot_data["timezone"]

        try:
            message = build_tasks_message(timezone_name)
        except Exception:
            logger.exception("Failed to build tasks message")
            await update.message.reply_text("Failed to fetch Todoist data")
            return

        await update.message.reply_text(message)

    async def events_command(
        update: Update, context: ContextTypes.DEFAULT_TYPE
    ) -> None:
        if not is_admin(update):
            await update.message.reply_text("❌ Access denied")
            return

        timezone_name = context.application.bot_data["timezone"]

        try:
            message = build_events_message(timezone_name)
        except Exception:
            logger.exception("Failed to build events message")
            await update.message.reply_text("Failed to fetch calendar events")
            return

        await update.message.reply_text(message)

    async def start_command(
        update: Update, context: ContextTypes.DEFAULT_TYPE
    ) -> None:
        if not is_admin(update):
            await update.message.reply_text("❌ Access denied")
            return

        await update.message.reply_text(
            "Main menu:",
            reply_markup=main_menu_keyboard(),
        )

    async def morning_test_command(
        update: Update, context: ContextTypes.DEFAULT_TYPE
    ) -> None:
        if not is_admin(update):
            await update.message.reply_text("❌ Access denied")
            return

        try:
            await send_morning_digest_to_chat(context, update.effective_chat.id)
        except Exception:
            logger.exception("Failed to send morning test digest")
            await update.message.reply_text("Failed to send morning digest")
            return

    async def weekly_inbox_test_command(
        update: Update, context: ContextTypes.DEFAULT_TYPE
    ) -> None:
        if not is_admin(update):
            await update.message.reply_text("❌ Access denied")
            return

        try:
            await send_weekly_inbox_reminder_to_chat(context, update.effective_chat.id)
        except Exception:
            logger.exception("Failed to send weekly inbox test reminder")
            await update.message.reply_text("Failed to send weekly inbox reminder")
            return

    async def logs_command(
        update: Update, context: ContextTypes.DEFAULT_TYPE
    ) -> None:
        if not is_admin(update):
            await update.message.reply_text("❌ Access denied")
            return

        try:
            logs_text = read_recent_logs(context)
        except Exception:
            logger.exception("Failed to read bot logs")
            await update.message.reply_text("Failed to read logs")
            return

        await send_text_chunks(update, logs_text)

    async def forwarded_message_command(
        update: Update, context: ContextTypes.DEFAULT_TYPE
    ) -> None:
        if not is_admin(update):
            await update.message.reply_text("❌ Access denied")
            return

        source_label = get_forward_source_label(update)
        message_text = get_forward_text(update)
        task_title = f"Forwarded from: {source_label}"

        try:
            todoist_service.create_task(content=task_title, description=message_text)
        except Exception:
            logger.exception("Failed to create task from forwarded message")
            await update.message.reply_text("Failed to save forwarded message to Todoist")
            return

        await update.message.reply_text("Saved to Todoist Inbox")

    async def admin_command(
        update: Update, context: ContextTypes.DEFAULT_TYPE
    ) -> None:
        if not is_admin(update):
            await update.message.reply_text("❌ Access denied")
            return

        await show_admin_menu(update, context, as_edit=False)

    async def admin_callback(
        update: Update, context: ContextTypes.DEFAULT_TYPE
    ) -> None:
        query = update.callback_query

        if query is None:
            return

        if not is_admin(update):
            await query.answer("Access denied", show_alert=True)
            return

        await query.answer()

        if query.data == "admin:timezone":
            await show_timezone_menu(update, context, as_edit=True)
            return

        if query.data == "admin:calendars":
            await show_calendars_menu(update, context, as_edit=True)
            return

        if query.data == "admin:morning_test":
            try:
                await send_morning_digest_to_chat(context, update.effective_chat.id)
            except Exception:
                logger.exception("Failed to send morning digest from admin menu")
                await query.answer("Failed to send morning digest", show_alert=True)
                return
            return

        if query.data == "admin:weekly_inbox_test":
            try:
                await send_weekly_inbox_reminder_to_chat(context, update.effective_chat.id)
            except Exception:
                logger.exception("Failed to send weekly inbox reminder from admin menu")
                await query.answer("Failed to send weekly inbox reminder", show_alert=True)
                return
            return

        if query.data == "admin:calendar:add":
            await show_add_calendar_menu(update, context, as_edit=True)
            return

        if query.data and query.data.startswith("admin:calendar:remove:"):
            _, _, _, index_text = query.data.split(":")
            try:
                settings_service.remove_calendar_url(int(index_text))
            except ValueError:
                await query.answer("Calendar not found", show_alert=True)
                return

            await show_calendars_menu(update, context, as_edit=True)
            return

        if query.data == "nav:admin":
            await show_admin_menu(update, context, as_edit=True)
            return

        if query.data == "nav:admin_calendars":
            await show_calendars_menu(update, context, as_edit=True)
            return

        if query.data == "nav:close":
            clear_user_state(context)
            await query.edit_message_text("Closed.")
            return

    async def settings_input(
        update: Update, context: ContextTypes.DEFAULT_TYPE
    ) -> None:
        if not is_admin(update):
            return

        message_text = (update.message.text or "").strip()

        if context.user_data.get("awaiting_timezone"):
            try:
                settings_service.set_timezone(message_text)
            except ValueError:
                await update.message.reply_text(
                    "Invalid timezone. Send a valid timezone, for example: Europe/Berlin",
                    reply_markup=back_keyboard("admin"),
                )
                return

            clear_user_state(context)
            context.application.bot_data["timezone"] = message_text
            schedule_morning_digest()
            schedule_weekly_inbox_reminder()
            await update.message.reply_text(f"Timezone updated: {message_text}")
            await show_admin_menu(update, context, as_edit=False)
            return

        if context.user_data.get("awaiting_calendar_url"):
            try:
                settings_service.add_calendar_url(message_text)
            except ValueError:
                await update.message.reply_text(
                    "Invalid ICS URL. Send a valid https:// or webcal:// URL.",
                    reply_markup=back_keyboard("admin_calendars"),
                )
                return

            clear_user_state(context)
            await update.message.reply_text("Calendar added")
            await show_calendars_menu(update, context, as_edit=False)
            return

        if message_text == tasks_button:
            await tasks_command(update, context)
            return

        if message_text == events_button:
            await events_command(update, context)
            return

        if message_text == admin_button:
            await admin_command(update, context)
            return

    async def error_handler(
        update: object, context: ContextTypes.DEFAULT_TYPE
    ) -> None:
        logger.exception("Unhandled Telegram error", exc_info=context.error)

    application.add_handler(CommandHandler("start", start_command))
    application.add_handler(CommandHandler("admin", admin_command))
    application.add_handler(CommandHandler("events", events_command))
    application.add_handler(CommandHandler("logs", logs_command))
    application.add_handler(CommandHandler("morning_test", morning_test_command))
    application.add_handler(CommandHandler("weekly_inbox_test", weekly_inbox_test_command))
    application.add_handler(CommandHandler("tasks", tasks_command))
    application.add_handler(CallbackQueryHandler(admin_callback, pattern="^(admin:|nav:)"))
    application.add_handler(MessageHandler(filters.FORWARDED, forwarded_message_command))
    application.add_handler(
        MessageHandler(filters.TEXT & ~filters.COMMAND, settings_input)
    )
    application.add_error_handler(error_handler)
    schedule_morning_digest()
    schedule_weekly_inbox_reminder()
    return application
