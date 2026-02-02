from typing import List
from sqlalchemy.orm import Session
from app.crud.base import CRUDBase
from app.models import Product
from app.schemas.product import ProductCreate, ProductUpdate


class CRUDProduct(CRUDBase[Product, ProductCreate, ProductUpdate]):
    def get_by_shopify_id(self, db: Session, *, shopify_id: str) -> Product:
        return db.query(Product).filter(Product.shopify_id == shopify_id).first()

    def get_available_products(self, db: Session) -> List[Product]:
        return db.query(Product).filter(Product.is_available == True).all()


product = CRUDProduct(Product)