from __future__ import annotations
from typing import Generic, TypeVar, List
from pydantic import BaseModel, ConfigDict, Field

T = TypeVar("T")

class Page(BaseModel, Generic[T]):
    total: int
    page: int
    page_size: int
    items: List[T] = Field(default_factory=list)
    model_config = ConfigDict(arbitrary_types_allowed=True)