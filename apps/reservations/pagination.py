from rest_framework.pagination import PageNumberPagination


class SeatPagination(PageNumberPagination):
    """A seat map needs many rows at once, but still a bounded number."""

    page_size = 200
    page_size_query_param = "page_size"
    max_page_size = 1000
