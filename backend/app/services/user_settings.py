"""User settings service: which provider and models this user's chat should use.

The single source of truth for both the settings API and the message handler, so what
the Settings screen shows is exactly what a conversation uses — on every channel.

Resolution is always **user value -> configured default**, so an account that has never
touched settings behaves exactly as it did before this feature existed.
"""

from decimal import Decimal

from sqlalchemy.orm import Session

from app.config import (
    MODEL_CATALOG,
    NO_REASONING_CONTROL,
    available_providers,
    provider_available,
    settings,
)
from app.db.models import User
from app.services import budget
from app.services.errors import Invalid


def resolve(user: User, deep: bool = False) -> tuple[str, str]:
    """Return (provider, model) for a turn. `deep` picks the "think harder" model."""
    provider = user.llm_provider or settings.llm_provider
    if not provider_available(provider):
        # A previously-chosen provider whose credentials were removed must not wedge
        # chat; fall back to the configured default.
        provider = settings.llm_provider
    if deep:
        model = user.model_deep or settings.model_heavy
    else:
        model = user.model_chat or settings.model_chat
    return provider, model


def get_settings(db: Session, user: User) -> dict:
    """Current selection plus what the UI needs to render the pickers. Never includes
    credentials — API keys live in the environment and are not exposed here."""
    provider, model_chat = resolve(user)
    _, model_deep = resolve(user, deep=True)
    return {
        "budget": budget.status(db, user),
        "provider": provider,
        "model_chat": model_chat,
        "model_deep": model_deep,
        "available_providers": available_providers(),
        "model_catalog": MODEL_CATALOG,
        # Models where choosing them for "deep" buys nothing, so the interface can say so
        # instead of offering a toggle that silently changes nothing.
        "no_reasoning_control": sorted(NO_REASONING_CONTROL),
        "defaults": {
            "provider": settings.llm_provider,
            "model_chat": settings.model_chat,
            "model_deep": settings.model_heavy,
        },
        # Pinned on purpose — see `embedding_note`. Shown read-only, never a picker.
        "embedding": {
            "provider": settings.embed_provider,
            "model": settings.embed_model,
            "dimensions": settings.embed_dim,
            "pinned": True,
            "note": (
                "Your saved memories were turned into numbers by this model. A different "
                "model writes those numbers in its own 'language', so old memories would "
                "become unreadable and recall would quietly return the wrong things. "
                "Changing it therefore requires re-processing every stored memory in one "
                "deliberate migration — so it is fixed here."
            ),
        },
    }


def update_settings(
    db: Session,
    user: User,
    *,
    provider: str | None = None,
    model_chat: str | None = None,
    model_deep: str | None = None,
    monthly_budget_usd: Decimal | None = None,
    clear_budget: bool = False,
) -> dict:
    """Partial update of the user's selection. Only fields passed are changed.

    `clear_budget` exists because None already means "field not sent" here; without an
    explicit flag there would be no way to turn a limit back OFF once set.
    """
    if provider is not None:
        if provider not in MODEL_CATALOG:
            raise Invalid(f"unknown provider '{provider}'")
        if not provider_available(provider):
            raise Invalid(f"provider '{provider}' is not configured on the server")
        user.llm_provider = provider
    # Models are free-text on purpose: a newly released model should be usable before
    # the catalog list is updated. Blank means "fall back to the default".
    if model_chat is not None:
        user.model_chat = model_chat.strip() or None
    if model_deep is not None:
        user.model_deep = model_deep.strip() or None
    if clear_budget:
        user.monthly_budget_usd = None
    elif monthly_budget_usd is not None:
        if monthly_budget_usd <= 0:
            raise Invalid("a spend limit must be greater than zero — leave it off instead")
        user.monthly_budget_usd = monthly_budget_usd
    db.commit()
    db.refresh(user)
    return get_settings(db, user)
