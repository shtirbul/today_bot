import atexit
import fcntl
import logging
import os
import sys
from logging.handlers import RotatingFileHandler
from pathlib import Path

from dotenv import load_dotenv

try:
    from app.bot import create_application
    from app.services.ical import IcalService
    from app.services.settings import SettingsService
    from app.services.todoist import TodoistService
except ImportError:
    from bot import create_application
    from services.ical import IcalService
    from services.settings import SettingsService
    from services.todoist import TodoistService


LOCK_FILE_HANDLE = None


def get_log_path() -> Path:
    return Path(__file__).resolve().parent / "data" / "bot.log"


def setup_logging(log_path: Path) -> None:
    log_path.parent.mkdir(parents=True, exist_ok=True)

    formatter = logging.Formatter(
        "%(asctime)s %(levelname)s [%(name)s] %(message)s"
    )
    file_handler = RotatingFileHandler(
        log_path,
        maxBytes=1_000_000,
        backupCount=3,
        encoding="utf-8",
    )
    file_handler.setFormatter(formatter)

    stream_handler = logging.StreamHandler()
    stream_handler.setFormatter(formatter)

    root_logger = logging.getLogger()
    root_logger.setLevel(logging.INFO)
    root_logger.handlers.clear()
    root_logger.addHandler(file_handler)
    root_logger.addHandler(stream_handler)


def get_lock_path() -> Path:
    return Path(__file__).resolve().parent / "data" / "bot.lock"


def acquire_single_instance_lock(lock_path: Path) -> None:
    global LOCK_FILE_HANDLE

    lock_path.parent.mkdir(parents=True, exist_ok=True)
    LOCK_FILE_HANDLE = lock_path.open("w", encoding="utf-8")

    try:
        fcntl.flock(LOCK_FILE_HANDLE.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BlockingIOError as error:
        raise RuntimeError("Bot is already running") from error

    LOCK_FILE_HANDLE.seek(0)
    LOCK_FILE_HANDLE.truncate()
    LOCK_FILE_HANDLE.write(str(os.getpid()))
    LOCK_FILE_HANDLE.flush()
    atexit.register(release_single_instance_lock, lock_path)


def release_single_instance_lock(lock_path: Path) -> None:
    global LOCK_FILE_HANDLE

    if LOCK_FILE_HANDLE is None:
        return

    try:
        fcntl.flock(LOCK_FILE_HANDLE.fileno(), fcntl.LOCK_UN)
    finally:
        LOCK_FILE_HANDLE.close()
        LOCK_FILE_HANDLE = None
        if lock_path.exists():
            lock_path.unlink()


def is_process_running(pid: int) -> bool:
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True

    return True


def main() -> None:
    load_dotenv()
    log_path = get_log_path()
    setup_logging(log_path)
    logger = logging.getLogger(__name__)

    bot_token = os.getenv("TELEGRAM_BOT_TOKEN")
    todoist_api_token = os.getenv("TODOIST_API_TOKEN")
    admin_user_id = os.getenv("ADMIN_USER_ID")

    if not bot_token:
        raise ValueError("TELEGRAM_BOT_TOKEN is not set")
    if not todoist_api_token:
        raise ValueError("TODOIST_API_TOKEN is not set")
    if not admin_user_id:
        raise ValueError("ADMIN_USER_ID is not set")

    settings_service = SettingsService(
        Path(__file__).resolve().parent / "data" / "settings.json"
    )
    lock_path = get_lock_path()

    if lock_path.exists():
        lock_pid_raw = lock_path.read_text(encoding="utf-8").strip()
        if lock_pid_raw.isdigit() and not is_process_running(int(lock_pid_raw)):
            lock_path.unlink()

    try:
        acquire_single_instance_lock(lock_path)
    except RuntimeError as error:
        logger.error(str(error))
        print(str(error))
        sys.exit(1)

    todoist_service = TodoistService(todoist_api_token)
    ical_service = IcalService()
    application = create_application(
        bot_token=bot_token,
        ical_service=ical_service,
        todoist_service=todoist_service,
        settings_service=settings_service,
        admin_user_id=int(admin_user_id),
    )
    application.bot_data["log_path"] = str(log_path)
    logger.info("Bot startup complete")
    application.run_polling()


if __name__ == "__main__":
    main()
