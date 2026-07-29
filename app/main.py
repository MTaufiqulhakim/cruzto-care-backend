from datetime import datetime, timedelta
from pydantic import BaseModel
from fastapi import FastAPI, Depends, HTTPException, UploadFile, File, status
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials, OAuth2PasswordRequestForm
from sqlalchemy.orm import Session, joinedload
from sqlalchemy import extract, func
from typing import List
from fastapi.middleware.cors import CORSMiddleware
from app import models, schemas, database, cloudinary_config
import os
import io
import pandas as pd
from fastapi.responses import Response

try:
    from fpdf import FPDF
except Exception:
    FPDF = None

from jose import jwt, JWTError
from passlib.context import CryptContext

models.Base.metadata.create_all(bind=database.engine)

app = FastAPI(title="Cruzto Care API", version="1.0")

# Konfigurasi CORS agar frontend (Next.js) bisa memanggil API
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

SECRET_KEY = os.getenv("SECRET_KEY", "cruzto_care_secret_key_super_aman")
ALGORITHM = "HS256"
pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")
security_bearer = HTTPBearer()

# --- HELPER JWT & AUTHENTICATION MIDDLEWARE ---
def verify_password(plain_password, hashed_password):
    return pwd_context.verify(plain_password, hashed_password)

def get_password_hash(password):
    return pwd_context.hash(password)

def create_access_token(data: dict):
    to_encode = data.copy()
    expire = datetime.now() + timedelta(hours=12)  # Token berlaku 12 jam
    to_encode.update({"exp": expire})
    return jwt.encode(to_encode, SECRET_KEY, algorithm=ALGORITHM)

# Dependency Verifikasi Token JWT (Keamanan Backend)
def get_current_user(credentials: HTTPAuthorizationCredentials = Depends(security_bearer), db: Session = Depends(database.get_db)):
    token = credentials.credentials
    credentials_exception = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Sesi telah berakhir atau token tidak valid. Silakan login kembali.",
        headers={"WWW-Authenticate": "Bearer"},
    )
    try:
        payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
        username: str = payload.get("sub")
        if username is None:
            raise credentials_exception
    except JWTError:
        raise credentials_exception

    user = db.query(models.User).filter(models.User.username == username).first()
    if user is None:
        raise credentials_exception
    return user


# --- 1. ENDPOINT AUTHENTICATION (PUBLIC) ---
@app.post("/api/auth/login")
def login(form_data: OAuth2PasswordRequestForm = Depends(), db: Session = Depends(database.get_db)):
    user = db.query(models.User).filter(models.User.username == form_data.username).first()
    if not user or not verify_password(form_data.password, user.hashed_password):
        raise HTTPException(status_code=400, detail="Username atau password salah")

    access_token = create_access_token(data={"sub": user.username, "role": user.role})
    return {"access_token": access_token, "token_type": "bearer", "role": user.role}


# --- SCHEMAS INVENTORY ---
class InventoryCreate(BaseModel):
    name: str
    category: str
    stock: float
    unit: str
    min_stock: float

class InventoryUpdateStock(BaseModel):
    stock: float


# --- 2. ENDPOINTS OPERASIONAL INTERNAL (TERPROTEKSI JWT) ---

