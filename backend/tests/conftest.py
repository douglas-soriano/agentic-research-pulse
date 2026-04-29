import uuid
from datetime import datetime
from unittest.mock import patch

import chromadb
import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

import app.database as db_module
from app.database import Base, init_db


@pytest.fixture
def chroma_collection():
    client = chromadb.EphemeralClient()
    collection = client.get_or_create_collection(
        name="paper_chunks",
        metadata={"hnsw:space": "cosine"},
    )
    with patch("app.tools.vector_tools._collection", collection):
        yield collection


@pytest.fixture
def test_db():
    test_engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    original_engine = db_module.engine
    db_module.engine = test_engine
    Base.metadata.create_all(test_engine)
    try:
        yield test_engine
    finally:
        db_module.engine = original_engine
        test_engine.dispose()


@pytest.fixture
def sample_paper_meta():
    return {
        "arxiv_id": "2005.11401",
        "title": "Retrieval-Augmented Generation for Knowledge-Intensive NLP Tasks",
        "authors": ["Patrick Lewis", "Ethan Perez", "Aleksandara Piktus"],
        "abstract": "We explore a general-purpose fine-tuning recipe for RAG models.",
        "published_at": "2020-05-22T00:00:00+00:00",
        "url": "https://arxiv.org/abs/2005.11401",
    }


@pytest.fixture
def sample_topic_id():
    return str(uuid.uuid4())
