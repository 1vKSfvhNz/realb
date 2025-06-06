from contextlib import asynccontextmanager
from fastapi import FastAPI
from apscheduler.schedulers.background import BackgroundScheduler

from models import (
    insert_icon_types,
    insert_devise,
    insert_locality,
    schedule_banner_expirations,
    get_db_context
)
from ml_engine import predictor  # Prédicteur avec planification auto

# Initialise le scheduler global
scheduler = BackgroundScheduler()

@asynccontextmanager
async def lifespan(app: FastAPI):
    with get_db_context() as db:  # utilise correctement le context manager sync
        try:
            # Insertions initiales
            insert_icon_types(db)
            insert_devise(db)
            insert_locality(db)

            # Planification des bannières expirées
            schedule_banner_expirations(scheduler, db)
            scheduler.start()

            # Démarrage du scheduler ML à 10h00
            predictor.start_scheduler(training_time="10:00")

            yield  # Exécution normale de l'app

        finally:
            # Arrêt propre des schedulers
            predictor.stop_scheduler()
            scheduler.shutdown()
