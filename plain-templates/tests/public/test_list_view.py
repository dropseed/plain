def test_unpaginated_list(list_client):
    response = list_client.get("/unpaginated")
    assert response.status_code == 200
    assert "item-1," in response.content.decode()
    assert "item-7," in response.content.decode()
    assert "unpaginated" in response.content.decode()


def test_paginated_first_page_default(list_client):
    response = list_client.get("/paginated")
    assert response.status_code == 200
    assert "item-1," in response.content.decode()
    assert "item-3," in response.content.decode()
    assert "item-4," not in response.content.decode()
    assert "page:1/3" in response.content.decode()


def test_paginated_second_page(list_client):
    response = list_client.get("/paginated?page=2")
    assert response.status_code == 200
    assert "item-4," in response.content.decode()
    assert "item-6," in response.content.decode()
    assert "item-1," not in response.content.decode()
    assert "page:2/3" in response.content.decode()


def test_paginated_page_out_of_range_clamps_to_last(list_client):
    response = list_client.get("/paginated?page=999")
    assert response.status_code == 200
    assert "item-7," in response.content.decode()
    assert "page:3/3" in response.content.decode()


def test_paginated_page_not_a_number_falls_back_to_first(list_client):
    response = list_client.get("/paginated?page=abc")
    assert response.status_code == 200
    assert "item-1," in response.content.decode()
    assert "page:1/3" in response.content.decode()


def test_paginated_empty_list(list_client):
    response = list_client.get("/empty")
    assert response.status_code == 200
    assert "items:\n" in response.content.decode()
    assert "page:1/1" in response.content.decode()
