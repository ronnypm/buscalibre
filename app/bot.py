"""Poller del bot de Telegram: escucha mensajes entrantes y responde.

Va en un hilo daemon para no bloquear FastAPI. Abre una sesión de DB propia por
mensaje para responder consultas sobre los libros trackeados:
  - "hola"            -> saludo + comandos
  - "scan"            -> escanea todos los libros y avisa cambios
  - "precios"         -> lista libros con su precio actual y stock
  - "sin stock"       -> libros agotados
  - cualquier consulta -> se le pasa a la IA (con contexto del libro si matchea)
"""
import threading
import time

import httpx

from . import ai, config, crawler, db as dbmod
from .models import PricePoint, Product

# Solo le responde a estas personas (chat_ids). Si está vacío, escucha
# únicamente el chat configurado por TELEGRAM_CHAT_ID (el dueño).
ALLOWED_CHAT_IDS = {str(config.TELEGRAM_CHAT_ID)} if config.TELEGRAM_CHAT_ID else set()

POLL_TIMEOUT = 30  # long polling (segundos)


def _send(chat_id: str, text: str) -> bool:
    try:
        r = httpx.post(
            f"https://api.telegram.org/bot{config.TELEGRAM_BOT_TOKEN}/sendMessage",
            json={"chat_id": chat_id, "text": text},
            timeout=15,
        )
        if not r.json().get("ok", False):
            print(f"[bot] _send falló: {r.json()}", flush=True)
            return False
        return True
    except Exception as e:
        print(f"[bot] _send excepción: {e!r}", flush=True)
        return False


def _fmt_precio(p) -> str:
    return f"S/ {p:.2f}" if isinstance(p, (int, float)) else "—"


def _contexto_bd(db) -> str:
    """Resumen compacto de la BD para que la IA responda con datos reales."""
    libros = db.query(Product).order_by(Product.created_at.asc()).all()
    if not libros:
        return "No hay libros trackeados aún."

    # Historial de cambios de precio (últimos 10) para preguntas de "qué cambió".
    cambios = []
    filas = db.query(PricePoint, Product).join(Product).order_by(PricePoint.scanned_at.asc()).all()
    previo: dict[int, float] = {}
    for pp, prod in filas:
        before = previo.get(pp.product_id)
        if before is not None and abs(before - pp.price) > 1e-6:
            cambios.append(
                f"{prod.title or 'sin título'}: {before:.2f} -> {pp.price:.2f} "
                f"({pp.scanned_at:%d/%m %H:%M})"
            )
        previo[pp.product_id] = pp.price

    lineas = []
    for p in libros:
        precio = _fmt_precio(p.current_price)
        estado = "sin_stock" if not p.in_stock else "disponible"
        alta = p.created_at.strftime("%d/%m %H:%M")
        lista = p.lista or "sin_lista"
        lineas.append(
            f"- {p.title or 'sin título'} | precio {precio} | {estado} | "
            f"lista: {lista} | agregado: {alta} | link: {p.url}"
        )

    historial = (
        "\n\nHistorial de cambios de precio (con fecha y hora del cambio):\n"
        + "\n".join(cambios)
        if cambios
        else ""
    )
    return f"Libros ({len(libros)}), cada uno con su link de compra:\n" + "\n".join(lineas) + historial


def _respuesta_ia(texto: str, db) -> list[str]:
    """Consulta de datos factuales -> respuesta determinista del código (fiable).
    Consulta interpretativa -> IA con contexto acotado."""
    t = texto.lower()

    # ---- Datos factuales, respondidos con lógica real (siempre exactos) ----
    if any(k in t for k in ("sin stock", "agotad", "no tienen stock")):
        return _respuesta_stock(db)
    # Cambios de precio (antes que "precio" para no caer en la lista total).
    if any(k in t for k in ("cambió", "cambio", "cambio de precio", "cambios", "varia", "varió", "variacion", "subió", "bajó", "reciente")):
        return _respuesta_cambios(db)
    # Barato/caro: primero detectar "más caro" para NO devolver el barato.
    if any(k in t for k in ("más caro", "mas caro", "mas cara", "más carita", "mas carita")):
        return _respuesta_barato(db, caro=True)
    if any(k in t for k in ("más barat", "mas barat", "precio más bajo", "precio mas bajo")):
        return _respuesta_barato(db)
    if any(k in t for k in ("último", "ultimo", "libro nuevo", "agregaste", "agregaste")):
        return _respuesta_ultimo_agregado(db)
    if any(k in t for k in ("precio", "precios", "cuánto", "cuanto", "lista", "todos")):
        return _respuesta_precios(db)

    # ---- Consultas interpretativas -> IA ----
    if not ai.config.ai_configured():
        return ["🧠 La IA no está configurada (falta KILO_API_KEY)."]
    contexto = _contexto_bd(db)
    respuesta = ai.ask(texto, contexto_global=contexto)
    return [respuesta or "🤖 No pude responder ahora. Probá de nuevo en un momento."]


