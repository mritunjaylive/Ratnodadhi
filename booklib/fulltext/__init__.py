"""
fulltext – In-book search and background indexing engine.
"""
from booklib.fulltext.store import FullTextStore, get_fulltext_store
from booklib.fulltext.query import search_inside_books, SearchResultGroup
from booklib.fulltext.scheduler import FullTextIndexScheduler

__all__ = [
    "FullTextStore",
    "get_fulltext_store",
    "search_inside_books",
    "SearchResultGroup",
    "FullTextIndexScheduler",
]
