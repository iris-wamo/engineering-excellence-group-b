"""Generic paginated response models."""

import math
from collections.abc import Sequence
from typing import Any

from pydantic import BaseModel, Field, model_validator


class PaginatedResponse[T](BaseModel):
    """Generic envelope for paginated resource collections."""

    items: list[T] = Field(description="List of records for the requested page")
    total: int = Field(description="Total count of matching records across all pages")
    page: int = Field(description="Current page number (1-indexed)")
    page_size: int = Field(description="Number of records requested per page")
    total_pages: int = Field(default=0, description="Calculated total number of pages")

    @model_validator(mode="before")
    @classmethod
    def _compute_total_pages(cls, data: Any) -> Any:
        if isinstance(data, dict):
            if data.get("total_pages") is None or data.get("total_pages") == 0:
                total = data.get("total", 0)
                page_size = data.get("page_size", 1)
                data["total_pages"] = (
                    math.ceil(total / page_size) if page_size > 0 and total > 0 else 0
                )
        return data

    @classmethod
    def create(
        cls,
        items: Sequence[T],
        total: int,
        page: int,
        page_size: int,
    ) -> "PaginatedResponse[T]":
        """Factory method computing total_pages safely."""
        total_pages = math.ceil(total / page_size) if page_size > 0 and total > 0 else 0
        return cls(
            items=list(items),
            total=total,
            page=page,
            page_size=page_size,
            total_pages=total_pages,
        )
