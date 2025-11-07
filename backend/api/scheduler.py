# myapp/scheduler_job.py

import threading
import logging
from apscheduler.schedulers.background import BackgroundScheduler
from django_apscheduler.jobstores import DjangoJobStore
from datetime import datetime

# -------------------------------------
# ✅ Optional: Enable file logging
# -------------------------------------
logging.basicConfig(
    filename='scheduler.log',  # Log file path
    level=logging.INFO,
    format='[%(asctime)s] %(levelname)s: %(message)s',
)

# -------------------------------------
# 🔒 Lock and startup flag to avoid re-init
# -------------------------------------
scheduler_lock = threading.Lock()
scheduler_started = False

# -------------------------------------
# 🧠 Warm-up function: Calls your DB search
# -------------------------------------
def warmup_job():
    from .postgres_views import processor  # Adjust to match your app

    start_time = datetime.now()
    print(f"[{start_time}] 🔁 Starting warm-up job...")
    logging.info("🔁 Starting warm-up job...")

    try:
        # Perform the search query
        result = processor.search(
            query="warmup",
            collection_name="chatbot_dgis",
            top_k=1,
            min_score=0.33
        )

        end_time = datetime.now()
        print(f"[{end_time}] ✅ Warm-up completed successfully.")
        print(f"[{end_time}] 🗃️ DB Response: {result}")

        logging.info("✅ Warm-up completed successfully.")
        logging.info(f"🗃️ DB Response: {result}")

    except Exception as e:
        error_time = datetime.now()
        print(f"[{error_time}] ❌ Warm-up failed: {e}")
        logging.error(f"❌ Warm-up failed: {e}")

# -------------------------------------
# 🕒 Start scheduler if not already running
# -------------------------------------
def start():
    global scheduler_started
    with scheduler_lock:
        if not scheduler_started:
            print("🚀 Initializing APScheduler...")
            logging.info("🚀 Initializing APScheduler...")

            scheduler = BackgroundScheduler()
            scheduler.add_jobstore(DjangoJobStore(), "default")

            existing_job = scheduler.get_job("warmup_job")
            if existing_job is None:
                scheduler.add_job(
                    warmup_job,
                    trigger="interval",
                    minutes=4,  # ⏱️ run every 4 minutes
                    id="warmup_job",
                    replace_existing=True,
                )
                print("✅ Warm-up job added to scheduler.")
                logging.info("✅ Warm-up job added to scheduler.")
            else:
                print("ℹ️ Warm-up job already exists.")
                logging.info("ℹ️ Warm-up job already exists.")

            scheduler.start()
            scheduler_started = True
            print("✅ Scheduler started once.")
            logging.info("✅ Scheduler started once.")
        else:
            print("⚠️ Scheduler already started. Skipping.")
            logging.warning("⚠️ Scheduler already started. Skipping.")
