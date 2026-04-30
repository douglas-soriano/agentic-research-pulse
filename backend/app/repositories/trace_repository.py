import json

from sqlalchemy import func
from sqlalchemy.orm import Session

from app.database import TraceRow
from app.models.metrics import Metrics
from app.models.trace import Trace, TraceCreate, TraceStep
from app.utils.time import utc_now


class TraceRepository:
    def __init__(self, session: Session):
        self.session = session

    def create(self, data: TraceCreate) -> Trace:


        import uuid
        existing = self.session.query(TraceRow).filter_by(job_id=data.job_id).first()
        if existing:
            existing.status = "running"
            existing.completed_at = None

            self.session.commit()
            return self._to_model(existing)

        row = TraceRow(
            id=str(uuid.uuid4()),
            job_id=data.job_id,
            topic=data.topic,
            status="running",
            steps=json.dumps([]),
        )
        self.session.add(row)
        self.session.commit()
        self.session.refresh(row)
        return self._to_model(row)

    def get_by_job_id(self, job_id: str) -> Trace | None:
        row = self.session.query(TraceRow).filter_by(job_id=job_id).first()
        return self._to_model(row) if row else None

    def append_step(self, job_id: str, step: TraceStep) -> None:
        row = self.session.query(TraceRow).filter_by(job_id=job_id).first()
        if not row:
            return
        steps = json.loads(row.steps)
        steps.append(step.model_dump(mode="json"))
        row.steps = json.dumps(steps)
        self.session.commit()

    def complete(self, job_id: str, stats: dict) -> None:
        row = self.session.query(TraceRow).filter_by(job_id=job_id).first()
        if not row:
            return
        row.status = "completed"
        row.completed_at = utc_now()
        row.total_duration_ms = stats.get("total_duration_ms", 0)
        row.papers_processed = stats.get("papers_processed", 0)
        row.claims_extracted = stats.get("claims_extracted", 0)
        row.citations_verified = stats.get("citations_verified", 0)
        row.citations_rejected = stats.get("citations_rejected", 0)
        self.session.commit()

    def fail(self, job_id: str, error: str) -> None:
        row = self.session.query(TraceRow).filter_by(job_id=job_id).first()
        if not row:
            return
        row.status = "failed"
        row.completed_at = utc_now()

        steps = json.loads(row.steps)
        steps.append({"agent": "system", "tool": None, "input": {}, "output": {"error": error},
                      "duration_ms": 0, "success": False, "error": error,
                      "timestamp": utc_now().isoformat()})
        row.steps = json.dumps(steps)
        self.session.commit()

    def list_recent(self, limit: int = 20) -> list[Trace]:
        rows = (
            self.session.query(TraceRow)
            .order_by(TraceRow.created_at.desc())
            .limit(limit)
            .all()
        )
        return [self._to_model(r) for r in rows]

    def latest_job_ids_by_topic(self, topic_names: list[str]) -> dict[str, str]:
        if not topic_names:
            return {}
        rows = (
            self.session.query(TraceRow.topic, TraceRow.job_id)
            .filter(TraceRow.topic.in_(topic_names))
            .order_by(TraceRow.created_at.desc())
            .all()
        )
        latest_job_ids: dict[str, str] = {}
        for topic_name, job_id in rows:
            if topic_name not in latest_job_ids:
                latest_job_ids[topic_name] = job_id
        return latest_job_ids

    def metrics(self) -> Metrics:
        total_jobs = self.session.query(func.count(TraceRow.id)).scalar() or 0
        failed_jobs = (
            self.session.query(func.count(TraceRow.id))
            .filter(TraceRow.status == "failed")
            .scalar() or 0
        )
        duration_rows = (
            self.session.query(TraceRow.total_duration_ms)
            .filter(TraceRow.status == "completed")
            .order_by(TraceRow.created_at.desc())
            .limit(100)
            .all()
        )
        durations = [row[0] for row in duration_rows if row[0] is not None]
        average_duration = sum(durations) / len(durations) if durations else 0.0
        citation_totals = self.session.query(
            func.sum(TraceRow.citations_verified),
            func.sum(TraceRow.citations_rejected),
        ).filter(TraceRow.status == "completed").first()
        verified_citations = int(citation_totals[0] or 0)
        rejected_citations = int(citation_totals[1] or 0)
        total_citations = verified_citations + rejected_citations
        correctness_rate = verified_citations / total_citations if total_citations > 0 else 0.0
        error_rate = failed_jobs / total_jobs if total_jobs > 0 else 0.0
        return Metrics(
            total_jobs_processed=total_jobs,
            average_duration_ms=round(average_duration, 2),
            citation_correctness_rate=round(correctness_rate, 4),
            error_rate=round(error_rate, 4),
        )

    def _to_model(self, row: TraceRow) -> Trace:
        steps_raw = json.loads(row.steps)
        steps = []
        for s in steps_raw:

            steps.append(TraceStep(**s))
        return Trace(
            id=row.id,
            job_id=row.job_id,
            topic=row.topic,
            status=row.status,
            steps=steps,
            total_duration_ms=row.total_duration_ms,
            papers_processed=row.papers_processed,
            claims_extracted=row.claims_extracted,
            citations_verified=row.citations_verified,
            citations_rejected=row.citations_rejected,
            created_at=row.created_at,
            completed_at=row.completed_at,
        )
