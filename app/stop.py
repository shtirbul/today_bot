import os
import signal
import sys
import time

try:
    from app.main import get_lock_path
except ImportError:
    from main import get_lock_path


def is_process_running(pid: int) -> bool:
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True

    return True


def main() -> None:
    lock_path = get_lock_path()

    if not lock_path.exists():
        print("Bot is not running")
        return

    pid_raw = lock_path.read_text(encoding="utf-8").strip()
    if not pid_raw.isdigit():
        lock_path.unlink()
        print("Removed invalid bot lock")
        return

    pid = int(pid_raw)

    if not is_process_running(pid):
        lock_path.unlink()
        print("Removed stale bot lock")
        return

    os.kill(pid, signal.SIGTERM)

    for _ in range(50):
        if not is_process_running(pid):
            if lock_path.exists():
                lock_path.unlink()
            print(f"Stopped bot process {pid}")
            return
        time.sleep(0.1)

    print(f"Bot process {pid} did not stop in time")
    sys.exit(1)


if __name__ == "__main__":
    main()
