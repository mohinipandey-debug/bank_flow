import time
import os
from watchdog.observers import Observer
from watchdog.events import FileSystemEventHandler
from processor import process_file
from database import init_db

STATEMENTS_DIR = "statements"
WATCH_EXTENSIONS = {".xlsx", ".xls", ".pdf"}

SKIP_PREFIXES   = ("~$", ".", "_")
SKIP_EXTENSIONS = {".tmp", ".part", ".crdownload", ".lock", ".~lock"}


def is_valid_statement_file(filepath):
    """Ignore temp, lock, and in-progress download files."""
    basename = os.path.basename(filepath)
    ext = os.path.splitext(basename)[1].lower()
    if any(basename.startswith(p) for p in SKIP_PREFIXES):
        return False
    if ext in SKIP_EXTENSIONS:
        return False
    if ext not in WATCH_EXTENSIONS:
        return False
    return True


def wait_for_file_ready(filepath, timeout=30):
    """Poll until file size stabilises — handles slow copies and downloads."""
    prev_size = -1
    stable_count = 0
    deadline = time.time() + timeout

    while time.time() < deadline:
        try:
            curr_size = os.path.getsize(filepath)
        except OSError:
            time.sleep(0.5)
            continue

        if curr_size == prev_size and curr_size > 0:
            stable_count += 1
            if stable_count >= 3:   # stable for 1.5 s
                return True
        else:
            stable_count = 0
        prev_size = curr_size
        time.sleep(0.5)

    print(f"[WATCHER] Timeout waiting for file to stabilise: {filepath}")
    return False


class StatementHandler(FileSystemEventHandler):
    def on_created(self, event):
        if event.is_directory:
            return
        filepath = event.src_path

        if not is_valid_statement_file(filepath):
            return

        print(f"\n[WATCHER] New file detected: {filepath}")

        if not wait_for_file_ready(filepath):
            print(f"[WATCHER] Skipping unstable file: {filepath}")
            return

        try:
            process_file(filepath)
        except Exception as e:
            print(f"[ERROR] Failed to process {filepath}: {e}")
            import traceback; traceback.print_exc()


def start_watcher():
    init_db()
    os.makedirs(STATEMENTS_DIR, exist_ok=True)

    event_handler = StatementHandler()
    observer = Observer()
    observer.schedule(event_handler, STATEMENTS_DIR, recursive=True)
    observer.start()

    print(f"[WATCHER] Watching: {os.path.abspath(STATEMENTS_DIR)}")
    print(f"[WATCHER] Drop bank statements into the correct subfolders.")
    print(f"[WATCHER] Temp/lock files are ignored automatically.")
    print(f"[WATCHER] Press Ctrl+C to stop.\n")

    try:
        while True:
            time.sleep(5)
    except KeyboardInterrupt:
        observer.stop()
    observer.join()


if __name__ == "__main__":
    start_watcher()
