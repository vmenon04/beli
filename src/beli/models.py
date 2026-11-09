"""Typed models for Beli responses.

Shapes were inferred from live responses, and Beli adds fields often, so every
model keeps unknown fields (``model.model_extra``) instead of dropping them.
"""

from __future__ import annotations

from datetime import date, datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, field_validator


class BeliModel(BaseModel):
    model_config = ConfigDict(extra="allow", populate_by_name=True, frozen=False)


class User(BeliModel):
    id: str
    username: str | None = None
    first_name: str | None = None
    last_name: str | None = None
    full_name: str | None = None
    created_dt: datetime | None = None
    profile_photo: str | None = None
    instagram_url: str | None = None
    tiktok_url: str | None = None
    public: bool | None = None
    school: Any = None
    company: Any = None
    has_supper_club: bool | None = None


class Business(BeliModel):
    id: int
    name: str
    place_id: str | None = None
    status: str | None = None
    city: str | None = None
    borough: str | None = None
    neighborhood: str | None = None
    country: str | None = None
    lat: float | None = None
    lng: float | None = None
    price: int | None = None
    price_key: str | None = None
    website: str | None = None
    phone_number: str | None = None
    cuisines: list[str] = Field(default_factory=list)
    default_category: str | None = None
    quick_link: str | None = None
    tz: str | None = None

    @property
    def price_symbol(self) -> str | None:
        return "$" * self.price if self.price else None


class Ranking(BeliModel):
    """One place you've ranked, with Beli's 0 to 10 score."""

    id: int
    user: str | None = None
    business: Business
    category: str
    score: float | None = None
    value: float | None = None
    created_dt: datetime | None = None
    visit_dates: list[date] = Field(default_factory=list)
    latest_visit_date: date | None = None

    @field_validator("visit_dates", mode="before")
    @classmethod
    def _visit_dates(cls, v: Any) -> Any:
        if not v:
            return []
        out = []
        for item in v:
            if isinstance(item, dict):
                item = item.get("visit_date") or item.get("date") or item.get("value")
            if item:
                out.append(str(item)[:10])
        return out

    @field_validator("latest_visit_date", mode="before")
    @classmethod
    def _latest(cls, v: Any) -> Any:
        return str(v)[:10] if v else None


class Score(BeliModel):
    user_id: str | None = None
    business_id: int
    value: float
    category: str | None = None
    labels: list[str] = Field(default_factory=list)


class Note(BeliModel):
    """The written review text you attached to a place."""

    id: int | None = None
    business: int
    user: str | None = None
    value: str = ""
    start_dt: datetime | None = None
    end_dt: datetime | None = None

    @property
    def text(self) -> str:
        return self.value


class Photo(BeliModel):
    id: int
    business: int
    image: str
    thumbnail: str | None = None
    description: str | None = None
    order: int | None = None
    favorite_dish: Any = None
    created_dt: datetime | None = None
    status: str | None = None
    likes: list[str] = Field(default_factory=list)


class Bookmark(BeliModel):
    """A place on your Want to Try list."""

    id: int | None = None
    business: Business
    category: str | None = None
    start_dt: datetime | None = None


class Guide(BeliModel):
    id: int
    name: str | None = None
    full_title: str | None = None
    subtitle: str | None = None
    description: str | None = None
    audience: str | None = None
    city: str | None = None
    category: str | None = None
    is_draft: bool | None = None
    is_collaborative: bool | None = None
    total_count: int | None = None


class GuideItem(BeliModel):
    business: int
    guide: int
    added_by: Any = None


class Category(BeliModel):
    code: str
    display: str | None = None
    singular: str | None = None
    icon: str | None = None


class SearchResult(BeliModel):
    """A search prediction. ``business`` is the Beli business id when known."""

    business: int | None = None
    description: str | None = None
    place_id: str | None = None
    structured_formatting: dict[str, Any] | None = None

    @property
    def name(self) -> str | None:
        if self.structured_formatting:
            return self.structured_formatting.get("main_text")
        return self.description

    @property
    def address(self) -> str | None:
        if self.structured_formatting:
            return self.structured_formatting.get("secondary_text")
        return None


class ScoreBucket(BeliModel):
    value: str
    count: int
    score: float


class ScoreAverages(BeliModel):
    """Your average score and count per city, country and cuisine."""

    cities: list[ScoreBucket] = Field(default_factory=list, alias="CITY")
    countries: list[ScoreBucket] = Field(default_factory=list, alias="COUNTRY")
    cuisines: list[ScoreBucket] = Field(default_factory=list, alias="CUISINE")


class BusinessHours(BeliModel):
    open_day: int
    close_day: int
    open_time: str
    close_time: str
