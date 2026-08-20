"""Envío de notificaciones a Telegram vía el Bot API (gratis)."""
import httpx

from . import config

API = "https://api.telegram.org/bot{token}/sendMessage"


def _escape(text: str) -> str:
    return text.replace("_", r"\_").replace("*", r"\*").replace("`", r"\`").replace("[", r"\[")


def notify(mensaje: str, kind: str = "") -> bool:
    """Envía un mensaje a Telegram. Devuelve True si se envió."""
    if not config.telegram_configured():
        return False
    try:
        r = httpx.post(
            API.format(token=config.TELEGRAM_BOT_TOKEN),
            json={
                "chat_id": config.TELEGRAM_CHAT_ID,
                "text": mensaje,
                "parse_mode": "Markdown",
                "disable_web_page_preview": False,
            },
            timeout=15,
        )
        r.raise_for_status()
        return r.json().get("ok", False)
    except Exception:
        return False


def _titulo(titulo: str | None, url: str) -> str:
    if titulo:
        return f"[{_escape(titulo)}]({url})"
    return url


def alerta_subida(producto) -> str:
    p = producto.current_price
    return (
        f"📈 *Subió de precio*\n{_titulo(producto.title, producto.url)}\n"
        f"Precio actual: *S/ {p}*"
    )


def alerta_bajada(producto) -> str:
    p = producto.current_price
    return (
        f"📉 *Bajó de precio*\n{_titulo(producto.title, producto.url)}\n"
        f"Precio actual: *S/ {p}*"
    )


def alerta_nuevo_minimo(producto) -> str:
    p = producto.current_price
    return (
        f"🏆 *EXCELENTE: nuevo mejor precio!*\n{_titulo(producto.title, producto.url)}\n"
        f"Precio: *S/ {p}* — el más bajo registrado"
    )


def alerta_vuelve_minimo(producto) -> str:
    p = producto.current_price
    return (
        f"✨ *Volvió a su mejor precio*\n{_titulo(producto.title, producto.url)}\n"
        f"Precio: *S/ {p}* (igual que el mínimo histórico)"
    )


def alerta_sin_stock(producto) -> str:
    return (
        f"🚫 *Sin stock*\n{_titulo(producto.title, producto.url)}\n"
        f"Ya no hay precio disponible (agotado)."
    )


def alerta_volvio_stock(producto) -> str:
    p = producto.current_price
    return (
        f"✅ *Volvió a estar disponible*\n{_titulo(producto.title, producto.url)}\n"
        f"Precio: *S/ {p}*"
    )


def notificar(alertas) -> int:
    """Envía a Telegram todas las alertas. Devuelve cuántas se enviaron."""
    enviadas = 0
    for a in alertas:
        if notify(a["message"]):
            enviadas += 1
    return enviadas