"""Generic paginated response models."""

import math
from collections.abc import Sequence

from pydantic import BaseModel, Field


class PaginatedResponse[T](BaseModel):
    """Generic envelope for paginated resource collections."""

    items: list[T] = Field(description="List of records for the requested page")
    total: int = Field(description="Total count of matching records across all pages")
    page: int = Field(description="Current page number (1-indexed)")
    page_size: int = Field(description="Number of records requested per page")
    total_pages: int = Field(description="Calculated total number of pages")

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