@app.get("/api/admin/dashboard")
def get_admin_dashboard_stats(db: Session = Depends(database.get_db), current_user: models.User = Depends(get_current_user)):
    today = datetime.now().date()

    today_shoes = db.query(func.count(models.OrderItem.id))\
        .join(models.Order)\
        .filter(func.date(models.Order.created_at) == today).scalar() or 0

    ready_shoes = db.query(models.Order).filter(models.Order.status == 'QC_COMPLETED').all()
    unpaid_orders = db.query(models.Order).filter(models.Order.payment_status == 'UNPAID').all()
    total_unpaid_amount = sum(o.total_amount for o in unpaid_orders)

    three_days_ago = datetime.now() - timedelta(days=3)
    unclaimed_orders = db.query(models.Order)\
        .filter(models.Order.status == 'QC_COMPLETED')\
        .filter(models.Order.created_at <= three_days_ago).all()

    unclaimed_data = []
    for order in unclaimed_orders:
        days_waiting = (datetime.now() - order.created_at).days
        unclaimed_data.append({
            "id": order.id,
            "customer_name": order.customer.name if order.customer else "-",
            "customer_phone": order.customer.phone if order.customer else "-",
            "items_count": len(order.items),
            "total_amount": order.total_amount,
            "payment_status": order.payment_status,
            "days_unclaimed": days_waiting
        })

    low_stock_items = db.query(models.Inventory)\
        .filter(models.Inventory.stock <= models.Inventory.min_stock).all()

    return {
        "today_shoes_count": today_shoes,
        "ready_pickup_count": len(ready_shoes),
        "total_unpaid_amount": total_unpaid_amount,
        "unpaid_orders_count": len(unpaid_orders),
        "low_stock_count": len(low_stock_items),
        "unclaimed_orders": unclaimed_data,
        "low_stock_items": [
            {"id": i.id, "name": i.name, "stock": i.stock, "unit": i.unit, "min_stock": i.min_stock}
            for i in low_stock_items
        ]
    }


@app.get("/api/inventory")
def get_inventory(db: Session = Depends(database.get_db), current_user: models.User = Depends(get_current_user)):
    return db.query(models.Inventory).order_by(models.Inventory.name).all()

@app.post("/api/inventory")
def create_inventory_item(item: InventoryCreate, db: Session = Depends(database.get_db), current_user: models.User = Depends(get_current_user)):
    new_item = models.Inventory(**item.dict())
    db.add(new_item)
    db.commit()
    db.refresh(new_item)
    return new_item

@app.patch("/api/inventory/{item_id}/stock")
def update_inventory_stock(item_id: int, payload: InventoryUpdateStock, db: Session = Depends(database.get_db), current_user: models.User = Depends(get_current_user)):
    item = db.query(models.Inventory).filter(models.Inventory.id == item_id).first()
    if not item:
        raise HTTPException(status_code=404, detail="Item tidak ditemukan")
    item.stock = payload.stock
    db.commit()
    return item


@app.get("/api/analytics/monthly")
def get_monthly_financial_report(year: int, month: int, db: Session = Depends(database.get_db), current_user: models.User = Depends(get_current_user)):
    total_revenue = db.query(func.sum(models.Order.total_amount))\
        .filter(extract('year', models.Order.created_at) == year)\
        .filter(extract('month', models.Order.created_at) == month).scalar() or 0.0

    paid_revenue = db.query(func.sum(models.Order.total_amount))\
        .filter(extract('year', models.Order.created_at) == year)\
        .filter(extract('month', models.Order.created_at) == month)\
        .filter(models.Order.payment_status == 'PAID').scalar() or 0.0

    unpaid_revenue = total_revenue - paid_revenue

    total_shoes = db.query(func.count(models.OrderItem.id))\
        .join(models.Order)\
        .filter(extract('year', models.Order.created_at) == year)\
        .filter(extract('month', models.Order.created_at) == month).scalar() or 0

    return {
        "year": year,
        "month": month,
        "total_revenue": total_revenue,
        "paid_revenue": paid_revenue,
        "unpaid_revenue": unpaid_revenue,
        "total_shoes_processed": total_shoes
    }


