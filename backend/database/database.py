from sqlalchemy import create_engine, event
from sqlalchemy.orm import sessionmaker, Session
from backend.config import settings
from backend.database.models import Base

# SQLite with check_same_thread=False and 30s connection timeout for multi-threaded FastAPI access
engine = create_engine(
    settings.DATABASE_URL,
    connect_args={"check_same_thread": False, "timeout": 30},
    pool_pre_ping=True
)

@event.listens_for(engine, "connect")
def set_sqlite_pragma(dbapi_connection, connection_record):
    cursor = dbapi_connection.cursor()
    try:
        cursor.execute("PRAGMA journal_mode=WAL;")
        cursor.execute("PRAGMA synchronous=NORMAL;")
        cursor.execute("PRAGMA busy_timeout=5000;")
    except Exception:
        pass
    finally:
        cursor.close()

SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

# Auto-create all tables immediately upon database module initialization
try:
    Base.metadata.create_all(bind=engine)
except Exception:
    pass

def init_db():
    Base.metadata.create_all(bind=engine)
    # Ensure backward-compatible columns exist in SQLite database
    from sqlalchemy import text
    with engine.connect() as conn:
        for col_def in [
            "ALTER TABLE alerts ADD COLUMN severity VARCHAR(32) DEFAULT 'MEDIUM'",
            "ALTER TABLE alerts ADD COLUMN evidence_hash VARCHAR(64)",
            "ALTER TABLE alerts ADD COLUMN optical_mode VARCHAR(32) DEFAULT 'DAY_RGB'",
            "ALTER TABLE cameras ADD COLUMN fence_type VARCHAR(32) DEFAULT 'LINE'",
            "ALTER TABLE cameras ADD COLUMN fence_points_json TEXT",
            "ALTER TABLE cameras ADD COLUMN auto_optical_mode INTEGER DEFAULT 1"
        ]:
            try:
                conn.execute(text(col_def))
                conn.commit()
            except Exception:
                pass  # Column already exists


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
