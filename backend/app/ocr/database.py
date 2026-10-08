from datetime import datetime, timezone
import os
from typing import Generator

from sqlalchemy import DateTime, Integer, String, create_engine
from sqlalchemy.orm import DeclarativeBase, Mapped, Session, mapped_column, sessionmaker

from app.ocr.config import DATA_DIR


class Base(DeclarativeBase):
    pass


class UploadedDocument(Base):
    __tablename__ = "ocr_uploaded_documents"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    document_id: Mapped[str | None] = mapped_column(String(20), unique=True)
    filename: Mapped[str] = mapped_column(String(255), unique=True, nullable=False)
    file_type: Mapped[str] = mapped_column(String(100), nullable=False)
    uploaded_by: Mapped[str] = mapped_column(String(100), nullable=False)
    upload_time: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=lambda: datetime.now(timezone.utc)
    )
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="uploaded")


DATA_DIR.mkdir(parents=True, exist_ok=True)
DATABASE_URL = os.getenv(
    "OCR_DATABASE_URL",
    f"sqlite:///{(DATA_DIR / 'ocr_documents.sqlite3').as_posix()}",
)
engine_options = {"connect_args": {"check_same_thread": False}} if DATABASE_URL.startswith("sqlite") else {}
engine = create_engine(DATABASE_URL, **engine_options)
SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False)


def get_db() -> Generator[Session, None, None]:
    Base.metadata.create_all(bind=engine)
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
