from datetime import datetime
from sqlalchemy import String, Integer, Float, DateTime, BigInteger, Text, ForeignKey
from sqlalchemy.orm import Mapped, mapped_column, relationship

from database import Base


class Vessel(Base):
    __tablename__ = "vessels"

    id: Mapped[int] = mapped_column(primary_key=True)
    mmsi: Mapped[str] = mapped_column(String(9), unique=True, nullable=False)
    imo: Mapped[str | None] = mapped_column(String(10), nullable=True)
    name: Mapped[str | None] = mapped_column(String(100), nullable=True)
    vessel_type: Mapped[int | None] = mapped_column(Integer, nullable=True)
    callsign: Mapped[str | None] = mapped_column(String(10), nullable=True)
    first_seen: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    last_seen: Mapped[datetime] = mapped_column(DateTime, nullable=False)

    visits: Mapped[list["VesselPortVisit"]] = relationship(back_populates="vessel")
    alerts: Mapped[list["SmellAlert"]] = relationship(back_populates="vessel")

    @property
    def display_name(self) -> str:
        return self.name or f"MMSI:{self.mmsi}"

    @property
    def is_tanker(self) -> bool:
        return self.vessel_type is not None and 80 <= self.vessel_type <= 89


class VesselPortVisit(Base):
    __tablename__ = "vessel_port_visits"

    id: Mapped[int] = mapped_column(primary_key=True)
    vessel_id: Mapped[int] = mapped_column(ForeignKey("vessels.id"), nullable=False)
    entered_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    left_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)

    vessel: Mapped["Vessel"] = relationship(back_populates="visits")
    alerts: Mapped[list["SmellAlert"]] = relationship(back_populates="visit")

    @property
    def duration_hours(self) -> float:
        end = self.left_at or datetime.utcnow()
        return (end - self.entered_at).total_seconds() / 3600


class WindReading(Base):
    __tablename__ = "wind_readings"

    id: Mapped[int] = mapped_column(primary_key=True)
    recorded_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    direction_deg: Mapped[float] = mapped_column(Float, nullable=False)
    speed_ms: Mapped[float] = mapped_column(Float, nullable=False)


class SmellAlert(Base):
    __tablename__ = "smell_alerts"

    id: Mapped[int] = mapped_column(primary_key=True)
    sent_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    vessel_id: Mapped[int | None] = mapped_column(ForeignKey("vessels.id"), nullable=True)
    visit_id: Mapped[int | None] = mapped_column(ForeignKey("vessel_port_visits.id"), nullable=True)
    wind_direction: Mapped[float] = mapped_column(Float, nullable=False)
    wind_speed: Mapped[float] = mapped_column(Float, nullable=False)
    risk_score: Mapped[float] = mapped_column(Float, nullable=False)
    vessel_docked_hours: Mapped[float | None] = mapped_column(Float, nullable=True)
    telegram_message_id: Mapped[int | None] = mapped_column(BigInteger, nullable=True)

    vessel: Mapped["Vessel | None"] = relationship(back_populates="alerts")
    visit: Mapped["VesselPortVisit | None"] = relationship(back_populates="alerts")
    feedback: Mapped[list["AlertFeedback"]] = relationship(back_populates="alert")


class AlertFeedback(Base):
    __tablename__ = "alert_feedback"

    id: Mapped[int] = mapped_column(primary_key=True)
    alert_id: Mapped[int] = mapped_column(ForeignKey("smell_alerts.id"), nullable=False)
    feedback_type: Mapped[str] = mapped_column(String(20), nullable=False)
    reported_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)

    alert: Mapped["SmellAlert"] = relationship(back_populates="feedback")
