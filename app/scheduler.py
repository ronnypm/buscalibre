"""Scheduler (APScheduler) que corre los escaneos periódicos dentro del proceso."""
from apscheduler.schedulers.background import BackgroundScheduler

from . import config, db as dbmod, notify
from .scanner import scan_all

_scheduler: BackgroundScheduler | None = None


def start() -> None:
    global _scheduler
    if _scheduler is not None:
        return
    _scheduler = BackgroundScheduler(timezone="UTC")
    _scheduler.add_job(
        _tick,
        "interval",
        minutes=config.SCAN_INTERVAL_MINUTES,
        id="scan_prices",
        max_instances=1,
        coalesce=True,
    )
    _scheduler.start()


def _tick() -> None:
    with dbmod.SessionLocal() as db:
        resumen, alertas = scan_all(db)
    enviadas = notify.notificar(alertas)
    print(f"[scan] {resumen} | telegram enviadas={enviadas}", flush=True)


def shutdown() -> None:
    global _scheduler
    if _scheduler is not None:
        _scheduler.shutdown(wait=False)
        _scheduler = None