@app.get("/api/analytics/monthly/excel")
def export_monthly_financial_excel(year: int, month: int, db: Session = Depends(database.get_db), current_user: models.User = Depends(get_current_user)):
    orders = db.query(models.Order).options(
        joinedload(models.Order.customer),
        joinedload(models.Order.items)
    ).filter(
        extract('year', models.Order.created_at) == year,
        extract('month', models.Order.created_at) == month
    ).order_by(models.Order.created_at.asc()).all()

    data = []
    for ord in orders:
        customer_name = ord.customer.name if ord.customer else "-"
        customer_phone = ord.customer.phone if ord.customer else "-"
        items_desc = " | ".join([f"{i.shoe_brand_model} ({i.service_type})" for i in ord.items])

        data.append({
            "ID Order": ord.id,
            "Tanggal Transaksi": ord.created_at.strftime("%d/%m/%Y %H:%M"),
            "Nama Pelanggan": customer_name,
            "No. WhatsApp": customer_phone,
            "Metode Layanan": ord.order_type,
            "Detail Sepatu & Jasa": items_desc,
            "Total Tagihan (Rp)": ord.total_amount,
            "Status Pembayaran": "LUNAS" if ord.payment_status == "PAID" else "BELUM DIBAYAR",
            "Status Pengerjaan": ord.status
        })

    if not data:
        df = pd.DataFrame(columns=[
            "ID Order", "Tanggal Transaksi", "Nama Pelanggan", "No. WhatsApp",
            "Metode Layanan", "Detail Sepatu & Jasa", "Total Tagihan (Rp)",
            "Status Pembayaran", "Status Pengerjaan"
        ])
    else:
        df = pd.DataFrame(data)

    output = io.BytesIO()
    with pd.ExcelWriter(output, engine='openpyxl') as writer:
        df.to_excel(writer, index=False, sheet_name=f"Laporan {month}-{year}")

    output.seek(0)
    filename = f"Laporan_Keuangan_CruztoCare_{year}_{month:02d}.xlsx"

    return Response(
        content=output.getvalue(),
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": f"attachment; filename={filename}"}
    )


def generate_order_id(db: Session):
    date_str = datetime.now().strftime("%Y%m%d")
    prefix = f"CRZ-{date_str}-"
    last_order = db.query(models.Order).filter(models.Order.id.like(f"{prefix}%")).order_by(models.Order.id.desc()).first()
    
    if not last_order:
        new_num = 1
    else:
        last_num = int(last_order.id.split("-")[-1])
        new_num = last_num + 1
        
    return f"{prefix}{new_num:03d}"


@app.post("/api/orders", response_model=schemas.OrderResponse)
def create_order(order_data: schemas.OrderCreate, db: Session = Depends(database.get_db), current_user: models.User = Depends(get_current_user)):
    # Cari dulu apakah customer dengan nomor HP ini sudah terdaftar
    customer = db.query(models.Customer).filter(models.Customer.phone == order_data.customer.phone).first()
    
    if not customer:
        customer = models.Customer(
            name=order_data.customer.name,
            phone=order_data.customer.phone,
            address=order_data.customer.address
        )
        db.add(customer)
        db.flush()
    else:
        if order_data.customer.address:
            customer.address = order_data.customer.address
            db.flush()

    new_order_id = generate_order_id(db)
    total = sum(item.price for item in order_data.items)
    
    new_order = models.Order(
        id=new_order_id,
        customer_id=customer.id,
        order_type=order_data.order_type,
        total_amount=total
    )
    db.add(new_order)

    for item in order_data.items:
        db_item = models.OrderItem(
            order_id=new_order_id,
            shoe_brand_model=item.shoe_brand_model,
            service_type=item.service_type,
            price=item.price,
            notes=item.notes
        )
        db.add(db_item)

    db.commit()
    db.refresh(new_order)
    return new_order


@app.get("/api/orders", response_model=List[schemas.OrderResponse])
def get_all_orders(skip: int = 0, limit: int = 200, db: Session = Depends(database.get_db), current_user: models.User = Depends(get_current_user)):
    orders = db.query(models.Order).options(
        joinedload(models.Order.customer),
        joinedload(models.Order.items)
    ).order_by(models.Order.created_at.desc()).offset(skip).limit(limit).all()
    return orders


@app.patch("/api/orders/{order_id}/status")
def update_order_status(order_id: str, status: str, db: Session = Depends(database.get_db), current_user: models.User = Depends(get_current_user)):
    order = db.query(models.Order).filter(models.Order.id == order_id).first()
    if not order:
        raise HTTPException(status_code=404, detail="Order tidak ditemukan")
    
    order.status = status.upper()
    db.commit()
    return {"message": f"Status order {order_id} berhasil diubah menjadi {order.status}"}


@app.patch("/api/orders/{order_id}/payment")
def update_payment_status(order_id: str, payment_status: str, db: Session = Depends(database.get_db), current_user: models.User = Depends(get_current_user)):
    order = db.query(models.Order).filter(models.Order.id == order_id).first()
    if not order:
        raise HTTPException(status_code=404, detail="Order tidak ditemukan")
    
    order.payment_status = payment_status.upper()
    db.commit()
    return {"message": f"Status pembayaran order {order_id} berhasil diubah menjadi {order.payment_status}"}


