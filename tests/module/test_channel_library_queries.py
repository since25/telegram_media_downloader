"""Filtered query, keyset pagination, and persistent selection tests."""

import base64
import datetime
import json

import pytest

from module.channel_library_store import (
    ChannelLibraryStore,
    PackageFilter,
)


UTC = datetime.timezone.utc


@pytest.fixture
def store(tmp_path):
    result = ChannelLibraryStore(tmp_path / "channel-library.sqlite3")
    result.initialize()
    return result


@pytest.fixture
def library(store):
    result, _ = store.create_or_get_library(
        -1001,
        "channel",
        "query-demo",
        "Query Demo",
        "https://t.me/query_demo",
    )
    return result


def insert_package(
    store,
    library_id,
    start_message_id,
    *,
    end_message_id=None,
    title=None,
    published_at="2026-07-16T00:00:00+00:00",
    boundary_status="stable",
    media_count=1,
    known_total_size=100,
    unknown_size_count=0,
    download_status="never",
):
    end_message_id = end_message_id or start_message_id
    title = title or f"Package {start_message_id}"
    with store.connect() as connection:
        connection.execute("BEGIN IMMEDIATE")
        revision = connection.execute(
            "SELECT index_revision + 1 FROM channel_libraries WHERE id = ?",
            (library_id,),
        ).fetchone()[0]
        package_id = connection.execute(
            """
            INSERT INTO channel_packages (
                library_id, start_message_id, end_message_id, title,
                published_at, boundary_status, media_count,
                known_total_size, unknown_size_count,
                current_download_status, index_revision, created_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                library_id,
                start_message_id,
                end_message_id,
                title,
                published_at,
                boundary_status,
                media_count,
                known_total_size,
                unknown_size_count,
                download_status,
                revision,
                float(revision),
                float(revision),
            ),
        ).lastrowid
        connection.execute(
            """
            UPDATE channel_libraries
            SET index_revision = ?, updated_at = ?
            WHERE id = ?
            """,
            (revision, float(revision), library_id),
        )
    return package_id


def insert_package_item(store, library_id, package_id, message_id, ordinal=0):
    with store.connect() as connection:
        connection.execute(
            """
            INSERT INTO channel_media_messages (
                library_id, message_id, message_date, media_type, caption,
                file_name, file_size, raw_fingerprint, first_seen_at, updated_at
            ) VALUES (?, ?, ?, 'video', ?, ?, ?, ?, 1, 1)
            """,
            (
                library_id,
                message_id,
                "2026-07-16T00:00:00+00:00",
                f"Caption {message_id}",
                f"video-{message_id}.mp4",
                message_id * 10,
                f"fingerprint-{message_id}",
            ),
        )
        connection.execute(
            """
            INSERT INTO channel_package_items (
                library_id, package_id, message_id, ordinal, media_type,
                caption_for_naming, original_caption, inherited_caption
            ) VALUES (?, ?, ?, ?, 'video', ?, ?, 0)
            """,
            (
                library_id,
                package_id,
                message_id,
                ordinal,
                f"Name {message_id}",
                f"Caption {message_id}",
            ),
        )


def package_ids(page):
    return [item["id"] for item in page.items]


def encode_cursor(payload):
    raw = json.dumps(payload, separators=(",", ":")).encode("ascii")
    return base64.urlsafe_b64encode(raw).decode("ascii").rstrip("=")


def test_title_filter_uses_normalized_unicode_literal_substring(store, library):
    full_width = insert_package(
        store, library["id"], 10, title="Ｆｏｏ CAFE\u0301 Lesson"
    )
    insert_package(store, library["id"], 20, title="Other")

    assert package_ids(
        store.list_packages(library["id"], PackageFilter(q="foo café"))
    ) == [full_width]
    assert store.list_packages(
        library["id"], PackageFilter(q="' OR 1=1 --")
    ).items == []


def test_date_filter_is_exact_utc_half_open_range(store, library):
    before = insert_package(
        store,
        library["id"],
        10,
        published_at="2026-07-15T23:59:59+00:00",
    )
    at_from = insert_package(
        store,
        library["id"],
        20,
        published_at="2026-07-16T00:00:00+00:00",
    )
    inside = insert_package(
        store,
        library["id"],
        30,
        published_at="2026-07-16T23:59:59+00:00",
    )
    at_to = insert_package(
        store,
        library["id"],
        40,
        published_at="2026-07-17T00:00:00+00:00",
    )

    page = store.list_packages(
        library["id"],
        PackageFilter(
            date_from=datetime.datetime(2026, 7, 16, tzinfo=UTC),
            date_to="2026-07-17T08:00:00+08:00",
        ),
    )

    assert package_ids(page) == [inside, at_from]
    assert before not in package_ids(page)
    assert at_to not in package_ids(page)


def test_message_range_counts_and_download_status_filters_are_exact(store, library):
    matching = insert_package(
        store,
        library["id"],
        10,
        end_message_id=20,
        media_count=3,
        download_status="outdated",
    )
    insert_package(
        store,
        library["id"],
        30,
        end_message_id=35,
        media_count=4,
        download_status="completed",
    )

    page = store.list_packages(
        library["id"],
        PackageFilter(
            message_id_min=20,
            message_id_max=25,
            media_count_min=3,
            media_count_max=3,
            download_status="outdated",
        ),
    )

    assert package_ids(page) == [matching]


def test_size_bounds_are_inclusive_and_unknown_size_requires_opt_in(store, library):
    exact = insert_package(
        store,
        library["id"],
        10,
        known_total_size=100,
        unknown_size_count=0,
    )
    unknown = insert_package(
        store,
        library["id"],
        20,
        known_total_size=100,
        unknown_size_count=1,
    )

    default_page = store.list_packages(
        library["id"], PackageFilter(size_min=100, size_max=100)
    )
    opted_in_page = store.list_packages(
        library["id"],
        PackageFilter(size_min=100, size_max=100, include_unknown_size=True),
    )

    assert package_ids(default_page) == [exact]
    assert package_ids(opted_in_page) == [unknown, exact]
    assert opted_in_page.items[0]["size_is_exact"] is False
    assert opted_in_page.items[1]["size_is_exact"] is True


def test_package_keyset_is_capped_opaque_and_rejects_malformed_shapes(store, library):
    for message_id in range(1, 206):
        insert_package(store, library["id"], message_id)

    first = store.list_packages(library["id"], PackageFilter(), limit=999)
    second = store.list_packages(
        library["id"], PackageFilter(), cursor=first.next_cursor, limit=999
    )

    assert len(first.items) == 200
    assert len(second.items) == 5
    assert not (set(package_ids(first)) & set(package_ids(second)))
    for bad_cursor in (
        "not-base64!",
        "eyJzdGFydF9tZXNzYWdlX2lkIjoxfQ==",
        "eyJzdGFydF9tZXNzYWdlX2lkIjp0cnVlLCJpZCI6MX0=",
        "eyJzdGFydF9tZXNzYWdlX2lkIjoxLCJpZCI6MSwiZXh0cmEiOjF9",
    ):
        with pytest.raises(ValueError, match="cursor"):
            store.list_packages(
                library["id"], PackageFilter(), cursor=bad_cursor, limit=2
            )


@pytest.mark.parametrize(
    "payload",
    [
        {"start_message_id": 2**63, "id": 1},
        {"start_message_id": 1, "id": 2**63},
    ],
)
def test_package_cursor_rejects_integers_outside_sqlite_range(
    store, library, payload
):
    with pytest.raises(ValueError, match="cursor"):
        store.list_packages(
            library["id"],
            PackageFilter(),
            cursor=encode_cursor(payload),
            limit=2,
        )


def test_package_cursor_accepts_sqlite_max_integer(store, library):
    package_id = insert_package(store, library["id"], 10)
    cursor = encode_cursor(
        {"start_message_id": 2**63 - 1, "id": 2**63 - 1}
    )

    page = store.list_packages(
        library["id"], PackageFilter(), cursor=cursor, limit=2
    )

    assert package_ids(page) == [package_id]


def test_package_keyset_has_no_duplicates_when_newer_package_is_inserted(store, library):
    original_ids = [
        insert_package(store, library["id"], message_id)
        for message_id in (10, 20, 30, 40)
    ]
    first = store.list_packages(library["id"], PackageFilter(), limit=2)

    inserted = insert_package(store, library["id"], 999)
    second = store.list_packages(
        library["id"], PackageFilter(), cursor=first.next_cursor, limit=2
    )

    assert not (set(package_ids(first)) & set(package_ids(second)))
    assert set(package_ids(first) + package_ids(second)) == set(original_ids)
    assert inserted not in package_ids(second)
    assert second.library_revision > first.library_revision


def test_list_libraries_and_package_items_use_keyset_pages(store, library):
    package_id = insert_package(store, library["id"], 10, end_message_id=11)
    insert_package_item(store, library["id"], package_id, 10, ordinal=0)
    insert_package_item(store, library["id"], package_id, 11, ordinal=1)

    libraries = store.list_libraries(limit=1)
    first = store.list_package_items(library["id"], package_id, limit=1)
    second = store.list_package_items(
        library["id"], package_id, cursor=first.next_cursor, limit=1
    )

    assert [row["id"] for row in libraries.items] == [library["id"]]
    assert first.items[0]["message_id"] == 10
    assert first.items[0]["file_name"] == "video-10.mp4"
    assert second.items[0]["message_id"] == 11
    assert second.library_revision == first.library_revision


def test_select_filtered_selects_all_pages_and_skips_non_stable(store, library):
    stable_ids = [
        insert_package(store, library["id"], message_id, title="Course Match")
        for message_id in range(1, 206)
    ]
    insert_package(
        store,
        library["id"],
        300,
        title="Course Match",
        boundary_status="provisional",
    )
    insert_package(
        store,
        library["id"],
        301,
        title="Course Match",
        boundary_status="uncertain",
    )
    insert_package(
        store,
        library["id"],
        302,
        title="Course Match",
        boundary_status="superseded",
    )

    result = store.select_filtered(
        library["id"], PackageFilter(q="course match"), now=500.0
    )
    reopened = ChannelLibraryStore(store.path)
    summary = reopened.selection_summary(library["id"])

    assert result == {"selected_count": 205, "skipped_count": 2}
    assert summary["selected_count"] == 205
    assert summary["media_count"] == 205
    assert summary["invalidated_count"] == 0
    with reopened.connect() as connection:
        selected_ids = {
            row[0]
            for row in connection.execute(
                """
                SELECT package_id FROM channel_package_selections
                WHERE library_id = ? AND selected = 1
                """,
                (library["id"],),
            )
        }
    assert selected_ids == set(stable_ids)


def test_set_clear_selection_and_revision_invalidation_are_distinguished(store, library):
    package_id = insert_package(
        store,
        library["id"],
        10,
        media_count=3,
        known_total_size=500,
        unknown_size_count=1,
    )
    selected = store.set_package_selected(
        library["id"], package_id, True, now=10.0
    )

    assert selected["selected"] is True
    assert store.selection_summary(library["id"]) == {
        "selected_count": 1,
        "media_count": 3,
        "known_total_size": 500,
        "unknown_size_count": 1,
        "size_is_exact": False,
        "invalidated_count": 0,
        "invalidations": [],
    }

    with store.connect() as connection:
        connection.execute(
            """
            UPDATE channel_packages
            SET index_revision = index_revision + 1
            WHERE library_id = ? AND id = ?
            """,
            (library["id"], package_id),
        )
    invalidated = store.selection_summary(library["id"])

    assert invalidated["selected_count"] == 0
    assert invalidated["invalidated_count"] == 1
    assert invalidated["invalidations"] == [
        {"package_id": package_id, "reason": "package_revision_changed"}
    ]
    assert store.clear_selection(library["id"]) == 1
    assert store.selection_summary(library["id"])["invalidated_count"] == 0


def test_non_stable_package_cannot_be_selected_individually(store, library):
    package_id = insert_package(
        store,
        library["id"],
        10,
        boundary_status="provisional",
    )

    with pytest.raises(ValueError, match="not stable"):
        store.set_package_selected(library["id"], package_id, True)


@pytest.mark.parametrize(
    "package_filter",
    [
        PackageFilter(date_from="2026-07-17", date_to="2026-07-16"),
        PackageFilter(message_id_min=20, message_id_max=10),
        PackageFilter(media_count_min=2, media_count_max=1),
        PackageFilter(size_min=2, size_max=1),
        PackageFilter(download_status="anything"),
    ],
)
def test_invalid_filter_boundaries_are_rejected(store, library, package_filter):
    with pytest.raises(ValueError):
        store.list_packages(library["id"], package_filter)
