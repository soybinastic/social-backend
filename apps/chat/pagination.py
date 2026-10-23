from rest_framework.pagination import CursorPagination


class InboxCursorPagination(CursorPagination):
    """Cursor pagination over conversations, newest activity first.

    Threads are ordered by when they were last written in rather than when they
    were created, which is the one ordering an inbox can be read in. `-id`
    breaks ties so that pages stay stable.
    """

    page_size = 20
    max_page_size = 50
    page_size_query_param = "limit"
    ordering = ("-last_message_at", "-id")
