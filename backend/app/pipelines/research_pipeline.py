"""
ResearchPipeline — thin orchestration layer that enqueues async Celery jobs
and returns job handles. Separates the HTTP request lifecycle from long-running work.
"""
import uuid
from datetime import datetime

from app.database import get_session, TopicRow, TraceRow
from app.services.stream_service import stream_service


class ResearchPipeline:
    def start(self, topic_id: str, topic_name: str, max_papers: int = 8) -> str:
        """Enqueue the full pipeline job. Returns job_id for trace tracking."""
        from app.jobs.run_pipeline_job import run_pipeline

        job_id = str(uuid.uuid4())
        stream_service.task_queued(job_id, topic_name)
        run_pipeline.delay(
            job_id=job_id,
            topic_id=topic_id,
            topic_name=topic_name,
            max_papers=max_papers,
        )
        return job_id

    def get_or_create_topic(self, name: str) -> TopicRow:
        with get_session() as session:
            topic = session.query(TopicRow).filter_by(name=name).first()
            if not topic:
                topic = TopicRow(
                    id=str(uuid.uuid4()),
                    name=name,
                    created_at=datetime.utcnow(),
                )
                session.add(topic)
                session.commit()
                session.refresh(topic)
            # Detach from session before returning
            session.expunge(topic)
            return topic

    def list_topics(self) -> list[TopicRow]:
        with get_session() as session:
            topics = session.query(TopicRow).order_by(TopicRow.created_at.desc()).all()
            for t in topics:
                session.expunge(t)
            return topics

    def latest_job_ids(self, topic_names: list[str]) -> dict[str, str]:
        """Return {topic_name: latest_job_id} for the given topic names."""
        if not topic_names:
            return {}
        with get_session() as session:
            rows = (
                session.query(TraceRow.topic, TraceRow.job_id)
                .filter(TraceRow.topic.in_(topic_names))
                .order_by(TraceRow.created_at.desc())
                .all()
            )
        # First occurrence per topic is the most recent (desc order)
        result: dict[str, str] = {}
        for topic_name, job_id in rows:
            if topic_name not in result:
                result[topic_name] = job_id
        return result