@app.post("/api/items/{item_id}/upload-photo")
def upload_item_photo(item_id: int, photo_type: str, file: UploadFile = File(...), db: Session = Depends(database.get_db), current_user: models.User = Depends(get_current_user)):
    item = db.query(models.OrderItem).filter(models.OrderItem.id == item_id).first()
    if not item:
        raise HTTPException(status_code=404, detail="Item sepatu tidak ditemukan")

    image_url = cloudinary_config.upload_image(file.file)

    if photo_type == "before":
        item.before_photo_url = image_url
    elif photo_type == "after":
        item.after_photo_url = image_url
    else:
        raise HTTPException(status_code=400, detail="photo_type harus 'before' atau 'after'")

    db.commit()
    return {"message": "Foto berhasil diunggah", "url": image_url}


@app.delete("/api/orders/{order_id}")
def delete_order(order_id: str, db: Session = Depends(database.get_db), current_user: models.User = Depends(get_current_user)):
    order = db.query(models.Order).filter(models.Order.id == order_id).first()
    if not order:
        raise HTTPException(status_code=404, detail="Order tidak ditemukan")
    
    db.query(models.OrderItem).filter(models.OrderItem.order_id == order_id).delete()
    db.delete(order)
    db.commit()
    return {"message": "Order berhasil dihapus"}


# --- 3. PUBLIC ENDPOINTS (TANPA BUBUTUHAN JWT TOKEN) ---

@app.get("/api/orders/{order_id}", response_model=schemas.OrderResponse)
def get_order_for_tracking(order_id: str, db: Session = Depends(database.get_db)):
    order = db.query(models.Order).options(
        joinedload(models.Order.customer),
        joinedload(models.Order.items)
    ).filter(models.Order.id == order_id).first()
    
    if not order:
        raise HTTPException(status_code=404, detail="Order tidak ditemukan")
    return order


LOGO_PATH = os.path.join(os.path.dirname(__file__), "logo.jpeg")

class CruztoPDFInvoice(FPDF):
    def __init__(self):
        super().__init__(orientation='P', unit='mm', format='A4')
        self.set_margins(12, 12, 12)
        self.set_auto_page_break(auto=False)

    def draw_decorations(self):
        self.set_fill_color(60, 85, 120)
        self.ellipse(x=80, y=-50, w=150, h=85, style='F')
        self.ellipse(x=-50, y=260, w=150, h=85, style='F')

