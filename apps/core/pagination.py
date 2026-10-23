from rest_framework.pagination import CursorPagination


class FeedCursorPagination(CursorPagination):
    """Cursor pagination keyed on creation time.

    Feeds grow at the head, so offset pagination would shift rows between
    requests and show duplicates. `-id` breaks ties so that posts created in
    the same instant keep a stable order across pages.
    """

    page_size = 20
    max_page_size = 50
    page_size_query_param = "limit"
    ordering = ("-created_at", "-id")
