"""Integración con Kilo AI (plata gratuita, API compatible con OpenAI).

Funciones:
- smart_alert: agarra un evento de precio y genera un mensaje natural con el libro,
  autor, precio, link y el mínimo histórico + un veredicto de compra (subió / buena
  oportunidad / vuelve al mínimo / excselente comprá).
- ask: responde preguntas del usuario sobre un libro usando sus datos trackeados.

Todo es OPCIONAL: si no hay KILO_API_KEY, `smart_alert` devuelve None y el scanner
usa las plantillas normales.
"""
from . import config


def _chat(prompt: str, system: str, max_tokens: int = 1000) -> str | None:
    # Nota: kil-auto/free gasta gran parte del presupuesto en "reasoning"; hace falta
    # un max_tokens generoso, si no el texto final queda en blanco (finish=length).
    try:
        from openai import OpenAI
        # timeout alto: el modelo free razona bastante y el contexto puede ser grande.
        client = OpenAI(base_url=config.KILO_BASE_URL, api_key=config.KILO_API_KEY, timeout=120.0)
        r = client.chat.completions.create(
            model=config.KILO_MODEL,
            messages=[
                {"role": "system", "content": system},
                {"role": "user", "content": prompt},
            ],
            max_tokens=max_tokens,
        )
        txt = r.choices[0].message.content
        return txt.strip() if txt and txt.strip() else None
    except Exception as e:
        print(f"[ai] error en _chat: {e!r}", flush=True)
        return None


def smart_alert(producto, evento: str, prev_price: float | None) -> str | None:
    """Genera una alerta inteligente de precio. evento: 'up' | 'down' | 'low'."""
    if not config.ai_configured():
        return None

    precio = producto.current_price
    minimo = producto.min_price
    titulo = producto.title or "este libro"
    autor = producto.author or "desconocido"

    reglas = {
        "low": "el precio rompió o volvió a su mínimo histórico: es EXCELENTE, recomienda comprar.",
        "down": "el precio BAJÓ respecto del escaneo anterior. Si está cerca del mínimo histórico, señala que es una buena oportunidad; si tienes el dinero, sugiere comprar. Explica brevemente.",
        "up": "el precio SUBIÓ respecto del escaneo anterior. Avisa que subió y que quizá conviene esperar a que baje.",
    }
    system = (
        "Sos un asistente de compras de libros. Escribís en español, directo y breve. "
        "Siempre incluís: el nombre del libro, el autor, el precio actual en soles (S/) "
        "y el link. Terminás con una etiqueta corta del tipo: —EXCELENTE: comprá—, "
        "—Buena oportunidad—, —Subió, esperá—."
    )
    prompt = (
        f"Libro: {titulo}\nAutor: {autor}\nPrecio actual: S/ {precio}\n"
        f"Menor precio histórico: S/ {minimo if minimo is not None else 'desconocido'}\n"
        f"Precio anterior: S/ {prev_price if prev_price is not None else 'n/a'}\n"
        f"Link: {producto.url}\n\n"
        f"Evento: {reglas.get(evento)}. Redactá la alerta."
    )
    return _chat(prompt, system)


def ask(question: str, producto=None, contexto_global: str = "") -> str | None:
    """Responde una pregunta del usuario.

    - producto: info de un solo libro (opcional).
    - contexto_global: resumen de la BD (precios, stock, cambios, fecha de alta).
      Permite que la IA responda consultas como "¿cuál fue el último que
      agregué?" o "¿qué libro subió más?" con datos reales.
    """
    if not config.ai_configured():
        return None

    contexto = ""
    if producto is not None:
        if producto.in_stock:
            precio = producto.current_price if producto.current_price is not None else "sin precio"
            contexto = (
                f"Datos del libro consultado:\n"
                f"- Título: {producto.title or 'desconocido'}\n"
                f"- Autor: {producto.author or 'desconocido'}\n"
                f"- Precio actual: S/ {precio}\n"
                f"- Menor precio histórico: S/ {producto.min_price if producto.min_price is not None else 'desconocido'}\n"
                f"- Link: {producto.url}\n\n"
                f"No inventes datos; usá estos si aplican a la pregunta.\n"
            )
        else:
            contexto = (
                f"Datos del libro consultado:\n"
                f"- Título: {producto.title or 'desconocido'}\n"
                f"- Autor: {producto.author or 'desconocido'}\n"
                f"- ESTADO: el libro NO tiene stock disponible ahora mismo, así que no hay "
                f"precio actual ni histórico para mostrar.\n"
                f"- Link: {producto.url}\n\n"
                f"Si te preguntan por precio, o si conviene esperar, explicá que no hay stock "
                f"y que no se puede saber el precio hasta que vuelva a estar disponible. "
                f"Ofrecé revisar el link."
            )
    if contexto_global:
        contexto += (
            f"\nRESUMEN DE TODOS TUS LIBROS TRACKEADOS (datos reales):\n"
            f"{contexto_global}\n"
            f"Usá estos datos para responder; no inventes precios ni libros.\n"
        )
    system = (
        "Sos un asistente de compras de libros que responde en español, breve y útil. "
        "Tenés acceso a los datos reales de los libros trackeados del usuario, "
        "cada uno con su link de compra.\n"
        "Reglas:\n"
        "- Respondé SOLO según esos datos; no inventes libros, precios ni links.\n"
        "- Si la pregunta apunta a un libro puntual (el más barato, el último "
        "agregado, el que cambió, el que subió), buscá ese libro y decí su nombre, "
        "precio y link de compra. No listes toda la colección.\n"
        "- Incluí el link de compra como texto/Markdown siempre que menciones un "
        "libro concreto.\n"
        "- Si el historial de cambios está vacío, aclará que todavía no hubo "
        "cambios de precio registrados."
    )
    return _chat(contexto + "Pregunta del usuario: " + question, system, max_tokens=1500)