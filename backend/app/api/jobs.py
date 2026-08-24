"""What runs automatically, and switching each one off.

Read-mostly. The only mutation is a per-job toggle, and it writes to a **sparse** table, so
the endpoint stays correct for jobs that did not exist when a preference was last saved.

There is deliberately **no route that triggers a job**. Running work on demand from the
browser turns a scheduler into a remote execution endpoint, and the legitimate need — trying
a job while developing — is served by `python -m app.jobs.run`, which requires shell access
to the machine. The one exception is the test notification, which is not a job.
"""

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.api.deps import get_current_user
from app.api.schemas import JobOut, JobPrefIn
from app.db.models import User
from app.db.session import get_db
from app.services import job_prefs

router = APIRouter(prefix="/api/jobs", tags=["jobs"])


@router.get("", response_model=list[JobOut])
def list_jobs(
    user: User = Depends(get_current_user), db: Session = Depends(get_db)
) -> list[JobOut]:
    return [JobOut(**row) for row in job_prefs.describe(db, user.id)]


@router.patch("/{job_name}", response_model=JobOut)
def set_job(
    job_name: str,
    body: JobPrefIn,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> JobOut:
    try:
        job_prefs.set_enabled(db, user.id, job_name, body.enabled)
    except KeyError as exc:
        # An unknown name is refused rather than stored. A preference for a job that does
        # not exist is indistinguishable afterwards from a job that was removed, and it
        # would sit in the table forever looking meaningful.
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail=f"No such job: {job_name}"
        ) from exc
    row = next(r for r in job_prefs.describe(db, user.id) if r["name"] == job_name)
    return JobOut(**row)
