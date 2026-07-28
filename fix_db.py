from app.database import engine
from sqlalchemy import text

with engine.connect() as conn:
    # Menambahkan kolom updated_at ke tabel orders
    conn.execute(text("ALTER TABLE orders ADD COLUMN IF NOT EXISTS updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP;"))
    conn.commit()
    print(" Berhasil menambahkan kolom updated_at ke tabel orders!")