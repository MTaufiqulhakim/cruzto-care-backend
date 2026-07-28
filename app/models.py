from datetime import datetime
from sqlalchemy import Column, Integer, String, Float, DateTime, ForeignKey, Text, Enum
import enum
from sqlalchemy.orm import relationship
from app.database import Base

class UserRole(str, enum.Enum):
    ADMIN = "ADMIN"
    TECHNICIAN = "TECHNICIAN"

class User(Base):
    __tablename__ = "users"

    id = Column(Integer, primary_key=True, index=True)
    username = Column(String(50), unique=True, nullable=False)
    hashed_password = Column(String(200), nullable=False)
    role = Column(String(20), default=UserRole.TECHNICIAN)

class Customer(Base):
    __tablename__ = "customers"

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String(100), nullable=False)
    phone = Column(String(20), nullable=False)
    address = Column(Text, nullable=True)

    orders = relationship("Order", back_populates="customer")

class Order(Base):
    __tablename__ = "orders"

    id = Column(String(30), primary_key=True, index=True)  # Format: CRZ-YYYYMMDD-001
    customer_id = Column(Integer, ForeignKey("customers.id"))
    order_type = Column(String(10), default="PICKUP") # PICKUP / DROPOFF
    status = Column(String(30), default="PENDING")    # PENDING, IN_PROGRESS, QC_COMPLETED, DELIVERED
    payment_status = Column(String(10), default="UNPAID") # UNPAID, PAID
    total_amount = Column(Float, default=0.0)
    created_at = Column(DateTime, default=datetime.now)
    updated_at = Column(DateTime, default=datetime.now, onupdate=datetime.now)

    customer = relationship("Customer", back_populates="orders")
    items = relationship("OrderItem", back_populates="order", cascade="all, delete-orphan")

class OrderItem(Base):
    __tablename__ = "order_items"

    id = Column(Integer, primary_key=True, index=True)
    order_id = Column(String(30), ForeignKey("orders.id"))
    shoe_brand_model = Column(String(100), nullable=False)
    service_type = Column(String(100), nullable=False) # e.g., Deep Clean + Reglue
    price = Column(Float, nullable=False)
    before_photo_url = Column(Text, nullable=True)
    after_photo_url = Column(Text, nullable=True)
    notes = Column(Text, nullable=True)

    order = relationship("Order", back_populates="items")

class Inventory(Base):
    __tablename__ = "inventory"

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String(100), nullable=False)
    category = Column(String(50), nullable=False)  # CLEANER, PAINT, GLUE, OTHER
    stock = Column(Float, default=0.0)
    unit = Column(String(20), default="botol")     # ml, botol, pcs, gram
    min_stock = Column(Float, default=5.0)          # Batas minimum peringatan re-stock
    updated_at = Column(DateTime, default=datetime.now, onupdate=datetime.now)