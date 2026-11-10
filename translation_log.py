"""Private per-request logs with five-minute retention while the service runs."""
import json
import os
import threading
import time
import uuid
from pathlib import Path

LOG_DIR = Path(__file__).resolve().parent / '.runtime' / 'translation-logs'
RETENTION_SECONDS = 300
CLEANUP_INTERVAL_SECONDS = 60


def cleanup(now=None):
    now = time.time() if now is None else now
    try:
        for path in LOG_DIR.iterdir():
            if path.suffix not in ('.json', '.tmp') or path.is_symlink():
                continue
            try:
                # Filenames contain the request start time, including temporary files.
                started = float(path.name.split('_', 1)[0])
                if now - started >= RETENTION_SECONDS:
                    path.unlink(missing_ok=True)
            except (OSError, ValueError):
                continue
    except OSError:
        pass


def write(record):
    temporary = None
    try:
        LOG_DIR.mkdir(parents=True, exist_ok=True, mode=0o700)
        LOG_DIR.chmod(0o700)
        name = f"{record['started_at']:.6f}_{record['request_id']}"
        temporary = LOG_DIR / (name + '.tmp')
        fd = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(fd, 'w', encoding='utf-8') as stream:
            json.dump(record, stream, ensure_ascii=False)
            stream.write('\n')
        os.replace(temporary, LOG_DIR / (name + '.json'))
    except Exception:
        # Observability must never change translation behavior.
        pass
    finally:
        if temporary is not None:
            try:
                temporary.unlink(missing_ok=True)
            except OSError:
                pass


def logged_translation(kind, text, config, operation):
    started = time.time()
    clock = time.monotonic()
    record = dict(request_id=uuid.uuid4().hex, kind=kind, started_at=started,
                  provider=config.get('api_provider'), model=config.get('model'),
                  original=text, status='started')
    write(record)
    try:
        result = operation()
        record.update(status='success', translated=result)
        return result
    except Exception as error:
        record.update(status='error', error_type=type(error).__name__)
        code = getattr(error, 'status_code', getattr(error, 'code', None))
        if isinstance(code, int):
            record['http_status'] = code
        raise
    finally:
        record.update(finished_at=time.time(),
                      duration_ms=round((time.monotonic() - clock) * 1000, 3))
        # Do not recreate a record already expired during a long request.
        if time.time() - started < RETENTION_SECONDS:
            write(record)
        cleanup()


def start(stopped):
    cleanup()

    def monitor():
        while not stopped.wait(CLEANUP_INTERVAL_SECONDS):
            cleanup()

    thread = threading.Thread(target=monitor, name='translation-log-cleanup', daemon=True)
    thread.start()
    return thread
