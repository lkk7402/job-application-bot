"""APScheduler jobs — daily search and digest email."""

from apscheduler.schedulers.background import BackgroundScheduler


def create_scheduler(run_search_fn, send_digest_fn) -> BackgroundScheduler:
    scheduler = BackgroundScheduler()

    # Daily at 8am: search + score new jobs
    scheduler.add_job(run_search_fn, "cron", hour=8, minute=0, id="daily_search")

    # Daily at 8pm: send digest email
    scheduler.add_job(send_digest_fn, "cron", hour=20, minute=0, id="daily_digest")

    return scheduler
