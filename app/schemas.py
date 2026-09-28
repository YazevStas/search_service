from datetime import datetime
from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field


class SortOrder(StrEnum):
    asc = "asc"
    desc = "desc"


class DocumentOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int = Field(examples=[42])
    rubrics: list[str] = Field(examples=[["VK-1603736028819866", "VK-27544774585"]])
    text: str = Field(examples=["Document text"])
    created_date: datetime = Field(examples=["2019-12-08T06:24:46"])


class ErrorOut(BaseModel):
    detail: str
