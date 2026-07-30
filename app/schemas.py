from pydantic import BaseModel
from typing import List, Optional
from datetime import datetime

# --- SCHEMAS CUSTOMER ---
class CustomerBase(BaseModel):
    name: str
    phone: str
    address: Optional[str] = None

class CustomerCreate(CustomerBase):
    pass

class CustomerResponse(CustomerBase):
    id: int

    class Config:
        from_attributes = True  # Pydantic v2 (gunakan orm_mode = True jika Pydantic v1)

# --- SCHEMAS ITEM SEPATU ---
class OrderItemBase(BaseModel):
    shoe_brand_model: str
    service_type: str
    price: float
    notes: Optional[str] = None

class OrderItemCreate(OrderItemBase):
    pass

class OrderItemResponse(OrderItemBase):
    id: int
    order_id: str
    before_photo_url: Optional[str] = None
    after_photo_url: Optional[str] = None

    class Config:
        from_attributes = True

# --- SCHEMAS ORDER ---
class OrderCreate(BaseModel):
    customer: CustomerCreate
    order_type: str
    items: List[OrderItemCreate]
    discount: float = 0.0
    dp: float = 0.0

class OrderResponse(BaseModel):
    id: str
    customer_id: int
    order_type: str
    total_amount: float
    discount: float = 0.0
    dp: float = 0.0
    status: str
    payment_status: str
    created_at: datetime
    customer: Optional[CustomerResponse] = None
    items: List[OrderItemResponse] = []

    class Config:
        from_attributes = True