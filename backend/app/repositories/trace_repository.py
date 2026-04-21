import json
from datetime import datetime

from sqlalchemy.orm import Session

from app.database import TraceRow
from app.models.trace import Trace, TraceCreate, TraceStep


class TraceRepository:
    def __init__(self, session: Session):
        self.session = session

    def create(self, data: TraceCreate) -> Trace:
        # Idempotent: Celery may retry the task with the same job_id.
        # If a trace already exists, reset it to "running" rather than crashing
        # on the UNIQUE constraint.
        import uuid
        existing = self.session.query(TraceRow).filter_by(job_id=data.job_id).first()
        if existing:
            existing.status = "running"
            existing.completed_at = None
            # Keep previous steps so the trace shows all attempts end-to-end
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
        row.completed_at = datetime.utcnow()
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
        row.completed_at = datetime.utcnow()
        # Append an error step
        steps = json.loads(row.steps)
        steps.append({"agent": "system", "tool": None, "input": {}, "output": {"error": error},
                      "duration_ms": 0, "success": False, "error": error,
                      "timestamp": datetime.utcnow().isoformat()})
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

    def _to_model(self, row: TraceRow) -> Trace:
        steps_raw = json.loads(row.steps)
        steps = []
        for s in steps_raw:
            # Pydantic v2 tolerates extra keys, but timestamp may be a string
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
