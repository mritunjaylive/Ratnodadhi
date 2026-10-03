"""
epub.py – EPUB metadata and cover extractor.

Supports EPUB 2 and EPUB 3. Uses only standard-library modules
(zipfile + xml.etree.ElementTree).
"""
from __future__ import annotations

import logging
import re
import zipfile
import xml.etree.ElementTree as ET
from pathlib import PurePosixPath

from booklib.metadata.base import BookMeta
from booklib.metadata.filename import validate_isbn, validate_year

logger = logging.getLogger(__name__)

_NS_DC = "http://purl.org/dc/elements/1.1/"
_NS_OPF = "http://www.idpf.org/2007/opf"
_NS_CONTAINER = "urn:oasis:names:tc:opendocument:xmlns:container"


def _q(ns: str, tag: str) -> str:
    return f"{{{ns}}}{tag}"


def extract(path: str) -> BookMeta:
    meta = BookMeta()
    try:
        with zipfile.ZipFile(path, "r") as zf:
            namelist = set(zf.namelist())

            # ── Step 1: find the OPF file ─────────────────────────────────────
            container_path = "META-INF/container.xml"
            if container_path not in namelist:
                return meta
            container = ET.fromstring(zf.read(container_path))
            opf_path = None
            for rf in container.iter(_q(_NS_CONTAINER, "rootfile")):
                opf_path = rf.get("full-path")
                break
            if not opf_path or opf_path not in namelist:
                return meta

            opf_dir = str(PurePosixPath(opf_path).parent)
            if opf_dir == ".":
                opf_dir = ""

            opf = ET.fromstring(zf.read(opf_path))

            # ── Step 2: Dublin Core metadata ──────────────────────────────────
            meta.title = _dc_text(opf, "title")
            meta.author = _dc_text(opf, "creator")
            meta.publisher = _dc_text(opf, "publisher")
            meta.language = _dc_text(opf, "language")
            meta.genre = _dc_text(opf, "subject")
            meta.year = validate_year(_dc_text(opf, "date"))
            meta.description = _dc_text(opf, "description")

            # ISBN from dc:identifier
            for ident in opf.iter(_q(_NS_DC, "identifier")):
                validated = validate_isbn(ident.text)
                if validated:
                    meta.isbn = validated
                    break

            # ── Step 2b: Series metadata (Calibre + EPUB 3) ───────────────────
            _extract_series(opf, meta)

            # ── Step 3: build manifest id → href map ──────────────────────────
            manifest: dict[str, str] = {}
            media_types: dict[str, str] = {}
            for item in opf.iter(_q(_NS_OPF, "item")):
                item_id = item.get("id", "")
                href = item.get("href", "")
                mt = item.get("media-type", "")
                manifest[item_id] = href
                media_types[item_id] = mt

            # ── Step 4: find cover image ──────────────────────────────────────
            cover_href = _find_cover(opf, manifest, media_types, opf_dir)
            if cover_href:
                zip_path = (
                    f"{opf_dir}/{cover_href}".lstrip("/")
                    if opf_dir
                    else cover_href
                )
                if zip_path in namelist:
                    meta.cover_bytes = zf.read(zip_path)

    except (zipfile.BadZipFile, KeyError, ET.ParseError, OSError) as exc:
        logger.warning("EPUB extraction failed for %s: %s", path, exc)
    return meta


def _dc_text(opf: ET.Element, tag: str) -> str | None:
    el = opf.find(f".//{_q(_NS_DC, tag)}")
    return el.text.strip() if el is not None and el.text else None


def _extract_series(opf: ET.Element, meta: BookMeta) -> None:
    """Extract series name and index from Calibre or EPUB 3 meta tags."""
    # 1. Calibre style
    for el in opf.iter(_q(_NS_OPF, "meta")):
        name_attr = el.get("name") or el.get("property")
        if name_attr == "calibre:series":
            meta.series = (el.get("content") or el.text or "").strip() or None
        elif name_attr == "calibre:series_index":
            try:
                raw = el.get("content") or el.text or ""
                meta.series_index = float(raw.strip())
            except (ValueError, TypeError):
                pass

    if meta.series:
        return

    # 2. EPUB 3 style: <meta property="belongs-to-collection" id="c01">Series Name</meta>
    series_id = None
    for el in opf.iter():
        if el.tag.endswith("meta") and el.get("property") == "belongs-to-collection":
            meta.series = (el.text or "").strip() or None
            series_id = el.get("id")
            break

    if series_id:
        for el in opf.iter():
            if el.tag.endswith("meta") and el.get("refines") == f"#{series_id}":
                if el.get("property") == "group-position":
                    try:
                        meta.series_index = float((el.text or "").strip())
                    except (ValueError, TypeError):
                        pass


def _find_cover(
    opf: ET.Element,
    manifest: dict[str, str],
    media_types: dict[str, str],
    opf_dir: str,
) -> str | None:
    _IMAGE_TYPES = {"image/jpeg", "image/png", "image/gif", "image/webp"}

    # EPUB 3: item with properties="cover-image"
    for item in opf.iter(_q(_NS_OPF, "item")):
        if "cover-image" in (item.get("properties") or ""):
            return item.get("href")

    # EPUB 2: <meta name="cover" content="id">
    for meta_el in opf.iter(_q(_NS_OPF, "meta")):
        if meta_el.get("name") == "cover":
            cover_id = meta_el.get("content", "")
            if cover_id in manifest:
                return manifest[cover_id]

    # Fallback: any image whose id or href contains "cover"
    for item_id, href in manifest.items():
        if "cover" in item_id.lower() or "cover" in href.lower():
            if media_types.get(item_id, "") in _IMAGE_TYPES:
                return href

    return None
