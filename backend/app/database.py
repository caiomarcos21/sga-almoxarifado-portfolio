import os
from urllib.parse import quote_plus
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker, DeclarativeBase

# Configuração de Conexão:
# 1. Se DATABASE_URL estiver definida no ambiente (ex: PostgreSQL no Render ou string customizada), usa ela.
# 2. Se não estiver definida, tenta conectar automaticamente no Microsoft SQL Server Express local.
# 3. Caso o SQL Server Express não esteja ativo/instalado, faz fallback automático para o SQLite local.

SQL_SERVER_CONN_STR = os.getenv(
    "SQL_SERVER_CONN",
    "DRIVER={ODBC Driver 18 for SQL Server};SERVER=localhost\\SQLEXPRESS;DATABASE=almoxarifado;Trusted_Connection=yes;TrustServerCertificate=yes;"
)

DATABASE_URL = os.getenv("DATABASE_URL")

if not DATABASE_URL:
    usa_sql_server = os.getenv("USE_SQL_SERVER", "true").lower() in ("true", "1", "yes")
    if usa_sql_server:
        try:
            import pyodbc
            conn_test = pyodbc.connect(SQL_SERVER_CONN_STR, timeout=2)
            conn_test.close()
            params = quote_plus(SQL_SERVER_CONN_STR)
            DATABASE_URL = f"mssql+pyodbc:///?odbc_connect={params}"
        except Exception:
            DATABASE_URL = "sqlite:///./almoxarifado.db"
    else:
        DATABASE_URL = "sqlite:///./almoxarifado.db"

# Compatibilidade Render/Heroku PostgreSQL (postgres:// -> postgresql://)
if DATABASE_URL.startswith("postgres://"):
    DATABASE_URL = DATABASE_URL.replace("postgres://", "postgresql://", 1)

BASE_URL = os.getenv("BASE_URL", "http://localhost:8000")  # embutido no QR Code

connect_args = {"check_same_thread": False} if DATABASE_URL.startswith("sqlite") else {}
engine = create_engine(
    DATABASE_URL,
    connect_args=connect_args,
    pool_pre_ping=True
)
SessionLocal = sessionmaker(bind=engine, autoflush=False)


class Base(DeclarativeBase):
    pass


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
