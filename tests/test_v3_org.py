"""
test_v3_org.py – Test Tags (Any/All, merge, FTS), Series (indexes, navigation), and Collections (manual & smart).
"""
import json
import sqlite3
from pathlib import Path

import pytest

from booklib.db.database import Database
from booklib.db.query import LibraryQuery
from booklib.db.repository import Repository


@pytest.fixture
def repo(tmp_path: Path):
    db = Database(tmp_path / "test_org.db")
    conn = db.connect()
    r = Repository(conn)
    fid = r.add_folder("C:/TestBooks")

    # Insert 3 test books
    r.upsert_book(
        folder_id=fid, path="C:/TestBooks/b1.epub", filename="b1.epub",
        format="epub", size_bytes=1000, file_mtime=1.0,
        title="Foundation", author="Isaac Asimov", publisher=None,
        year=1951, isbn=None, pages=250, genre="Sci-Fi", language="en",
        cover_path=None, series_name="Foundation", series_index=1.0,
    )
    r.upsert_book(
        folder_id=fid, path="C:/TestBooks/b2.epub", filename="b2.epub",
        format="epub", size_bytes=1000, file_mtime=1.0,
        title="Foundation and Empire", author="Isaac Asimov", publisher=None,
        year=1952, isbn=None, pages=247, genre="Sci-Fi", language="en",
        cover_path=None, series_name="Foundation", series_index=2.0,
    )
    r.upsert_book(
        folder_id=fid, path="C:/TestBooks/b3.pdf", filename="b3.pdf",
        format="pdf", size_bytes=1000, file_mtime=1.0,
        title="Python Deep Learning", author="Francois Chollet", publisher=None,
        year=2017, isbn=None, pages=384, genre="Programming", language="en",
        cover_path=None,
    )
    db.conn.commit()
    yield r
    db.close()


# ── Tags Tests ───────────────────────────────────────────────────────────────

def test_tags_crud_and_merge(repo: Repository):
    tid1 = repo.create_tag("python")
    # Case-insensitive uniqueness
    tid1_again = repo.create_tag("Python")
    assert tid1 == tid1_again

    tid2 = repo.create_tag("ml")
    tags = repo.list_tags()
    tag_names = [t["name"] for t in tags]
    assert "python" in tag_names
    assert "ml" in tag_names

    # Add tags to book 3
    repo.add_tag_to_books("python", [3])
    repo.add_tag_to_books("ml", [3])

    # Check tags_text
    b3 = repo.get_book_row(3)
    assert "python" in b3.tags_text
    assert "ml" in b3.tags_text

    # Merge tag 'ml' into 'python'
    repo.merge_tags(tid2, tid1)
    tags_after = repo.list_tags()
    assert len(tags_after) == 1
    assert tags_after[0]["name"] == "python"

    b3_after = repo.get_book_row(3)
    assert b3_after.tags_text == "python"


def test_tags_any_vs_all_query(repo: Repository):
    tid_sci = repo.create_tag("scifi")
    tid_classic = repo.create_tag("classic")

    # b1 gets scifi and classic
    repo.add_tag_to_books("scifi", [1])
    repo.add_tag_to_books("classic", [1])

    # b2 gets only scifi
    repo.add_tag_to_books("scifi", [2])

    # Query Any mode: {scifi, classic} -> b1 and b2
    q_any = LibraryQuery(tag_ids={tid_sci, tid_classic}, tag_mode="any")
    res_any = repo.query_books(q_any)
    ids_any = {b.id for b in res_any}
    assert ids_any == {1, 2}

    # Query All mode: {scifi, classic} -> b1 only!
    q_all = LibraryQuery(tag_ids={tid_sci, tid_classic}, tag_mode="all")
    res_all = repo.query_books(q_all)
    ids_all = {b.id for b in res_all}
    assert ids_all == {1}


# ── Series Tests ─────────────────────────────────────────────────────────────

def test_series_navigation_and_sorting(repo: Repository):
    series_list = repo.list_series()
    assert len(series_list) == 1
    s = series_list[0]
    assert s["name"] == "Foundation"
    assert s["book_count"] == 2

    # Neighbors for book 1 in series
    n1 = repo.get_series_neighbors(1, s["id"])
    assert n1["prev_id"] is None
    assert n1["next_id"] == 2

    # Neighbors for book 2
    n2 = repo.get_series_neighbors(2, s["id"])
    assert n2["prev_id"] == 1
    assert n2["next_id"] is None

    # Query sorted by series
    q = LibraryQuery(series_id=s["id"], sort_field="series")
    books = repo.query_books(q)
    assert len(books) == 2
    assert books[0].id == 1
    assert books[1].id == 2


# ── Collections Tests ────────────────────────────────────────────────────────

def test_manual_collection(repo: Repository):
    cid = repo.create_collection("Sci-Fi Shelf", kind="manual")
    repo.add_books_to_collection(cid, [1, 2])

    cols = repo.list_collections()
    assert len(cols) == 1
    assert cols[0]["name"] == "Sci-Fi Shelf"
    assert cols[0]["book_count"] == 2

    # Query by collection
    q = LibraryQuery(collection_id=cid)
    res = repo.query_books(q)
    assert len(res) == 2

    # Remove book from collection
    repo.remove_books_from_collection(cid, [1])
    res_after = repo.query_books(q)
    assert len(res_after) == 1
    assert res_after[0].id == 2


def test_smart_collection_serialization(repo: Repository):
    q = LibraryQuery(
        search="Python",
        formats={"pdf"},
        min_rating=4,
        incomplete=False,
    )
    data = q.to_dict()
    assert data["v"] == 1
    assert data["search"] == "Python"
    assert data["formats"] == ["pdf"]
    assert data["min_rating"] == 4

    # Add unknown future field to test forward compatibility
    data["unknown_future_field"] = "some_val"

    # Deserialize
    reloaded = LibraryQuery.from_dict(data)
    assert reloaded.search == "Python"
    assert reloaded.formats == {"pdf"}
    assert reloaded.min_rating == 4
    assert not hasattr(reloaded, "unknown_future_field")
