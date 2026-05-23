"""SQLAlchemy ORM models. SQLite-friendly types; the same schema runs on Postgres.

Naming convention:
- Tables prefixed by dataset (smp_, supply_, weather_, fuel_, dr_).
- Time fields stored as UTC-naive ISO timestamps; the *trading hour* is a separate column
  because KEPCO trading time uses an end-of-interval convention (hour 6 = 05:00-06:00).
"""
from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import (
    Column,
    Date,
    DateTime,
    Float,
    Index,
    Integer,
    String,
    UniqueConstraint,
)
from sqlalchemy.orm import DeclarativeBase


def _utcnow() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


class Base(DeclarativeBase):
    pass


class IngestionRun(Base):
    """One row per `collector.run()` invocation. Used for observability / debugging."""

    __tablename__ = "ingestion_run"

    id = Column(Integer, primary_key=True, autoincrement=True)
    dataset_id = Column(String(8), nullable=False, index=True)
    started_at = Column(DateTime, nullable=False, default=_utcnow)
    finished_at = Column(DateTime, nullable=True)
    rows_inserted = Column(Integer, nullable=False, default=0)
    rows_updated = Column(Integer, nullable=False, default=0)
    status = Column(String(16), nullable=False, default="running")  # running | success | error
    error = Column(String(2048), nullable=True)
    params_json = Column(String(2048), nullable=True)


class SmpHourly(Base):
    """D1 — SMP and demand forecast, hourly.

    `trade_hour` follows KEPCO's end-of-interval rule (1..24). E.g. trade_hour=6 → 05:00-06:00.
    """

    __tablename__ = "smp_hourly"
    __table_args__ = (
        UniqueConstraint("trade_date", "trade_hour", "region", name="uq_smp_hourly"),
        Index("ix_smp_hourly_date_region", "trade_date", "region"),
    )

    id = Column(Integer, primary_key=True, autoincrement=True)
    trade_date = Column(Date, nullable=False)
    trade_hour = Column(Integer, nullable=False)  # 1..24
    region = Column(String(8), nullable=False)  # "land" or "jeju"
    smp_krw_per_kwh = Column(Float, nullable=True)
    demand_forecast_mw = Column(Float, nullable=True)
    fetched_at = Column(DateTime, nullable=False, default=_utcnow)


class SupplySnapshot(Base):
    """D2 — point-in-time supply/demand reading."""

    __tablename__ = "supply_snapshot"
    __table_args__ = (
        UniqueConstraint("observed_at", name="uq_supply_snapshot"),
    )

    id = Column(Integer, primary_key=True, autoincrement=True)
    observed_at = Column(DateTime, nullable=False)
    supply_capacity_mw = Column(Float, nullable=True)
    current_demand_mw = Column(Float, nullable=True)
    reserve_mw = Column(Float, nullable=True)
    reserve_ratio_pct = Column(Float, nullable=True)
    fetched_at = Column(DateTime, nullable=False, default=_utcnow)


class WeatherHourly(Base):
    """D3 — ASOS hourly observation per station."""

    __tablename__ = "weather_hourly"
    __table_args__ = (
        UniqueConstraint("station_id", "observed_at", name="uq_weather_hourly"),
        Index("ix_weather_station_time", "station_id", "observed_at"),
    )

    id = Column(Integer, primary_key=True, autoincrement=True)
    station_id = Column(Integer, nullable=False)
    observed_at = Column(DateTime, nullable=False)
    temperature_c = Column(Float, nullable=True)
    precipitation_mm = Column(Float, nullable=True)
    wind_speed_ms = Column(Float, nullable=True)
    wind_direction_deg = Column(Float, nullable=True)
    humidity_pct = Column(Float, nullable=True)
    pressure_hpa = Column(Float, nullable=True)
    fetched_at = Column(DateTime, nullable=False, default=_utcnow)


class FuelCostMonthly(Base):
    """D4 — monthly fuel cost summary."""

    __tablename__ = "fuel_cost_monthly"
    __table_args__ = (
        UniqueConstraint("period_year", "period_month", "fuel_type", name="uq_fuel_cost_monthly"),
    )

    id = Column(Integer, primary_key=True, autoincrement=True)
    period_year = Column(Integer, nullable=False)
    period_month = Column(Integer, nullable=False)
    fuel_type = Column(String(32), nullable=False)  # LNG / COAL / OIL / ...
    fuel_unit_cost = Column(Float, nullable=True)  # 연료단가
    heat_unit_cost = Column(Float, nullable=True)  # 열량단가
    cost_per_kwh = Column(Float, nullable=True)  # 연료비단가
    fetched_at = Column(DateTime, nullable=False, default=_utcnow)


class DrTransactionMonthly(Base):
    """D5/D6 — monthly DR transaction (economic / reliability). One row per (month, resource).

    `dr_type`: 'economic' | 'reliability'
    """

    __tablename__ = "dr_transaction_monthly"
    __table_args__ = (
        UniqueConstraint(
            "period_year",
            "period_month",
            "dr_type",
            "resource_name",
            name="uq_dr_transaction_monthly",
        ),
        Index("ix_dr_period", "period_year", "period_month", "dr_type"),
    )

    id = Column(Integer, primary_key=True, autoincrement=True)
    period_year = Column(Integer, nullable=False)
    period_month = Column(Integer, nullable=False)
    dr_type = Column(String(16), nullable=False)
    resource_name = Column(String(128), nullable=False)
    bid_mwh = Column(Float, nullable=True)
    cleared_mwh = Column(Float, nullable=True)
    settlement_krw = Column(Float, nullable=True)
    raw_columns_json = Column(String(4096), nullable=True)  # preserve unknown columns
    fetched_at = Column(DateTime, nullable=False, default=_utcnow)
