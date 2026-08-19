from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.api.deps import get_current_user
from app.api.schemas import BudgetStatus, SettingsOut, SettingsUpdate
from app.db.models import User
from app.db.session import get_db
from app.services import budget
from app.services import user_settings as svc

router = APIRouter(prefix="/api/settings", tags=["settings"])


@router.get("")
def read_settings(
    user: User = Depends(get_current_user), db: Session = Depends(get_db)
) -> SettingsOut:
    """Current selection + what the UI needs to render the pickers.
    Never returns provider credentials — those live only in the environment."""
    return SettingsOut.model_validate(svc.get_settings(db, user))


@router.get("/budget")
def read_budget(
    user: User = Depends(get_current_user), db: Session = Depends(get_db)
) -> BudgetStatus:
    """Just the spend state. Separate from the full settings payload because the chat
    screen re-reads this after every turn, and it has no use for the model catalogue."""
    return BudgetStatus.model_validate(budget.status(db, user))


@router.patch("")
def update_settings(
    body: SettingsUpdate,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> SettingsOut:
    return SettingsOut.model_validate(
        svc.update_settings(db, user, **body.model_dump(exclude_unset=True))
    )
