"""Generic paginated response models."""

import math
from collections.abc import Sequence

from pydantic import BaseModel, Field, computed_field


class PaginatedResponse[T](BaseModel):
    """Generic envelope for paginated resource collections."""

    items: list[T] = Field(description="List of records for the requested page")
    total: int = Field(description="Total count of matching records across all pages")
    page: int = Field(description="Current page number (1-indexed)")
    page_size: int = Field(description="Number of records requested per page")

    @computed_field  # type: ignore[prop-decorator]
    @property
    def total_pages(self) -> int:
        """Calculated total number of pages based on total and page_size."""
        if self.page_size > 0 and self.total > 0:
            return math.ceil(self.total / self.page_size)
        return 0

    @classmethod
    def create(
        cls,
        items: Sequence[T],
        total: int,
        page: int,
        page_size: int,
    ) -> "PaginatedResponse[T]":
        """Factory method returning PaginatedResponse."""
        return cls(
            items=list(items),
            total=total,
            page=page,
            page_size=page_size,
        )
