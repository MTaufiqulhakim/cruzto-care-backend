import os
from dotenv import load_dotenv
from passlib.context import CryptContext
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

# Membaca variabel dari file .env
load_dotenv()

DATABASE_URL = os.getenv("DATABASE_URL")
ADMIN_PASS = os.getenv("INITIAL_ADMIN_PASSWORD", "AdminDefault123!")
TECH_PASS = os.getenv("INITIAL_TECH_PASSWORD", "TeknisiDefault123!")

if not DATABASE_URL:
    raise ValueError("DATABASE_URL tidak ditemukan di .env!")

engine = create_engine(DATABASE_URL)
SessionLocal = sessionmaker(bind=engine)
pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")

from app.models import User, Base

# 1. Buat seluruh tabel jika belum ada
Base.metadata.create_all(bind=engine)

# 2. Buat atau Update Akun Admin & Teknisi
db = SessionLocal()

admin_user = db.query(User).filter(User.username == "admin").first()
tech_user = db.query(User).filter(User.username == "teknisi").first()

# Update / Buat Admin
if admin_user:
    admin_user.hashed_password = pwd_context.hash(ADMIN_PASS)
    print("Password 'admin' berhasil diperbarui!")
else:
    admin_user = User(
        username="admin", 
        hashed_password=pwd_context.hash(ADMIN_PASS), 
        role="ADMIN"
    )
    db.add(admin_user)
    print("Akun 'admin' berhasil dibuat!")

# Update / Buat Teknisi
if tech_user:
    tech_user.hashed_password = pwd_context.hash(TECH_PASS)
    print("Password 'teknisi' berhasil diperbarui!")
else:
    tech_user = User(
        username="teknisi", 
        hashed_password=pwd_context.hash(TECH_PASS), 
        role="TECHNICIAN"
    )
    db.add(tech_user)
    print("Akun 'teknisi' berhasil dibuat!")

db.commit()
db.close()