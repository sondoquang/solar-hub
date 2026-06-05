"""Shared DRF pagination.

``StandardPagination`` lets the client override the page size via a
``?page_size=`` query param (capped) so the frontend's "rows per page" control
can re-query the server instead of slicing client-side.
"""

from rest_framework.pagination import PageNumberPagination


class StandardPagination(PageNumberPagination):
    page_size = 25
    page_size_query_param = "page_size"
    max_page_size = 100