def _respuesta_stock(db) -> list[str]:
    agotados = db.query(Product).filter(Product.in_stock.is_(False)).all()
    if not agotados:
        return ["✅ Todos tus libros tienen stock ahora."]
    lineas = [f"{i}. {p.title or 'sin título'}\n   🔗 {p.url}" for i, p in enumerate(agotados, 1)]
    msg = f"🚫 Tenés *{len(agotados)}* libro(s) sin stock:\n\n" + "\n".join(lineas)
    return _chunks(msg)


def _respuesta_barato(db, caro: bool = False) -> list[str]:
    libros = [p for p in db.query(Product).all()
              if p.current_price is not None and p.in_stock]
    if not libros:
        return ["No hay libros con precio registrado."]
    ordenados = sorted(libros, key=lambda p: p.current_price)
    libro = ordenados[-1] if caro else ordenados[0]
    emoji = "💰" if caro else "🏷️"
    texto = f"{emoji} El libro más {'caro' if caro else 'barato'}: *{libro.title}* a S/ {libro.current_price:.2f}\n🔗 {libro.url}"
    return [texto]


def _respuesta_ultimo_agregado(db) -> list[str]:
    from sqlalchemy import desc
    ultimo = db.query(Product).order_by(desc(Product.created_at)).first()
    if not ultimo:
        return ["No hay libros registrados."]
    precio = _fmt_precio(ultimo.current_price)
    return [f"🆕 El último libro que agregaste: *{ultimo.title or 'sin título'}*\n"
            f"💰 {precio} · {'disponible' if ultimo.in_stock else 'sin stock'}\n"
            f"📁 {ultimo.lista or 'sin lista'} · agregado {ultimo.created_at:%d/%m %H:%M}\n"
            f"🔗 {ultimo.url}"]


def _respuesta_cambios(db) -> list[str]:
    """Libros cuyo precio varió entre dos escaneos, según el historial."""
    filas = db.query(PricePoint, Product).join(Product).order_by(PricePoint.scanned_at.asc()).all()
    previo: dict[int, float] = {}
    cambios = []  # (producto, precio_antes, precio_despues, fecha)
    for pp, prod in filas:
        before = previo.get(pp.product_id)
        if before is not None and abs(before - pp.price) > 1e-6:
            cambios.append((prod, before, pp.price, pp.scanned_at))
        previo[pp.product_id] = pp.price

    if not cambios:
        return ["🔒 Ningún libro cambió de precio todavía. Te aviso apenas bajen o suban."]
    # Solo los más recientes (últimos 15) para no saturar.
    cambios = cambios[-15:]
    lineas = []
    for prod, before, despues, ts in cambios:
        direccion = "📉 bajó" if despues < before else "📈 subió"
        lineas.append(f"- {prod.title or 'sin título'}\n   {direccion} {_fmt_precio(before)} → {_fmt_precio(despues)} · {ts:%d/%m %H:%M}")
    msg = f"🔔 {len(cambios)} libro(s) cambiaron de precio recientemente:\n\n" + "\n".join(lineas)
    return _chunks(msg)


def _respuesta_precios(db) -> list[str]:
    libros = db.query(Product).order_by(Product.created_at.asc()).all()
    if not libros:
        return ["Aún no trackeas ningún libro."]
    lineas = [f"- {p.title or 'sin título'} · {_fmt_precio(p.current_price)}"
              f" · {'disponible' if p.in_stock else 'sin stock'}" for p in libros]
    msg = f"📚 Tus *{len(libros)}* libros:\n\n" + "\n".join(lineas)
    return _chunks(msg)


