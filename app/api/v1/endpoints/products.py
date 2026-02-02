from typing import List
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from app import crud, models, schemas
from app.db.session import get_db

router = APIRouter()


@router.get("/", response_model=List[schemas.Product])
def read_products(
    db: Session = Depends(get_db),
    skip: int = 0,
    limit: int = 100,
):
    products = crud.product.get_multi(db, skip=skip, limit=limit)
    return products


@router.get("/{product_id}", response_model=schemas.Product)
def read_product(
    product_id: int,
    db: Session = Depends(get_db),
):
    product = crud.product.get(db, id=product_id)
    if not product:
        raise HTTPException(status_code=404, detail="Product not found")
    return product


@router.post("/", response_model=schemas.Product)
def create_product(
    product_in: schemas.ProductCreate,
    db: Session = Depends(get_db),
):
    product = crud.product.create(db, obj_in=product_in)
    return product