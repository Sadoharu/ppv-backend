# backend/models/__init__.py
# ============================================================================
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy import (
    Boolean, Column, DateTime, ForeignKey, Integer, String, UniqueConstraint,
    Index, Text, text
)
from sqlalchemy.orm import relationship, Mapped, mapped_column
from uuid import uuid4
from backend.database import Base
from datetime import datetime, timezone
from sqlalchemy.ext.hybrid import hybrid_property
from sqlalchemy.sql import func

class Event(Base):
    """Одна трансляція / захід."""
    __tablename__ = "events"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    title: Mapped[str] = mapped_column(String(128), nullable=False)
    slug:  Mapped[str] = mapped_column(String(128), unique=True, index=True)

    # Публічний статус сторінки/івенту (draft|published)
    status = Column(String(16), nullable=False, server_default="draft")

    # Часи з TZ (можуть бути None)
    starts_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    ends_at:   Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    thumbnail_url = Column(Text, nullable=True)
    short_description = Column(Text, nullable=True)

    # (за потреби) маніфест плеєра, але сторінка може обійтись і без плеєра
    player_manifest_url = Column(Text, nullable=True)

    # --- Стрімінг та Аналітика (Bunny CDN + Mux) ---
    # Шлях до відео у Bunny CDN (для підпису токеном), наприклад "/video/playlist.m3u8"
    bunny_video_path = Column(String(512), nullable=True)
    # Специфічний ключ середовища Mux Data для цієї події (перекриває глобальний)
    mux_env_key = Column(String(128), nullable=True)
    # -----------------------------------------------

    # ======= [DEPRECATED, залишено для зворотної сумісності] =================
    # Механіка старих “custom_*”
    custom_mode = Column(String(16), nullable=False, server_default="none")  # none|safe|sandbox
    custom_html = Column(Text, nullable=True)
    custom_css  = Column(Text, nullable=True)
    custom_js   = Column(Text, nullable=True)
    # ========================================================================

    theme = Column(JSONB, nullable=True)

    # ======= ONLY-CUSTOM PAGE поля (нові, для відсутності дефолтів) ==========
    # Повний HTML-каркас сторінки без <script> (скрипти — окремо в page_js)
    page_html = Column(Text, nullable=False, server_default="")
    # Користувацькі стилі
    page_css  = Column(Text, nullable=True)
    # Користувацький JS (віддається окремим ресурсом /event-assets/{id}/user.js)
    page_js   = Column(Text, nullable=True)
    # Версія обов’язкового PPV-runtime, який інʼєктується першим
    runtime_js_version = Column(String(32), nullable=False, server_default="latest")
    # Коли опубліковано (None для draft)
    published_at = Column(DateTime(timezone=True), nullable=True)
    # База для асетів (CDN/S3-префікс)
    assets_base_url = Column(String(512), nullable=True)
    # ETag для кешування сторінки/ресурсів
    etag = Column(String(64), nullable=True, index=True)
    # Токен безпечного превʼю неопублікованої сторінки
    preview_token = Column(String(64), nullable=True, index=True)
    # Службове оновлення (для ETag/If-None-Match); якщо вже є в моделі — можна не дублювати
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now()
    )
    # ========================================================================

    sessions = relationship("Session", back_populates="event", cascade="save-update, merge", passive_deletes=True)
    codes: Mapped[list["AccessCode"]] = relationship(back_populates="event")
    code_batches:  Mapped[list["CodeBatch"]]  = relationship(back_populates="event")


class CodeBatch(Base):
    """Пакет кодів, згенерований разом (для аналітики/доходу)."""
    __tablename__ = "code_batches"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    event_id: Mapped[int | None] = mapped_column(ForeignKey("events.id"), nullable=True)
    label: Mapped[str] = mapped_column(String(64))
    price_uah: Mapped[int | None] = mapped_column(Integer, nullable=True)
    generated_by: Mapped[str] = mapped_column(String(64))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
        default=datetime.utcnow
    )

    event: Mapped["Event"] = relationship(back_populates="code_batches")
    codes: Mapped[list["AccessCode"]] = relationship(back_populates="batch")


class AccessCode(Base):
    __tablename__ = "access_codes"

    id              = Column(Integer, primary_key=True)
    code_plain      = Column(String(32), unique=True, nullable=False)
    code_hash       = Column(String(60), nullable=False)
    allowed_sessions= Column(Integer, default=1)
    allow_all_events = Column(Boolean, nullable=False, server_default=text("false"), default=False)
    revoked         = Column(Boolean, default=False)
    created_at      = Column(DateTime(timezone=True), server_default=func.now())
    expires_at      = Column(DateTime(timezone=True), nullable=True)

    sessions        = relationship("Session", back_populates="code", cascade="all,delete")
    event_id: Mapped[int | None] = mapped_column(ForeignKey("events.id"), nullable=True)
    batch_id: Mapped[int | None] = mapped_column(ForeignKey("code_batches.id"))

    event:  Mapped["Event"] = relationship(back_populates="codes")
    batch:  Mapped["CodeBatch"] = relationship(back_populates="codes")

    __table_args__ = (
        Index("ix_access_codes_event_active", "event_id", "revoked"),
    )

    @hybrid_property
    def is_active(self):
        if self.revoked:
            return False
        if self.expires_at is None:
            return True
        now = datetime.now(timezone.utc)
        return self.expires_at > now


