import uuid

from app.models.topic import Topic
from app.services.stream_service import stream_service
from app.services.topic_service import TopicService
from app.services.trace_service import TraceService


class ResearchPipeline:
    def __init__(self):
        self.topic_service = TopicService()
        self.trace_service = TraceService()

    def start(self, topic_id: str, topic_name: str, max_papers: int = 8) -> str:
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

    def get_or_create_topic(self, name: str) -> Topic:
        return self.topic_service.get_or_create(name)

    def list_topics(self) -> list[Topic]:
        return self.topic_service.list_all()

    def latest_job_ids(self, topic_names: list[str]) -> dict[str, str]:
        return self.trace_service.latest_job_ids(topic_names)
