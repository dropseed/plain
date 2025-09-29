from __future__ import annotations

import collections.abc
import inspect
import warnings
from collections.abc import Iterator
from functools import cached_property
from math import ceil
from typing import Any

from plain.utils.inspect import method_has_no_args


class UnorderedObjectListWarning(RuntimeWarning):
    pass


class InvalidPage(Exception):
    pass


class PageNotAnInteger(InvalidPage):
    pass


class EmptyPage(InvalidPage):
    pass


class Paginator:
    def __init__(
        self,
        object_list: Any,
        per_page: int,
        orphans: int = 0,
        allow_empty_first_page: bool = True,
    ) -> None:
        self.object_list = object_list
        self._check_object_list_is_ordered()
        self.per_page = int(per_page)
        self.orphans = int(orphans)
        self.allow_empty_first_page = allow_empty_first_page

    def __iter__(self) -> Iterator[Page]:
        for page_number in self.page_range:
            yield self.page(page_number)

    def validate_number(self, number: Any) -> int:
        """Validate the given 1-based page number."""
        try:
            if isinstance(number, float) and not number.is_integer():
                raise ValueError
            number = int(number)
        except (TypeError, ValueError):
            raise PageNotAnInteger("That page number is not an integer")
        if number < 1:
            raise EmptyPage("That page number is less than 1")
        if number > self.num_pages:
            raise EmptyPage("That page contains no results")
        return number

    def get_page(self, number: Any) -> Page:
        """
        Return a valid page, even if the page argument isn't a number or isn't
        in range.
        """
        try:
            number = self.validate_number(number)
        except PageNotAnInteger:
            number = 1
        except EmptyPage:
            number = self.num_pages
        return self.page(number)

    def page(self, number: Any) -> Page:
        """Return a Page object for the given 1-based page number."""
        number = self.validate_number(number)
        bottom = (number - 1) * self.per_page
        top = bottom + self.per_page
        if top + self.orphans >= self.count:
            top = self.count
        return self._get_page(self.object_list[bottom:top], number, self)

    def _get_page(self, *args: Any, **kwargs: Any) -> Page:
        """
        Return an instance of a single page.

        This hook can be used by subclasses to use an alternative to the
        standard :cls:`Page` object.
        """
        return Page(*args, **kwargs)

    @cached_property
    def count(self) -> int:
        """Return the total number of objects, across all pages."""
        c = getattr(self.object_list, "count", None)
        if callable(c) and not inspect.isbuiltin(c) and method_has_no_args(c):
            return c()
        return len(self.object_list)

    @cached_property
    def num_pages(self) -> int:
        """Return the total number of pages."""
        if self.count == 0 and not self.allow_empty_first_page:
            return 0
        hits = max(1, self.count - self.orphans)
        return ceil(hits / self.per_page)

    @property
    def page_range(self) -> range:
        """
        Return a 1-based range of pages for iterating through within
        a template for loop.
        """
        return range(1, self.num_pages + 1)

    def _check_object_list_is_ordered(self) -> None:
        """
        Warn if self.object_list is unordered (typically a QuerySet).
        """
        ordered = getattr(self.object_list, "ordered", None)
        if ordered is not None and not ordered:
            obj_list_repr = (
                f"{self.object_list.model} {self.object_list.__class__.__name__}"
                if hasattr(self.object_list, "model")
                else f"{self.object_list!r}"
            )
            warnings.warn(
                "Pagination may yield inconsistent results with an unordered "
                f"object_list: {obj_list_repr}.",
                UnorderedObjectListWarning,
                stacklevel=3,
            )


class Page(collections.abc.Sequence):
    def __init__(self, object_list: Any, number: int, paginator: Paginator) -> None:
        self.object_list = object_list
        self.number = number
        self.paginator = paginator

    def __repr__(self) -> str:
        return f"<Page {self.number} of {self.paginator.num_pages}>"

    def __len__(self) -> int:
        return len(self.object_list)

    def __getitem__(self, index: int | slice) -> Any:
        if not isinstance(index, int | slice):
            raise TypeError(
                f"Page indices must be integers or slices, not {type(index).__name__}."
            )
        # The object_list is converted to a list so that if it was a QuerySet
        # it won't be a database hit per __getitem__.
        if not isinstance(self.object_list, list):
            self.object_list = list(self.object_list)
        return self.object_list[index]

    def has_next(self) -> bool:
        return self.number < self.paginator.num_pages

    def has_previous(self) -> bool:
        return self.number > 1

    def has_other_pages(self) -> bool:
        return self.has_previous() or self.has_next()

    def next_page_number(self) -> int:
        return self.paginator.validate_number(self.number + 1)

    def previous_page_number(self) -> int:
        return self.paginator.validate_number(self.number - 1)

    def start_index(self) -> int:
        """
        Return the 1-based index of the first object on this page,
        relative to total objects in the paginator.
        """
        # Special case, return zero if no items.
        if self.paginator.count == 0:
            return 0
        return (self.paginator.per_page * (self.number - 1)) + 1

    def end_index(self) -> int:
        """
        Return the 1-based index of the last object on this page,
        relative to total objects found (hits).
        """
        # Special case for the last page because there can be orphans.
        if self.number == self.paginator.num_pages:
            return self.paginator.count
        return self.number * self.paginator.per_page
