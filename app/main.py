"""Punto de entrada FastAPI. Arranca la BD y el scheduler de escaneos."""
from contextlib import asynccontextmanager

from fastapi import FastAPI

from . import bot as botmod, config, db as dbmod, scheduler
from .routers import products


@asynccontextmanager
async def lifespan(app: FastAPI):
    dbmod.init_db()
    if config.ENABLE_SCANNER:
        scheduler.start()
    # Poller del bot: responde a mensajes entrantes
    botmod.start()
    print(
        f"[app] scanner={'ON' if config.ENABLE_SCANNER else 'OFF'} "
        f"intervalo={config.SCAN_INTERVAL_MINUTES}min "
        f"telegram={'OK' if config.telegram_configured() else 'desactivado'}",
        flush=True,
    )
    yield
    scheduler.shutdown()


app = FastAPI(
    title="Price Tracker Buscalibre",
    description="Backend que trackea precios y notifica por Telegram subidas, bajadas "
    "y cuando un producto vuelve a su mejor precio histórico.",
    version="0.1.0",
    lifespan=lifespan,
)
app.include_router(products.router)


@app.get("/")
def indice():
    return {
        "app": "Price Tracker Buscalibre",
        "docs": "/docs",
        "health": "/health",
        "endpoints": {
            "listar_productos": "GET /products",
            "crear_producto": "POST /products",
            "historial": "GET /products/{id}/history",
            "escanear_uno": "POST /products/{id}/scan",
            "escanear_todo": "POST /scan",
            "importar_wishlist": "POST /import/wishlist",
            "consultar_ia": "POST /ai/ask",
        },
    }


@app.get("/health")
def health():
    return {"status": "ok", "scanner": config.ENABLE_SCANNER,
            "interval_min": config.SCAN_INTERVAL_MINUTES}