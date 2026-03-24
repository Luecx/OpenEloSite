from __future__ import annotations

import re
from pathlib import Path

from sqlalchemy import or_
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.models.opening_book import OpeningBook
from app.db.models.rating_list import RatingList
from app.services.syzygy_service import normalize_syzygy_probe_limit
from app.services.storage_service import sha256_for_file


def slugify(value: str) -> str:
    value = value.lower().strip()
    value = re.sub(r"[^a-z0-9]+", "-", value)
    return value.strip("-") or "rating-list"


def list_books(db: Session, q: str = "") -> list[OpeningBook]:
    query = select(OpeningBook).order_by(OpeningBook.created_at.desc())
    if q.strip():
        pattern = f"%{q.strip()}%"
        query = query.where(
            or_(
                OpeningBook.name.ilike(pattern),
                OpeningBook.description.ilike(pattern),
                OpeningBook.file_name.ilike(pattern),
            )
        )
    return list(db.scalars(query))


def get_book(db: Session, book_id: int) -> OpeningBook | None:
    return db.get(OpeningBook, book_id)


def get_book_by_name(db: Session, name: str) -> OpeningBook | None:
    return db.scalar(select(OpeningBook).where(OpeningBook.name == name.strip()))


def create_book(
    db: Session,
    name: str,
    description: str,
    file_name: str,
    file_path: str,
    content_hash: str,
    format_name: str,
    uploaded_by_user_id: int,
) -> OpeningBook:
    record = OpeningBook(
        name=name.strip(),
        description=description.strip() or None,
        file_name=file_name,
        file_path=file_path,
        content_hash=content_hash.strip() or None,
        format_name=format_name.strip() or "pgn",
        uploaded_by_user_id=uploaded_by_user_id,
    )
    db.add(record)
    db.commit()
    db.refresh(record)
    return record


def update_book(
    db: Session,
    book: OpeningBook,
    name: str,
    description: str,
    format_name: str,
) -> OpeningBook:
    book.name = name.strip()
    book.description = description.strip() or None
    book.format_name = format_name.strip() or "pgn"
    db.commit()
    db.refresh(book)
    return book


def delete_book(db: Session, book: OpeningBook) -> None:
    book_path = Path(book.file_path)
    connection = db.get_bind().raw_connection()
    try:
        cursor = connection.cursor()
        cursor.execute("PRAGMA foreign_keys=OFF")
        cursor.execute("UPDATE rating_lists SET opening_book_id = NULL WHERE opening_book_id = ?", (book.id,))
        cursor.execute("DELETE FROM opening_books WHERE id = ?", (book.id,))
        connection.commit()
        cursor.execute("PRAGMA foreign_keys=ON")
        db.expire_all()
    except Exception:
        connection.rollback()
        raise
    finally:
        connection.close()
    if book_path.exists():
        book_path.unlink(missing_ok=True)


def ensure_book_hash(db: Session, book: OpeningBook) -> OpeningBook:
    if book.content_hash:
        return book
    book_path = Path(book.file_path)
    if not book_path.exists():
        return book
    book.content_hash = sha256_for_file(book_path)
    db.commit()
    db.refresh(book)
    return book


def list_rating_lists(db: Session, q: str = "") -> list[RatingList]:
    query = select(RatingList).order_by(RatingList.name.asc())
    if q.strip():
        pattern = f"%{q.strip()}%"
        query = query.where(
            or_(
                RatingList.name.ilike(pattern),
                RatingList.description.ilike(pattern),
            )
        )
    return list(db.scalars(query))


def get_rating_list(db: Session, rating_list_id: int) -> RatingList | None:
    return db.get(RatingList, rating_list_id)


def get_rating_list_by_name(db: Session, name: str) -> RatingList | None:
    return db.scalar(select(RatingList).where(RatingList.name == name.strip()))


def get_rating_list_by_slug(db: Session, slug: str) -> RatingList | None:
    return db.scalar(select(RatingList).where(RatingList.slug == slug))


def create_rating_list(
    db: Session,
    name: str,
    description: str,
    time_control_base_seconds: int,
    time_control_increment_seconds: int,
    time_control_moves: int | None,
    threads_per_engine: int,
    hash_per_engine: int,
    syzygy_probe_limit: int | str | None,
    opening_book_id: int | None,
    anchor_engine_version_id: int | None,
    anchor_rating: float | None,
) -> RatingList:
    record = RatingList(
        name=name.strip(),
        slug=slugify(name),
        description=description.strip() or None,
        time_control_base_seconds=max(1, int(time_control_base_seconds)),
        time_control_increment_seconds=max(0, int(time_control_increment_seconds)),
        time_control_moves=time_control_moves,
        threads_per_engine=max(1, int(threads_per_engine)),
        hash_per_engine=max(1, int(hash_per_engine)),
        syzygy_probe_limit=normalize_syzygy_probe_limit(syzygy_probe_limit),
        opening_book_id=opening_book_id,
        anchor_engine_version_id=anchor_engine_version_id,
        anchor_rating=anchor_rating,
    )
    db.add(record)
    db.commit()
    db.refresh(record)
    return record


def update_rating_list(
    db: Session,
    rating_list: RatingList,
    name: str,
    description: str,
    time_control_base_seconds: int,
    time_control_increment_seconds: int,
    time_control_moves: int | None,
    threads_per_engine: int,
    hash_per_engine: int,
    syzygy_probe_limit: int | str | None,
    opening_book_id: int | None,
    anchor_engine_version_id: int | None,
    anchor_rating: float | None,
) -> RatingList:
    rating_list.name = name.strip()
    rating_list.slug = slugify(name)
    rating_list.description = description.strip() or None
    rating_list.time_control_base_seconds = max(1, int(time_control_base_seconds))
    rating_list.time_control_increment_seconds = max(0, int(time_control_increment_seconds))
    rating_list.time_control_moves = time_control_moves
    rating_list.threads_per_engine = max(1, int(threads_per_engine))
    rating_list.hash_per_engine = max(1, int(hash_per_engine))
    rating_list.syzygy_probe_limit = normalize_syzygy_probe_limit(syzygy_probe_limit)
    rating_list.opening_book_id = opening_book_id
    rating_list.anchor_engine_version_id = anchor_engine_version_id
    rating_list.anchor_rating = anchor_rating
    db.commit()
    db.refresh(rating_list)
    return rating_list


def delete_rating_list(db: Session, rating_list: RatingList) -> None:
    connection = db.get_bind().raw_connection()
    try:
        cursor = connection.cursor()
        cursor.execute("PRAGMA foreign_keys=OFF")
        cursor.execute("DELETE FROM engine_version_rating_lists WHERE rating_list_id = ?", (rating_list.id,))
        cursor.execute(
            "DELETE FROM match_jobs WHERE match_id IN (SELECT id FROM matches WHERE rating_list_id = ?)",
            (rating_list.id,),
        )
        cursor.execute("DELETE FROM matches WHERE rating_list_id = ?", (rating_list.id,))
        cursor.execute("DELETE FROM leaderboard_entries WHERE rating_list_id = ?", (rating_list.id,))
        cursor.execute("DELETE FROM rating_lists WHERE id = ?", (rating_list.id,))
        connection.commit()
        cursor.execute("PRAGMA foreign_keys=ON")
        db.expire_all()
    except Exception:
        connection.rollback()
        raise
    finally:
        connection.close()