class Session(Base):
    __tablename__ = "sessions"

    id         = Column(String(36), primary_key=True, default=lambda: str(uuid4()))
    code_id    = Column(Integer, ForeignKey("access_codes.id"))
    event_id   = Column(Integer, ForeignKey("events.id", ondelete="SET NULL"), nullable=True, index=True)
    token_jti  = Column(String(36), unique=True)
    ip         = Column(String)
    user_agent = Column(String)
    active     = Column(Boolean, default=True)
    connected  = Column(Boolean, default=False)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    last_seen  = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())

    code = relationship("AccessCode", back_populates="sessions")
    event = relationship("Event", back_populates="sessions")

    watch_seconds: Mapped[int] = mapped_column(Integer, default=0)
    bytes_out:     Mapped[int] = mapped_column(Integer, default=0)

    __table_args__ = (
        Index("ix_sessions_active_last_seen", "active", "last_seen"),
        Index("ix_sessions_created_at", "created_at"),
        Index("ix_sessions_code_active", "code_id", "active"),
    )


class CCUMinutely(Base):
    __tablename__ = "ccu_minutely"
    ts:   Mapped[datetime] = mapped_column(DateTime(timezone=True), primary_key=True)
    ccu:  Mapped[int]      = mapped_column(Integer)


class Order(Base):
    __tablename__ = "orders"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    code_id:  Mapped[int] = mapped_column(ForeignKey("access_codes.id"))
    gateway:  Mapped[str] = mapped_column(String(32))
    amount_uah: Mapped[int] = mapped_column(Integer)
    status:   Mapped[str] = mapped_column(String(32))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    refund_at:  Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    code: Mapped["AccessCode"] = relationship()


class FailedLogin(Base):
    __tablename__ = "failed_logins"
    ip:        Mapped[str]      = mapped_column(String, primary_key=True)
    code_try:  Mapped[str]      = mapped_column(String)
    attempts:  Mapped[int]      = mapped_column(Integer, default=1)
    last_try:  Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class AdminUser(Base):
    __tablename__ = "admin_users"
    id:     Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    email:  Mapped[str] = mapped_column(String(128), unique=True, index=True)
    hashed_password: Mapped[str] = mapped_column(String)
    role:   Mapped[str] = mapped_column(String(32), default="viewer")
    tfa_secret: Mapped[str | None] = mapped_column(String, nullable=True)


class AdminAudit(Base):
    __tablename__ = "admin_audit"
    id:      Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    admin_id: Mapped[int] = mapped_column(ForeignKey("admin_users.id"))
    action:   Mapped[str] = mapped_column(String)
    object:   Mapped[str] = mapped_column(String)
    ip:       Mapped[str] = mapped_column(String)
    ts:       Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class RefreshToken(Base):
    __tablename__='refresh_tokens'
    jti: Mapped[str]=mapped_column(String(36), primary_key=True)
    session_id: Mapped[str]=mapped_column(String(36), ForeignKey('sessions.id', ondelete='CASCADE'), index=True)
    issued_at: Mapped[datetime]=mapped_column(DateTime(timezone=True), server_default=func.now())
    revoked_at: Mapped[datetime]=mapped_column(DateTime(timezone=True), nullable=True)
    replaced_by: Mapped[str]=mapped_column(String(36), nullable=True)
    __table_args__ = (
        Index("ix_refresh_tokens_revoked_at", "revoked_at"),
    )


class SessionEvent(Base):
    __tablename__='session_events'
    id: Mapped[int]=mapped_column(Integer, primary_key=True, autoincrement=True)
    session_id: Mapped[str]=mapped_column(String(36), ForeignKey('sessions.id', ondelete='CASCADE'), index=True)
    event: Mapped[str]=mapped_column(String(32))
    at: Mapped[datetime]=mapped_column(DateTime(timezone=True), server_default=func.now())
    details: Mapped[str]=mapped_column(String, nullable=True)
    __table_args__ = (
        Index("ix_session_events_at", "at"),
    )


class CodeAllowedEvent(Base):
    __tablename__ = "code_allowed_events"
    code_id  = Column(Integer, ForeignKey("access_codes.id", ondelete="CASCADE"), primary_key=True)
    event_id = Column(Integer, ForeignKey("events.id", ondelete="CASCADE"), primary_key=True)

# зручно мати backref
AccessCode.allowed_events = relationship(
    "CodeAllowedEvent",
    cascade="all,delete-orphan",
    passive_deletes=True,
)