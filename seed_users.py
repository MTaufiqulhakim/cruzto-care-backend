from app.database import SessionLocal, engine
from app import models, main

# Buat tabel users jika belum ada
models.Base.metadata.create_all(bind=engine)

db = SessionLocal()

# Hash password
admin_pass = main.get_password_hash("cruztocare456")
tech_pass = main.get_password_hash("teknisi123")

# 1. Buat User Admin
if not db.query(models.User).filter(models.User.username == "admin").first():
    admin = models.User(username="admin", hashed_password=admin_pass, role="ADMIN")
    db.add(admin)

# 2. Buat User Teknisi
if not db.query(models.User).filter(models.User.username == "teknisi").first():
    teknisi = models.User(username="teknisi", hashed_password=tech_pass, role="TECHNICIAN")
    db.add(teknisi)

db.commit()
db.close()
print("Akun Admin (admin/admin123) dan Teknisi (teknisi/teknisi123) berhasil dibuat!")