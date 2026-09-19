from __future__ import annotations

from templates_test_clients import list_client


def test_unpaginated_list():
    with list_client() as client:
        response = client.get("/unpaginated")
        assert response.status_code == 200
        assert "item-1," in response.text
        assert "item-7," in response.text
        assert "unpaginated" in response.text


def test_paginated_first_page_default():
    with list_client() as client:
        response = client.get("/paginated")
        assert response.status_code == 200
        assert "item-1," in response.text
        assert "item-3," in response.text
        assert "item-4," not in response.text
        assert "page:1/3" in response.text


def test_paginated_second_page():
    with list_client() as client:
        response = client.get("/paginated", query_params={"page": "2"})
        assert response.status_code == 200
        assert "item-4," in response.text
        assert "item-6," in response.text
        assert "item-1," not in response.text
        assert "page:2/3" in response.text


def test_paginated_page_out_of_range_clamps_to_last():
    with list_client() as client:
        response = client.get("/paginated", query_params={"page": "999"})
        assert response.status_code == 200
        assert "item-7," in response.text
        assert "page:3/3" in response.text


def test_paginated_page_not_a_number_falls_back_to_first():
    with list_client() as client:
        response = client.get("/paginated", query_params={"page": "abc"})
        assert response.status_code == 200
        assert "item-1," in response.text
        assert "page:1/3" in response.text


def test_paginated_empty_list():
    with list_client() as client:
        response = client.get("/empty")
        assert response.status_code == 200
        assert "items:\n" in response.text
        assert "page:1/1" in response.text
