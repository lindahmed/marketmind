"""Independent Railway worker. No business API and no public domain."""
import json
import logging
import os
import signal
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from sqlalchemy import text

from app.config import get_settings
from app.db import SessionLocal, engine
from app.deployment import check_database, configure_logging
from app.workflow_jobs import _worker_loop

logger = logging.getLogger("marketmind.worker")


def main() -> None:
    configure_logging()
    settings = get_settings()
    try:
        if settings.environment == "production" and settings.service_role != "worker":
            raise RuntimeError("Worker service requires SERVICE_ROLE=worker")
        check_database(engine, "worker", production=settings.environment == "production")
    except Exception as error:
        logger.error("worker_startup_failed error_type=%s; check migrations and restricted worker credentials",
                     type(error).__name__)
        raise SystemExit(1) from None

    stop = threading.Event()
    thread = threading.Thread(target=_worker_loop, args=(stop, SessionLocal), name="marketmind-worker")

    class HealthHandler(BaseHTTPRequestHandler):
        def do_GET(self):
            status = 200
            if self.path != "/health":
                status = 404
            elif not thread.is_alive() or stop.is_set():
                status = 503
            else:
                try:
                    with engine.connect() as connection:
                        connection.execute(text("SELECT 1"))
                except Exception:
                    status = 503
            self.send_response(status)
            self.send_header("Content-Type", "application/json")
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(json.dumps({"status": "ok" if status == 200 else "unavailable"}).encode())

        def log_message(self, *_):
            pass

    server = ThreadingHTTPServer(("0.0.0.0", int(os.environ.get("PORT", "8000"))), HealthHandler)
    server.daemon_threads = True

    def shutdown(signum, frame):
        logger.info("worker_shutdown_requested signal=%s", signum)
        stop.set()

    signal.signal(signal.SIGTERM, shutdown)
    signal.signal(signal.SIGINT, shutdown)
    thread.start()
    logger.info("worker_started poll_seconds=%s lease_seconds=%s", settings.worker_poll_seconds,
                settings.worker_lease_seconds)
    server.timeout = 0.5
    try:
        while thread.is_alive() and not stop.is_set():
            server.handle_request()
    finally:
        stop.set()
        server.server_close()
        # Finish the current job where possible. A forced platform termination
        # leaves an expiring lease; uncertain provider calls are not replayed.
        thread.join()
        engine.dispose()
        logger.info("worker_stopped")


if __name__ == "__main__":
    main()
