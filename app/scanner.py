"""Scanner: lee el precio actual, guarda el historial y emite alertas.

Reglas:
- Cualquier CAMBIO de precio notifica (subió / bajó).
- "EXCELENTE" cuando el precio rompe el mínimo histórico o vuelve a él.
- Cambios de stock: avisa agotado y restock.
- Si el precio NO cambia: no se manda nada ni se guarda punto de historial.
- Las alertas de precio usan la IA de Kilo (si hay key) para redactar el mensaje
  con recomendación; si no, caen en plantillas.
"""
from datetime import datetime
import time

from sqlalchemy import select
from sqlalchemy.orm import Session

from . import ai, crawler, notify
from .models import PricePoint, Product


def _alerta(kind: str, producto, mensaje):
    return {"product_id": producto.id, "title": producto.title,
            "message": mensaje, "kind": kind}


def _scan_producto(db: Session, producto: Product) -> tuple[bool, dict | None]:
    """Devuelve (ok, alerta|None). ok=False = no se pudo leer la página (error de red)."""
    precio = titulo = autor = None
    ok_leer = False
    for intento in range(2):
        try:
            precio, titulo, autor = crawler.get_current_price(producto.url)
        except Exception:
            time.sleep(1 + intento)  # backoff ante rate-limit/red
            continue
        # Precio None puede ser rate-limit; reintenta una vez antes de declarar agotado.
        if precio is None and intento == 0:
            time.sleep(1 + intento)
            continue
        ok_leer = True
        break

    if not ok_leer:
        return False, None  # no se pudo leer la página; se reintenta en el próximo ciclo

    producto.title = titulo or producto.title
    producto.author = autor or producto.author
    now = datetime.utcnow()
    EPS = 1e-6

    # Sin precio en la página == sin stock (la página cargó bien).
    if precio is None:
        alerta = None
        if producto.in_stock:
            producto.in_stock = False
            alerta = _alerta("nostock", producto, notify.alerta_sin_stock(producto))
        return True, alerta

    prev = producto.current_price

    # Primer escaneo: fijamos línea de base, no alertamos.
    if producto.min_price is None:
        producto.initial_price = precio
        producto.min_price = precio
        producto.min_price_at = now
        producto.current_price = precio
        producto.last_scanned_at = now
        producto.in_stock = True
        db.add(PricePoint(product_id=producto.id, price=precio, scanned_at=now))
        return True, None

    # Sin cambio de precio: no se toca la BD ni se avisa.
    if prev is not None and abs(precio - prev) <= EPS:
        producto.last_scanned_at = now
        return True, None

    # Hubo cambio -> registro el punto en el historial.
    producto.current_price = precio
    producto.last_scanned_at = now
    db.add(PricePoint(product_id=producto.id, price=precio, scanned_at=now))

    vuelve_stock = not producto.in_stock
    producto.in_stock = True

    es_nuevo_min = precio < producto.min_price - EPS
    es_igual_min = abs(precio - producto.min_price) <= EPS

    if es_nuevo_min:
        producto.min_price = precio
        producto.min_price_at = now
        if vuelve_stock:
            mensaje = notify.alerta_volvio_stock(producto)
            return True, _alerta("restock", producto, mensaje)
        mensaje = ai.smart_alert(producto, "low", prev) or notify.alerta_nuevo_minimo(producto)
        return True, _alerta("low", producto, mensaje)

    if es_igual_min and prev is not None and prev > producto.min_price + EPS:
        mensaje = ai.smart_alert(producto, "low", prev) or notify.alerta_vuelve_minimo(producto)
        return True, _alerta("low", producto, mensaje)

    if vuelve_stock:
        return True, _alerta("restock", producto, notify.alerta_volvio_stock(producto))

    if precio < prev - EPS:
        mensaje = ai.smart_alert(producto, "down", prev) or notify.alerta_bajada(producto)
        return True, _alerta("down", producto, mensaje)

    if precio > prev + EPS:
        mensaje = ai.smart_alert(producto, "up", prev) or notify.alerta_subida(producto)
        return True, _alerta("up", producto, mensaje)

    return True, None


def scan_all(db: Session) -> tuple[dict, list]:
    """Escanea todos los productos activos. Devuelve (resumen, alertas)."""
    productos = db.scalars(select(Product).where(Product.active.is_(True))).all()
    resumen = {"scanned": 0, "changed": 0, "low_alert": 0, "errors": 0, "nostock": 0}
    alertas = []

    for p in productos:
        ok, alerta = _scan_producto(db, p)
        if not ok:
            resumen["errors"] += 1
            continue
        resumen["scanned"] += 1
        if alerta:
            alertas.append(alerta)
            resumen["changed"] += 1
            if alerta["kind"] == "low":
                resumen["low_alert"] += 1
            elif alerta["kind"] in ("nostock", "restock"):
                resumen["nostock"] += 1

    db.commit()
    return resumen, alertas