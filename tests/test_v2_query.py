"""
test_v2_query.py – Tests for FTS query builder, LibraryQuery and SQL querying.
"""
from pathlib import Path

import pytest

from booklib.db.database import Database, natural_compare
from booklib.db.query import LibraryQuery, build_fts_query
from booklib.db.repository import Repository


def test_build_fts_query_edge_cases():
    assert build_fts_query("") is None
    assert build_fts_query("   ") is None
    assert build_fts_query("tolstoy") == '"tolstoy"*'
    assert build_fts_query("war and peace") == '"war"* "and"* "peace"*'
    assert build_fts_query('"quoted text"') == '"quoted"* "text"*'
    assert build_fts_query("c++") == '"c"*'
    assert build_fts_query("a-b") == '"a"* "b"*'
    assert build_fts_query("*") is None
    # Non-English / Unicode script (Hindi)
    hindi_query = build_fts_query("युद्ध और शांति")
    assert hindi_query is not None
    assert '"युद्ध"*' in hindi_query
    assert '"शांति"*' in hindi_query


def test_natural_compare():
    assert natural_compare("Book 2", "Book 10") < 0
    assert natural_compare("Book 10", "Book 2") > 0
    assert natural_compare("Book 2", "book 2") == 0
    assert natural_compare("apple", "banana") < 0


@pytest.fixture()
def seeded_repo(tmp_path: Path):
    db = Database(tmp_path / "query_test.db")
    conn = db.connect()
    repo = Repository(conn)

    fid = repo.add_folder("/books")

    # Add several books with diverse metadata
    repo.upsert_book(
        folder_id=fid, path="/books/b1.pdf", filename="b1.pdf", format="pdf",
        size_bytes=1000, file_mtime=1.0, title="Book 10", author="Alice",
        publisher="Penguin", year=2010, isbn="9780140449136", pages=100,
        genre="Fiction", language="English", cover_path=None,
    )
    repo.upsert_book(
        folder_id=fid, path="/books/b2.epub", filename="b2.epub", format="epub",
        size_bytes=2000, file_mtime=2.0, title="Book 2", author="Bob",
        publisher="O'Reilly", year=2020, isbn="9781491957660", pages=200,
        genre="Tech", language="English", cover_path=None,
    )
    repo.upsert_book(
        folder_id=fid, path="/books/b3.pdf", filename="b3.pdf", format="pdf",
        size_bytes=3000, file_mtime=3.0, title="No Year Book", author="Charlie",
        publisher="Springer", year=None, isbn=None, pages=300,
        genre="SciFi", language="French", cover_path=None,
    )
    repo.upsert_book(
        folder_id=fid, path="/books/b4.mobi", filename="b4.mobi", format="mobi",
        size_bytes=4000, file_mtime=4.0, title="War and Peace", author="Leo Tolstoy",
        publisher=None, year=1869, isbn=None, pages=1200,
        genre="Classic", language="Russian", cover_path=None,
    )
    repo.upsert_book(
        folder_id=fid, path="/books/hindi.epub", filename="hindi.epub", format="epub",
        size_bytes=1500, file_mtime=5.0, title="युद्ध और शांति", author="टॉलस्टॉय",
        publisher="राजकमल", year=2015, isbn=None, pages=800,
        genre="Classic", language="Hindi", cover_path=None,
    )

    # Set statuses and ratings
    b_all = repo.list_books()
    id_map = {b.path: b.id for b in b_all}

    repo.set_status([id_map["/books/b1.pdf"]], "want")
    repo.set_status([id_map["/books/b2.epub"]], "reading")
    repo.set_status([id_map["/books/b4.mobi"]], "read")
    # b3 and hindi remain unset (NULL)

    repo.set_rating(id_map["/books/b1.pdf"], 4)
    repo.set_rating(id_map["/books/b2.epub"], 5)
    repo.set_rating(id_map["/books/b4.mobi"], 3)

    repo.record_open(id_map["/books/b2.epub"])

    yield repo, id_map
    db.close()


def test_query_search(seeded_repo):
    repo, id_map = seeded_repo

    # Basic search
    res = repo.query_books(LibraryQuery(search="Tolstoy"))
    assert len(res) == 1
    assert res[0].id == id_map["/books/b4.mobi"]

    # Search with prefix
    res = repo.query_books(LibraryQuery(search="Peng"))
    assert len(res) == 1
    assert res[0].id == id_map["/books/b1.pdf"]

    # Unicode search (Hindi)
    res_hindi = repo.query_books(LibraryQuery(search="युद्ध"))
    assert len(res_hindi) == 1
    assert res_hindi[0].id == id_map["/books/hindi.epub"]

    # Search with punctuation/special characters
    res_punct = repo.query_books(LibraryQuery(search="O'Reilly"))
    assert len(res_punct) == 1
    assert res_punct[0].id == id_map["/books/b2.epub"]


def test_query_statuses(seeded_repo):
    repo, id_map = seeded_repo

    # Filter by 'want'
    res_want = repo.query_books(LibraryQuery(statuses={"want"}))
    assert len(res_want) == 1
    assert res_want[0].id == id_map["/books/b1.pdf"]

    # Filter by 'none' (unset)
    res_none = repo.query_books(LibraryQuery(statuses={"none"}))
    assert len(res_none) == 2

    # Multiple statuses (OR)
    res_or = repo.query_books(LibraryQuery(statuses={"want", "reading"}))
    assert len(res_or) == 2


def test_query_formats_and_ratings(seeded_repo):
    repo, id_map = seeded_repo

    res_pdf = repo.query_books(LibraryQuery(formats={"pdf"}))
    assert len(res_pdf) == 2

    res_rated = repo.query_books(LibraryQuery(min_rating=4))
    assert len(res_rated) == 2
    for b in res_rated:
        assert b.rating >= 4


def test_query_shelves(seeded_repo):
    repo, id_map = seeded_repo

    res_cont = repo.query_books(LibraryQuery(shelf="continue"))
    assert len(res_cont) == 1
    assert res_cont[0].id == id_map["/books/b2.epub"]

    res_recent = repo.query_books(LibraryQuery(shelf="recent"))
    assert len(res_recent) == 5


def test_query_natural_sort_and_nulls_last(seeded_repo):
    repo, id_map = seeded_repo

    # Natural sort title: Book 2 should come before Book 10!
    res_title = repo.query_books(LibraryQuery(sort_field="title", sort_desc=False))
    titles = [b.title for b in res_title if b.title.startswith("Book ")]
    assert titles == ["Book 2", "Book 10"]

    # Sort year ASC: nulls last!
    res_year_asc = repo.query_books(LibraryQuery(sort_field="year", sort_desc=False))
    assert res_year_asc[-1].title == "No Year Book"  # year=None is at the end

    # Sort year DESC: nulls last!
    res_year_desc = repo.query_books(LibraryQuery(sort_field="year", sort_desc=True))
    assert res_year_desc[-1].title == "No Year Book"  # year=None is at the end


def test_facet_counts(seeded_repo):
    repo, _ = seeded_repo
    facets = repo.facet_counts("format", LibraryQuery())
    facet_dict = dict(facets)
    assert facet_dict.get("pdf") == 2
    assert facet_dict.get("epub") == 2
    assert facet_dict.get("mobi") == 1
