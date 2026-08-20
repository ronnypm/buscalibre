"""Motor, sesión y base declarativa de SQLAlchemy."""
from sqlalchemy import create_engine
from sqlalchemy.orm import DeclarativeBase, sessionmaker

from . import config

# Para SQLite permitir uso de hilos (uvicorn). Para Postgres es inocuo.
engine = create_engine(config.DATABASE_URL, connect_args={"check_same_thread": False})

SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)


class Base(DeclarativeBase):
    pass


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def init_db():
    from . import models  # noqa: F401  (registra los modelos en Base.metadata)

    Base.metadata.create_all(bind=engine)
    _migrar(engine)


def _migrar(engine) -> None:
    """Migraciones manuales para tablas SQLite ya creadas (create_all no altera)."""
    from sqlalchemy import inspect, text

    insp = inspect(engine)
    cols = {c["name"] for c in insp.get_columns("products")}
    if "lista" not in cols:
        with engine.begin() as conn:
            conn.execute(text("ALTER TABLE products ADD COLUMN lista VARCHAR(128)"))