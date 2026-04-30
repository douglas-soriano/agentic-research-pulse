from contextlib import contextmanager
from datetime import datetime

from sqlalchemy import Column, String, Integer, Boolean, Text, DateTime, create_engine, inspect, text
from sqlalchemy.orm import DeclarativeBase, Session
from sqlalchemy.pool import StaticPool

from app.config import settings
from app.utils.time import utc_now


class Base(DeclarativeBase):
    ...


class PaperRow(Base):
    __tablename__ = "papers"
    id = Column(String, primary_key=True)
    arxiv_id = Column(String, unique=True, index=True)
    title = Column(Text)
    authors = Column(Text)
    abstract = Column(Text)
    published_at = Column(DateTime)
    topic_id = Column(String, index=True)
    full_text = Column(Text, nullable=True)
    chunk_count = Column(Integer, default=0)
    embedded = Column(Boolean, default=False)
    created_at = Column(DateTime, default=utc_now)


class ReviewRow(Base):
    __tablename__ = "reviews"
    id = Column(String, primary_key=True)
    topic_id = Column(String, index=True)
    topic_name = Column(String)
    synthesis = Column(Text)
    citations = Column(Text, default="{}")
    cited_papers = Column(Text)
    papers_processed = Column(Integer, default=0)
    claims_extracted = Column(Integer, default=0)
    citations_verified = Column(Integer, default=0)
    citations_rejected = Column(Integer, default=0)
    version = Column(Integer, default=1)
    created_at = Column(DateTime, default=utc_now)
    updated_at = Column(DateTime, default=utc_now)


class TopicRow(Base):
    __tablename__ = "topics"
    id = Column(String, primary_key=True)
    name = Column(String, unique=True)
    last_fetched_at = Column(DateTime, nullable=True)
    created_at = Column(DateTime, default=utc_now)


class TraceRow(Base):
    __tablename__ = "traces"
    id = Column(String, primary_key=True)
    job_id = Column(String, unique=True, index=True)
    topic = Column(String)
    status = Column(String, default="running")
    steps = Column(Text)
    total_duration_ms = Column(Integer, default=0)
    papers_processed = Column(Integer, default=0)
    claims_extracted = Column(Integer, default=0)
    citations_verified = Column(Integer, default=0)
    citations_rejected = Column(Integer, default=0)
    created_at = Column(DateTime, default=utc_now)
    completed_at = Column(DateTime, nullable=True)


def _make_engine():
    url = settings.database_url
    if url.startswith("sqlite"):
        return create_engine(
            url,
            connect_args={"check_same_thread": False},
            poolclass=StaticPool,
        )
    return create_engine(url)


engine = _make_engine()


def _sqlite_type_for_column(col: Column) -> str:
    t = col.type
    if isinstance(t, (String, Text)):
        return "TEXT"
    if isinstance(t, Integer):
        return "INTEGER"
    if isinstance(t, Boolean):
        return "INTEGER"
    if isinstance(t, DateTime):
        return "DATETIME"
    return "TEXT"


def _sqlite_add_missing_columns() -> None:
    if not str(engine.url).startswith("sqlite"):
        return

    table_defaults: list[tuple[type, dict[str, str]]] = [
        (
            ReviewRow,
            {
                "citations": "'{}'",
                "cited_papers": "'[]'",
                "papers_processed": "0",
                "claims_extracted": "0",
                "citations_verified": "0",
                "citations_rejected": "0",
                "version": "1",
            },
        ),
        (
            PaperRow,
            {
                "chunk_count": "0",
                "embedded": "0",
            },
        ),
        (
            TraceRow,
            {
                "total_duration_ms": "0",
                "papers_processed": "0",
                "claims_extracted": "0",
                "citations_verified": "0",
                "citations_rejected": "0",
            },
        ),
    ]

    insp = inspect(engine)
    with engine.begin() as conn:
        for model_cls, defaults in table_defaults:
            tname = model_cls.__tablename__
            if tname not in insp.get_table_names():
                continue
            existing = {c["name"] for c in insp.get_columns(tname)}
            for col in model_cls.__table__.columns:
                if col.primary_key or col.name in existing:
                    continue
                coltype = _sqlite_type_for_column(col)
                stmt = f"ALTER TABLE {tname} ADD COLUMN {col.name} {coltype}"
                if col.name in defaults:
                    stmt += f" DEFAULT {defaults[col.name]}"
                conn.execute(text(stmt))


def init_db() -> None:
    Base.metadata.create_all(engine)
    _sqlite_add_missing_columns()


@contextmanager
def get_session():
    session = Session(engine)
    try:
        yield session
    finally:
        session.close()
