"""App config endpoints — all admin-controlled, never hardcoded."""
from fastapi import APIRouter
from app.db.firebase import get_db, Col
from app.schemas import AppConfig, HomepageBanner, HomepageConfig, HomepageSection
from datetime import datetime, timezone
from app.services.admin_settings import active_banners
from app.services.mappers import build_app_config

router = APIRouter(prefix="/config", tags=["config"])

_DEFAULT_SECTIONS = [
    HomepageSection(id="featured_banner",   label="Featured Banner",   enabled=True, order=1),
    HomepageSection(id="featured_videos",   label="Featured Videos",   enabled=True, order=2),
    HomepageSection(id="trending_videos",   label="Trending Videos",   enabled=True, order=3),
    HomepageSection(id="latest_videos",     label="Latest Videos",     enabled=True, order=4),
    HomepageSection(id="popular_categories",label="Categories",        enabled=True, order=5),
    HomepageSection(id="featured_packages", label="Featured Packages", enabled=True, order=6),
]


def _banners(data: dict) -> list[HomepageBanner]:
    """Enabled banners inside their window; one malformed admin entry never breaks the homepage."""
    out: list[HomepageBanner] = []
    for b in active_banners(data.get("homepage_banners"), datetime.now(timezone.utc)):
        try:
            out.append(HomepageBanner(**b))
        except Exception:
            continue
    return out


@router.get("", response_model=AppConfig)
async def get_app_config():
    db = get_db()
    doc = await db.collection(Col.APP_SETTINGS).document("config").get()
    # Missing document or missing/invalid fields fall back to safe defaults
    # (mappers.build_app_config) instead of failing the whole app with a 500.
    return build_app_config(doc.to_dict() if doc.exists else None)


@router.get("/homepage", response_model=HomepageConfig)
async def get_homepage_config():
    db = get_db()
    doc = await db.collection(Col.APP_SETTINGS).document("config").get()
    if not doc.exists:
        return HomepageConfig(sections=_DEFAULT_SECTIONS)
    data = doc.to_dict() or {}
    banners = _banners(data)
    raw = data.get("homepage_sections", [])
    if not raw:
        return HomepageConfig(sections=_DEFAULT_SECTIONS, banners=banners)
    sections: list[HomepageSection] = []
    for item in raw:
        try:
            sections.append(HomepageSection(**item))
        except Exception:
            continue  # one malformed admin entry must not break the homepage
    if not sections:
        return HomepageConfig(sections=_DEFAULT_SECTIONS, banners=banners)
    sections.sort(key=lambda s: s.order)
    return HomepageConfig(sections=sections, banners=banners)
