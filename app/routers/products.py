"""Endpoints de productos, historial, escaneo, importación y consulta IA."""
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import Session

from .. import crawler, notify
from ..db import get_db
from ..models import PricePoint, Product
from ..schemas import ProductIn, ProductOut, PricePointOut, ScanResult
from ..scanner import _scan_producto, scan_all

router = APIRouter(tags=["productos"])


@router.post("/products", response_model=ProductOut)
def crear_producto(payload: ProductIn, db: Session = Depends(get_db)):
    existe = db.scalars(select(Product).where(Product.url == payload.url)).first()
    if existe:
        return existe

    producto = Product(
        url=payload.url,
        source="buscalibre",
        title=payload.title,
        author=payload.author,
    )
    db.add(producto)
    db.commit()
    db.refresh(producto)

    # Primer escaneo inmediato para fijar la línea de base
    _scan_producto(db, producto)
    db.commit()
    db.refresh(producto)
    return producto


@router.get("/products", response_model=list[ProductOut])
def listar_productos(db: Session = Depends(get_db)):
    return db.scalars(select(Product).order_by(Product.created_at)).all()


@router.get("/products/{producto_id}", response_model=ProductOut)
def obtener_producto(producto_id: int, db: Session = Depends(get_db)):
    p = db.get(Product, producto_id)
    if not p:
        raise HTTPException(404, "Producto no encontrado")
    return p


@router.get("/products/{producto_id}/history", response_model=list[PricePointOut])
def historial(producto_id: int, db: Session = Depends(get_db)):
    if not db.get(Product, producto_id):
        raise HTTPException(404, "Producto no encontrado")
    return db.scalars(
        select(PricePoint)
        .where(PricePoint.product_id == producto_id)
        .order_by(PricePoint.scanned_at)
    ).all()


@router.post("/products/{producto_id}/scan", response_model=ScanResult)
def escanear_producto(producto_id: int, db: Session = Depends(get_db)):
    p = db.get(Product, producto_id)
    if not p:
        raise HTTPException(404, "Producto no encontrado")
    ok, alerta = _scan_producto(db, p)
    db.commit()
    if alerta:
        notify.notify(alerta["message"])
    resumen = {"scanned": 1, "changed": 1 if alerta else 0,
               "low_alert": 1 if alerta and alerta["kind"] == "low" else 0,
               "errors": 0 if ok else 1}
    return resumen


@router.post("/scan", response_model=ScanResult)
def escanear_todo(db: Session = Depends(get_db)):
    resumen, alertas = scan_all(db)
    notify.notificar(alertas)
    return resumen


@router.post("/import/wishlist", response_model=list[ProductOut])
def importar_wishlist(db: Session = Depends(get_db)):
    try:
        originales = crawler.importar_wishlist()
    except RuntimeError as e:
        raise HTTPException(400, str(e))

    creados = []
    vistos: set[str] = set()
    for it in originales:
        if not it.get("url"):
            continue
        url = it["url"]
        if url in vistos:
            continue
        vistos.add(url)
        p = db.scalars(select(Product).where(Product.url == url)).first()
        if p:
            continue
        p = Product(
            url=it["url"],
            source="buscalibre",
            title=it.get("titulo"),
            author=it.get("autor"),
            lista=it.get("lista"),
        )
        db.add(p)
        creados.append(p)
    db.commit()

    # Escaneo inicial de los recién agregados
    for p in creados:
        _scan_producto(db, p)
    db.commit()
    for p in creados:
        db.refresh(p)
    return creados


@router.delete("/products/{producto_id}", status_code=204)
def eliminar_producto(producto_id: int, db: Session = Depends(get_db)):
    p = db.get(Product, producto_id)
    if not p:
        raise HTTPException(404, "Producto no encontrado")
    db.delete(p)
    db.commit()


class PreguntaIn(BaseModel):
    pregunta: str
    producto_id: int | None = None


@router.post("/ai/ask")
def preguntar_ai(payload: PreguntaIn, db: Session = Depends(get_db)):
    from .. import ai
    if not ai.config.ai_configured():
        raise HTTPException(503, "KILO_API_KEY no configurada")
    producto = None
    if payload.producto_id:
        producto = db.get(Product, payload.producto_id)
        if not producto:
            raise HTTPException(404, "Producto no encontrado")
    resp = ai.ask(payload.pregunta, producto)
    if resp is None:
        raise HTTPException(502, "La IA no respondió (verificá KILO_API_KEY / modelo)")
    return {"respuesta": resp, "producto_id": payload.producto_id}