def _reply(texto: str, db) -> list[str]:
    t = texto.lower().strip()
    # "scan" es la única acción técnica real (importa y avisa libros nuevos).
    # Atrapa "scan", "escanea", "escanear", "scanear", "actualiza nuevos".
    if (
        ("scan" in t or "escane" in t or "scanear" in t)
        or ("nuevo" in t and ("libro" in t or "agreg" in t))
    ):
        return _respuesta_scan(db)
    if "hola" in t or "buenas" in t or "help" in t or t == "/start":
        return [("¡Hola! 👋 Soy tu tracker de precios de Buscalibre.\n\n"
                 "Podés preguntarme cualquier cosa sobre tus libros en lenguaje "
                 "natural, por ejemplo:\n"
                 "- \u201c¿cuál fue el último libro que agregué?\u201d\n"
                 "- \u201c¿qué libros no tienen stock?\u201d\n"
                 "- \u201c¿cuál subió más?\u201d\n"
                 "- \u201cscan\u201d → importo y aviso libros nuevos")]
    # Cualquier otra cosa -> la IA, que decide con los datos reales.
    return _respuesta_ia(texto, db)


def _respuesta_scan(db) -> list[str]:
    """Importa la wishlist y reporta SOLO los libros nuevos, con precio y lista."""
    try:
        originales = crawler.importar_wishlist()
    except Exception as e:
        return [f"⚠️ No pude conectarme a buscalibre: {e!r}"]

    urls_db = {p.url for p in db.query(Product.url).all()}
    nuevos = []
    for it in originales:
        url = it.get("url")
        if not url or url in urls_db:
            continue
        urls_db.add(url)
        nuevos.append(it)

    if not nuevos:
        return ["✅ No tenés libros nuevos agregados."]

    # Registramos los nuevos con su precio de la wishlist como línea de base.
    creados = []
    for it in nuevos:
        precio = it.get("precio")
        p = Product(
            url=it["url"],
            source="buscalibre",
            title=it.get("titulo"),
            author=it.get("autor"),
            lista=it.get("lista"),
            current_price=precio,
            initial_price=precio,
            min_price=precio,
            in_stock=precio is not None,
        )
        db.add(p)
        creados.append(p)
    db.commit()

    lineas = []
    for it in nuevos:
        precio = it.get("precio")
        precio_txt = f"S/ {precio:.2f}" if isinstance(precio, (int, float)) else "sin precio"
        lista = it.get("lista") or "sin lista"
        lineas.append(f"🆕 {it.get('titulo') or 'sin título'}\n   💰 {precio_txt} · 📁 {lista}")

    msg = f"🆕 Tenés *{len(nuevos)}* libro(s) nuevo(s):\n\n" + "\n".join(lineas)
    return _chunks(msg)


def _chunks(texto: str, limite: int = 3900) -> list[str]:
    """Corta texto largo en varios mensajes sin romper líneas."""
    if len(texto) <= limite:
        return [texto]
    partes, actual = [], ""
    for linea in texto.splitlines(keepends=True):
        if len(actual) + len(linea) > limite:
            partes.append(actual.rstrip())
            actual = ""
        actual += linea
    if actual:
        partes.append(actual.rstrip())
    return partes or [""]


def _procesar_chat() -> None:
    """Lee mensajes entrantes vía getUpdates y responde en el mismo chat."""
    url = f"https://api.telegram.org/bot{config.TELEGRAM_BOT_TOKEN}/getUpdates"
    offset = None
    while True:
        try:
            params = {
                "timeout": POLL_TIMEOUT,
                "offset": offset,
                "allowed_updates": ["message"],
            }
            r = httpx.get(url, params=params, timeout=POLL_TIMEOUT + 10)
            data = r.json()
            for update in data.get("result", []):
                offset = update["update_id"] + 1
                msg = update.get("message") or {}
                chat = msg.get("chat") or {}
                chat_id = str(chat.get("id"))
                texto = msg.get("text", "")
                print(f"[bot] update={update['update_id']} chat={chat_id} texto={texto!r}", flush=True)
                if not chat_id or not texto:
                    continue
                if ALLOWED_CHAT_IDS and chat_id not in ALLOWED_CHAT_IDS:
                    print(f"[bot] chat {chat_id} no permitido, ignorando", flush=True)
                    continue
                with dbmod.SessionLocal() as sesion:
                    ok = True
                    for m in _reply(texto, sesion):
                        ok = _send(chat_id, m) and ok
                    print(f"[bot] enviado={ok}", flush=True)
        except Exception as e:
            print(f"[bot] error en loop: {e!r}", flush=True)
            time.sleep(5)


def start() -> None:
    if not config.telegram_configured():
        return
    t = threading.Thread(target=_procesar_chat, daemon=True)
    t.start()