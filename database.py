import os
import uuid
from datetime import datetime, timezone
from typing import Optional, Generator

from sqlalchemy import Column, LargeBinary, text
from sqlmodel import Field, Relationship, Session, SQLModel, UniqueConstraint, create_engine

DATABASE_URL = os.getenv("DATABASE_URL", "sqlite:///./wallet.db")

# SQLite: enable WAL and foreign keys
connect_args = {}
if DATABASE_URL.startswith("sqlite"):
    connect_args = {"check_same_thread": False}

engine = create_engine(
    DATABASE_URL,
    connect_args=connect_args,
    echo=False,
)


# ---------------------------------------------------------------------------
# Models
# ---------------------------------------------------------------------------

class Pass(SQLModel, table=True):
    __tablename__ = "passes"

    serial_number: str = Field(primary_key=True)
    authentication_token: str
    title: str
    description: str = ""
    discount: str = ""
    organization_name: str
    use_count: int = 0
    max_use: int = 1
    is_rechargeable: bool = False
    keep_after_used_up: bool = True
    expiration_date: Optional[str] = None
    bg_red: float = 0.0
    bg_green: float = 0.0
    bg_blue: float = 0.0
    fg_red: float = 1.0
    fg_green: float = 1.0
    fg_blue: float = 1.0
    lb_red: float = 1.0
    lb_green: float = 1.0
    lb_blue: float = 1.0
    language: str = "en"
    icon_image: Optional[bytes] = Field(default=None, sa_column=Column(LargeBinary, nullable=True))
    last_updated: int = 0
    created_at: str = Field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    relevant_date: Optional[str] = None      # ISO 8601 datetime string
    locations_json: Optional[str] = None     # JSON array of location objects
    ibeacons_json: Optional[str] = None      # JSON array of iBeacon objects

    registrations: list["Registration"] = Relationship(back_populates="pass_")


class Device(SQLModel, table=True):
    __tablename__ = "devices"

    id: Optional[int] = Field(default=None, primary_key=True)
    device_library_identifier: str = Field(unique=True)
    push_token: str

    registrations: list["Registration"] = Relationship(back_populates="device")


class Registration(SQLModel, table=True):
    __tablename__ = "registrations"
    __table_args__ = (UniqueConstraint("device_id", "serial_number"),)

    id: Optional[int] = Field(default=None, primary_key=True)
    device_id: int = Field(foreign_key="devices.id")
    serial_number: str = Field(foreign_key="passes.serial_number")

    device: Optional[Device] = Relationship(back_populates="registrations")
    pass_: Optional[Pass] = Relationship(back_populates="registrations")


class ShareToken(SQLModel, table=True):
    __tablename__ = "share_tokens"

    token: str = Field(default_factory=lambda: str(uuid.uuid4()), primary_key=True)
    serial_number: str = Field(foreign_key="passes.serial_number")
    used: bool = False
    created_at: str = Field(default_factory=lambda: datetime.now(timezone.utc).isoformat())


# ---------------------------------------------------------------------------
# Setup
# ---------------------------------------------------------------------------

def init_db() -> None:
    if DATABASE_URL.startswith("sqlite"):
        from sqlalchemy import event
        from sqlalchemy.engine import Engine
        import sqlite3

        @event.listens_for(Engine, "connect")
        def _set_sqlite_pragmas(dbapi_connection, connection_record):
            if isinstance(dbapi_connection, sqlite3.Connection):
                cursor = dbapi_connection.cursor()
                cursor.execute("PRAGMA journal_mode=WAL")
                cursor.execute("PRAGMA foreign_keys=ON")
                cursor.close()

    SQLModel.metadata.create_all(engine)

def get_session() -> Generator[Session, None, None]:
    with Session(engine) as session:
        yield session
