"""Crawler de buscalibre: login, importar wishlist y leer precio actual.

Reutiliza el flujo ya validado del scraper original (login AJAX en 2 pasos + el
endpoint /v2/lista-deseos que devuelve el HTML de cada lista).

Importante sobre login: la API de check-password devuelve `password: 1` (int),
NO booleano -> jamás comparar con `is True`; usar truthiness.
"""
import re
from datetime import datetime

import requests
from bs4 import BeautifulSoup

from . import config


def limpiar_precio(texto: str | None) -> float | None:
    """'S/  45,00' -> 45.0. Devuelve None si no hay número."""
    if not texto:
        return None
    m = re.search(r"\d[\d.,]*", texto)
    if not m:
        return None
    num = m.group(0).replace(".", "").replace(",", ".")
    try:
        return round(float(num), 2)
    except ValueError:
        return None


def _login(session: requests.Session) -> None:
    if not config.buscalibre_configured():
        raise RuntimeError("BUSD_EMAIL/BUSD_PASSWORD no configurados")
    r = session.get(f"{config.BUSD_DOMAIN}/v2/u", timeout=25)
    r.raise_for_status()
    soup = BeautifulSoup(r.text, "lxml")
    form = soup.find("form", id="login_form")
    if not form:
        raise RuntimeError("No se encontró el formulario de login")
    ocultos = {
        (i.get("name") or ""): i.get("value", "")
        for i in form.find_all("input", {"type": "hidden"})
    }
    session.get(
        f"{config.BUSD_DOMAIN}/v2/u/checkuser",
        params={"email": config.BUSD_EMAIL},
        timeout=25,
    ).raise_for_status()

    data = dict(ocultos)
    data.update({"email": config.BUSD_EMAIL, "password": config.BUSD_PASSWORD})
    r = session.post(f"{config.BUSD_DOMAIN}/v2/u/check-password", data=data, timeout=25)
    r.raise_for_status()
    if not r.json().get("password"):
        raise RuntimeError("Contraseña de buscalibre incorrecta")
    session.post(
        f"{config.BUSD_DOMAIN}/v2/u", data=data, timeout=25, allow_redirects=True
    ).raise_for_status()


def _lists(session: requests.Session) -> list[dict]:
    """Lee el sidebar del dashboard: [{id, nombre}]."""
    r = session.get(f"{config.BUSD_DOMAIN}/v2/u/dashboard", timeout=30)
    r.raise_for_status()
    soup = BeautifulSoup(r.text, "lxml")
    listas: dict[str, str] = {}
    for li in soup.select('li[data-view="listaDeseosProductos"][data-id]'):
        lid = li.get("data-id")
        span = li.select_one(".nombre") or li.select_one("a span")
        listas[lid] = span.get_text(strip=True) if span else str(lid)
    return [{"id": k, "nombre": v} for k, v in listas.items()]


def _load_list(session: requests.Session, lista: dict) -> list[dict]:
    """Devuelve [{titulo, autor, precio, url}] de una lista."""
    r = session.get(
        f"{config.BUSD_DOMAIN}/v2/lista-deseos",
        params={"id_lista": lista["id"], "action": "load_list"},
        timeout=40,
    )
    r.raise_for_status()
    soup = BeautifulSoup(r.json().get("html", ""), "lxml")
    items = []
    for nodo in soup.select(".productoLista"):
        tit = nodo.select_one(".title")
        if not tit:
            continue
        a = nodo.select_one("a[href]")
        url = a["href"] if a and a.get("href", "").startswith("http") else a["href"] if a else ""
        aut = nodo.select_one(".field.autor")
        precio_nodo = nodo.select_one(".precioAhora")
        items.append(
            {
                "titulo": tit.get_text(strip=True),
                "autor": aut.get_text(strip=True) if aut else None,
                "precio": limpiar_precio(precio_nodo.get_text()) if precio_nodo else None,
                "url": url,
            }
        )
    return items


def importar_wishlist() -> list[dict]:
    """Importa todas las listas de deseos de buscalibre. Devuelve items crudos."""
    session = requests.Session()
    session.headers.update(config.BUSD_HEADERS)
    _login(session)
    items = []
    for lista in _lists(session):
        for it in _load_list(session, lista):
            it["lista"] = lista["nombre"]
            items.append(it)
    return items


def get_current_price(url: str) -> tuple[float | None, str | None, str | None]:
    """Lee una URL de producto. Devuelve (precio, titulo, autor). Sin login (catálogo público)."""
    session = requests.Session()
    session.headers.update(config.BUSD_HEADERS)
    r = session.get(url, timeout=30)
    r.raise_for_status()
    soup = BeautifulSoup(r.text, "lxml")

    precio = None
    for sel in (".precioAhora", ".colPrecio .ped", ".ped", "strong.precio"):
        nodo = soup.select_one(sel)
        if nodo:
            precio = limpiar_precio(nodo.get_text())
            if precio is not None:
                break

    titulo = None
    h1 = soup.find("h1")
    if h1:
        titulo = h1.get_text(strip=True)
    if not titulo:
        meta = soup.find("meta", {"name": "twitter:title"})
        if meta:
            titulo = meta.get("content", "").strip() or None

    autor = None
    at = soup.find("a", {"class": re.compile(r"autor")})
    if at:
        autor = at.get_text(strip=True) or None
    if not autor:
        meta = soup.find("meta", {"name": "twitter:data1"})
        if meta:
            autor = meta.get("content", "").strip() or None

    return precio, titulo, autor


def ensure_login_optional(session: requests.Session) -> bool:
    """Intenta loguearse; devuelve True si quedó logueado (o no era necesario)."""
    if not config.buscalibre_configured():
        return False
    try:
        _login(session)
        return True
    except Exception:
        return False