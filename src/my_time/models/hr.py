from sqlalchemy import Column, Integer, String, ForeignKey, Date, UniqueConstraint
from ..db import Base


class EmployeeProfile(Base):
    __tablename__ = "employee_profiles"
    user_id = Column(Integer, ForeignKey("users.id"), primary_key=True)
    team_id = Column(Integer, ForeignKey("teams.id"), nullable=False, index=True)
    location_id = Column(Integer, ForeignKey("work_locations.id"), nullable=True)
    department = Column(String(120), default="")
    job_title = Column(String(120), default="")
    joined_on = Column(Date, nullable=True)


class LocationHoliday(Base):
    __tablename__ = "location_holidays"
    id = Column(Integer, primary_key=True)
    team_id = Column(Integer, ForeignKey("teams.id"), nullable=False, index=True)
    location_id = Column(Integer, ForeignKey("work_locations.id"), nullable=False)
    date = Column(Date, nullable=False)
    name = Column(String(200), nullable=False)
    __table_args__ = (UniqueConstraint("location_id", "date", name="uq_location_holiday_date"),)
