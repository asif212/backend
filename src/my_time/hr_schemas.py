from datetime import date, datetime, time
from decimal import Decimal
from typing import Literal
from pydantic import Field, model_validator
from .schemas import Input


class PolicyInput(Input):
    name:str=Field(min_length=1,max_length=120)
    annual_days:Decimal=Field(gt=0,le=366,max_digits=5,decimal_places=2)
    accrual:Literal["annual","monthly"]="annual"
    location_id:int|None=None
    approval_steps:int=Field(default=1,ge=1,le=3)
    carry_forward_days:Decimal=Field(default=Decimal("0"),ge=0,le=366,max_digits=5,decimal_places=2)
    waiting_days:int=Field(default=0,ge=0,le=730)
    prorate_joiners:bool=False
    allow_half_day:bool=True


class Enrollment(Input):
    user_id:int
    policy_id:int
    year:int=Field(ge=2020,le=2100)


class ProfileInput(Input):
    name:str=Field(min_length=1,max_length=120)
    department:str=Field(default="",max_length=120)
    job_title:str=Field(default="",max_length=120)
    joined_on:date|None=None
    location_id:int|None=None
    active:bool=True


class CorrectionInput(Input):
    attendance_id:int
    check_in_at:datetime
    check_out_at:datetime
    reason:str=Field(min_length=1,max_length=2000)

    @model_validator(mode="after")
    def times(self):
        from datetime import timezone
        for key in ("check_in_at","check_out_at"):
            value=getattr(self,key)
            if value.tzinfo:
                setattr(self,key,value.astimezone(timezone.utc).replace(tzinfo=None))
        seconds=(self.check_out_at-self.check_in_at).total_seconds()
        if seconds<=0 or seconds>86400:
            raise ValueError("Corrected attendance must be positive and at most 24 hours")
        return self


class TeamSettings(Input):
    timezone:str=Field(min_length=1,max_length=120)
    work_days:str=Field(pattern=r"^[1-7](,[1-7])*$")
    work_start:time
    work_end:time
