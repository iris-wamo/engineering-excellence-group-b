"""Unit tests for taskflow_shared.pagination."""

from pydantic import BaseModel
from taskflow_shared.pagination import PaginatedResponse, PaginationParams


class ItemModel(BaseModel):
    id: int
    name: str


def test_pagination_params_calculations() -> None:
    """Verify offset and limit calculations."""
    p1 = PaginationParams(page=1, page_size=20)
    assert p1.offset == 0
    assert p1.limit == 20

    p2 = PaginationParams(page=3, page_size=15)
    assert p2.offset == 30
    assert p2.limit == 15


def test_paginated_response_create() -> None:
    """Verify total_pages computation and serialization."""
    items = [ItemModel(id=1, name="Item A"), ItemModel(id=2, name="Item B")]

    # 45 items total with page_size=20 -> 3 pages
    res = PaginatedResponse[ItemModel].create(
        items=items,
        total=45,
        page=1,
        page_size=20,
    )
    assert res.total == 45
    assert res.page == 1
    assert res.page_size == 20
    assert res.total_pages == 3
    assert len(res.items) == 2
    assert res.items[0].name == "Item A"

    # Empty list
    empty_res = PaginatedResponse[ItemModel].create(
        items=[],
        total=0,
        page=1,
        page_size=20,
    )
    assert empty_res.total_pages == 0
    assert empty_res.total == 0
