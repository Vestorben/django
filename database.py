import os
from datetime import datetime

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "settings")

from django.conf import settings
from django.utils import timezone
from sqlalchemy import (
    Boolean, CheckConstraint, DateTime, ForeignKey, Integer, String, Text,
    UniqueConstraint, create_engine,
)
from sqlalchemy.engine import URL
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, sessionmaker

CATEGORIES = [
    ("festival", "Фестиваль"),
    ("exhibition", "Выставка"),
    ("workshop", "Мастер-класс"),
    ("lecture", "Лекция"),
    ("concert", "Концерт"),
]

# SQLAlchemy использует те же параметры PostgreSQL, что и Django.
config = settings.DATABASES["default"]
engine = create_engine(URL.create(
    "postgresql+psycopg",
    username=config["USER"], password=config["PASSWORD"],
    host=config["HOST"], port=int(config["PORT"]), database=config["NAME"],
))
Session = sessionmaker(bind=engine, expire_on_commit=False)


class Base(DeclarativeBase):
    pass


class Event(Base):
    __tablename__ = "culture_events"
    __table_args__ = (
        CheckConstraint("capacity > 0", name="positive_capacity"),
        CheckConstraint("ends_at > starts_at", name="valid_event_dates"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    title: Mapped[str] = mapped_column(String(160))
    description: Mapped[str] = mapped_column(Text)
    category: Mapped[str] = mapped_column(String(20))
    region: Mapped[str] = mapped_column(String(100))
    venue: Mapped[str] = mapped_column(String(200))
    starts_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    ends_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    capacity: Mapped[int] = mapped_column(Integer)
    is_cancelled: Mapped[bool] = mapped_column(Boolean, default=False)
    # Постоянный ключ только для демонстрационных событий; не зависит от названия.
    seed_key: Mapped[str | None] = mapped_column(String(50), unique=True)

    @property
    def category_label(self):
        return dict(CATEGORIES).get(self.category, self.category)

    @property
    def status(self):
        if self.is_cancelled:
            return "Отменено"
        now = timezone.now()
        if self.ends_at <= now:
            return "Завершено"
        if self.starts_at <= now:
            return "Идёт сейчас"
        return "Предстоит"


class Registration(Base):
    __tablename__ = "culture_registrations"
    __table_args__ = (UniqueConstraint("event_id", "user_id"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    event_id: Mapped[int] = mapped_column(ForeignKey("culture_events.id"), index=True)
    # ID пользователя Django. SQLAlchemy не описывает и не создаёт auth_user.
    user_id: Mapped[int] = mapped_column(Integer, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=timezone.now)


class Review(Base):
    __tablename__ = "culture_reviews"
    __table_args__ = (
        UniqueConstraint("event_id", "user_id"),
        CheckConstraint("rating BETWEEN 1 AND 5", name="valid_rating"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    event_id: Mapped[int] = mapped_column(ForeignKey("culture_events.id"), index=True)
    user_id: Mapped[int] = mapped_column(Integer, index=True)
    rating: Mapped[int] = mapped_column(Integer)
    text: Mapped[str] = mapped_column(String(1000))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=timezone.now)