@app.get("/api/orders/{order_id}/pdf")
def generate_order_pdf(order_id: str, db: Session = Depends(database.get_db)):
    order = db.query(models.Order).options(
        joinedload(models.Order.customer),
        joinedload(models.Order.items)
    ).filter(models.Order.id == order_id).first()
    
    if not order:
        raise HTTPException(status_code=404, detail="Order tidak ditemukan")

    pdf = CruztoPDFInvoice()
    pdf.add_page()
    pdf.draw_decorations()

    if os.path.exists(LOGO_PATH):
        pdf.image(LOGO_PATH, x=12, y=6, w=30)

    y_meta = 38
    created_date = order.created_at.strftime("%d %B %Y") if order.created_at else "-"
    customer_name = order.customer.name if order.customer else "-"
    customer_phone = order.customer.phone if order.customer else "-"
    customer_address = order.customer.address if (order.customer and order.customer.address) else "-"

    pdf.set_font('Helvetica', 'B', 9.5)
    pdf.set_text_color(0, 0, 0)
    
    pdf.set_xy(12, y_meta)
    pdf.cell(15, 5, "Date", ln=0)
    pdf.cell(5, 5, ":", ln=0)
    pdf.cell(60, 5, created_date, ln=1)

    pdf.set_xy(12, y_meta + 5)
    pdf.cell(15, 5, "Name", ln=0)
    pdf.cell(5, 5, ":", ln=0)
    pdf.cell(60, 5, customer_name, ln=1)

    pdf.set_xy(110, y_meta)
    pdf.cell(28, 5, "Booking Info", ln=0)
    pdf.set_font('Helvetica', '', 9.5)
    pdf.cell(0, 5, f"-  {customer_phone}  -", ln=1)

    pdf.set_xy(110, y_meta + 5)
    pdf.set_font('Helvetica', 'B', 9.5)
    pdf.cell(28, 5, "Address:", ln=0)
    pdf.set_font('Helvetica', '', 9)
    pdf.cell(0, 5, customer_address, ln=1)

    pdf.set_y(y_meta + 18)
    w_desc, w_qty, w_price, w_amount = 86, 25, 37.5, 37.5

    pdf.set_fill_color(0, 0, 0)
    pdf.set_text_color(255, 255, 255)
    pdf.set_draw_color(60, 85, 120)
    pdf.set_line_width(0.4)
    pdf.set_font('Helvetica', 'B', 10)

    pdf.cell(w_desc, 9, 'DESCRIPTION', border=1, align='C', fill=True)
    pdf.cell(w_qty, 9, 'QTY.', border=1, align='C', fill=True)
    pdf.cell(w_price, 9, 'PRICE', border=1, align='C', fill=True)
    pdf.cell(w_amount, 9, 'AMOUNT', border=1, align='C', fill=True, ln=True)

    pdf.set_font('Helvetica', '', 8.5)
    pdf.set_text_color(70, 90, 120)

    items = order.items
    for i in range(7):
        if i < len(items):
            item = items[i]
            desc = f"{item.shoe_brand_model} - {item.service_type}" if item.shoe_brand_model else item.service_type
            qty = "1 pasang"
            price_str = f"{int(item.price):,}".replace(",", ".")
            amount_str = price_str
        else:
            desc, qty, price_str, amount_str = "", "", "", ""

        pdf.cell(w_desc, 8, f"  {desc}", border=1, align='L')
        pdf.cell(w_qty, 8, qty, border=1, align='C')
        pdf.cell(w_price, 8, price_str, border=1, align='C')
        pdf.cell(w_amount, 8, amount_str, border=1, align='C', ln=True)

    pdf.ln(5)
    y_bottom = pdf.get_y()

    pdf.set_text_color(0, 0, 0)
    pdf.set_xy(12, y_bottom)
    pdf.set_font('Helvetica', '', 9.5)
    pdf.cell(0, 5, "Note:", ln=1)

    pdf.set_font('Helvetica', '', 9)
    pdf.set_x(12)
    pdf.cell(0, 4.5, "  -   Reglue dihitung persatu sepatu", ln=1)
    pdf.set_x(12)
    pdf.cell(0, 4.5, "  -   Reglue garansi 1 bulan", ln=1)

    total_str = f"{int(order.total_amount):,}".replace(",", ".")

    pdf.set_xy(110, y_bottom)
    pdf.set_font('Helvetica', 'B', 9.5)
    pdf.cell(30, 5, "Discount:", align='L')
    pdf.cell(30, 5, "Rp", align='R', ln=1)

    pdf.set_xy(110, y_bottom + 5)
    pdf.cell(30, 5, "Dp:", align='L')
    pdf.cell(30, 5, "Rp", align='R', ln=1)

    pdf.set_xy(110, y_bottom + 10)
    pdf.set_font('Helvetica', 'B', 10.5)
    pdf.cell(30, 6, "Total:", align='L')
    pdf.cell(30, 6, f"Rp {total_str}", align='R', ln=1)

    pdf.set_draw_color(120, 120, 120)
    pdf.set_line_width(0.6)
    pdf.line(125, y_bottom + 27, 198, y_bottom + 27)

    if os.path.exists(LOGO_PATH):
        pdf.image(LOGO_PATH, x=150, y=y_bottom + 30, w=26)

    pdf_output = pdf.output(dest='S')
    if isinstance(pdf_output, str):
        pdf_bytes = pdf_output.encode('latin-1')
    elif isinstance(pdf_output, (bytes, bytearray)):
        pdf_bytes = bytes(pdf_output)
    else:
        pdf_bytes = str(pdf_output).encode('latin-1')

    return Response(
        content=pdf_bytes,
        media_type="application/pdf",
        headers={"Content-Disposition": f"inline; filename=Nota_{order_id}.pdf"}
    )