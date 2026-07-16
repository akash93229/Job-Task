import os
from sqlalchemy import create_engine, event
from sqlalchemy.engine import Engine
from sqlalchemy.orm import sessionmaker, declarative_base

DATABASE_URL = os.getenv("DATABASE_URL", "sqlite:///./jobs.db")

connect_args = {}
if DATABASE_URL.startswith("sqlite"):
    connect_args = {
        "check_same_thread": False,
        "timeout": 15,  # 15 seconds busy timeout
    }

engine = create_engine(DATABASE_URL, connect_args=connect_args)

SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

Base = declarative_base()

@event.listens_for(Engine, "connect")
def set_sqlite_pragma(dbapi_connection, connection_record):
    if DATABASE_URL.startswith("sqlite"):
        cursor = dbapi_connection.cursor()
        try:
            cursor.execute("PRAGMA journal_mode=WAL;")
            cursor.execute("PRAGMA synchronous=NORMAL;")
        except Exception:
            pass
        finally:
            cursor.close()

def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
