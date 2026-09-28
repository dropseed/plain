from plain.paginator import Paginator
from plain.test import cases, raises


@cases(0, -1)
def test_raises_for_non_positive_per_page(per_page):
    with raises(ValueError, match="per_page must be at least 1"):
        Paginator([1, 2, 3], per_page)


def test_accepts_positive_per_page():
    paginator = Paginator([1, 2, 3], 1)
    assert paginator.num_pages == 3
