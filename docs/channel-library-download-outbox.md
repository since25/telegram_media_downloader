# Channel Library Download Outbox

Channel-library download batches use a persistent outbox/saga across two independent
SQLite databases. The channel database and `web_tasks.sqlite3` are never described or
treated as one atomic transaction.

## Commit And Dispatch Order

1. `ChannelLibraryStore.create_download_batch` opens `BEGIN IMMEDIATE` in the channel
   database. It returns an existing `(library_id, idempotency_key)` batch before doing
   new validation.
2. A new batch requires a `ready` or `partial` library, current stable selected
   revisions, no package in another active batch, and explicit `redownload` when a
   package has historical success. Active membership is determined from nonterminal
   batch-package attempt rows inside the same write transaction, not from the mutable
   package summary updated by later indexing.
3. The same transaction writes the batch, package title/boundary/revision snapshots,
   the channel title used for task display and recommended-C naming, ordered
   message/caption snapshots, and current package `queued` summaries. Later channel
   renames cannot change the batch task identity or download naming context.
4. Only after that transaction commits, the service idempotently ensures the
   deterministic `channel-batch-<uuid>` task in `web_tasks.sqlite3`.
5. After the Web task write succeeds, the channel batch is marked `dispatched`.

A crash before the channel commit leaves neither record. A crash after the channel
commit leaves `pending_dispatch`. A crash after the Web task write can replay the same
task ID and then mark the same batch dispatched. `dispatch_pending_batches` is safe to
run at startup. An existing deterministic task must match the expected source, type,
chat, title, and total count whether it is active or terminal. An identity mismatch
leaves the batch `pending_dispatch`, records only `task_identity_conflict`, and never
marks the batch dispatched.

Schema version 3 adds the immutable batch `channel_title`. Existing databases add the
column idempotently and backfill older batches from the current library title once;
new batches always capture it inside their creation transaction.

Schema version 4 adds `channel_package_auto_download_triggers`. An automatic title rule
creates an exact one-package batch without modifying the user's persisted Web selection.
The trigger row stores the rule key, matched keywords, package revision, and batch ID in
the same channel-database transaction, so the same rule and package revision cannot
create another automatic batch after a restart or later scan.

Schema version 5 snapshots `known_total_size` and `unknown_size_count` on each
batch-package attempt. This keeps disk admission bound to the immutable message snapshot,
not to a package's later index revision. Existing attempts are backfilled from their
snapshotted message IDs and stored media metadata.

Schema version 6 adds database-owned keyword monitor groups, normalized terms, and
per-group trigger history. The older schema-version-4 trigger table remains additive
compatibility data but is no longer used by the runtime. Keyword-monitor history rows are
written in the same transaction as an exact-package batch. Multiple groups may point to
the same batch/package revision, while each group/package revision remains unique.

The top-level package interface aggregates rows across channel libraries. Package
identity remains the database package ID plus its `library_id`; channel title and
Telegram `chat_id` are source metadata, not package identity based on title. Aggregate
manual submission fans selected packages out into one immutable batch per source library.

## Download And Result Semantics

`run_download_batch` refetches each package's exact snapshotted message IDs under a
download-priority Telegram permit. It retains saved package titles, boundaries,
revisions, item ordering, and captions for recommended-C naming. Packages run in
ascending start-message order.

Before a package transitions to `downloading`, it acquires a FIFO disk reservation equal
to its full known size. The reservation is retained through download, upload, and local
cleanup. A successful package releases it at its callback terminal state; an upload
failure retains it until upload retry succeeds or explicit cleanup completes. The default
minimum remaining free space is 3 GiB (`channel_library.min_free_disk_bytes`). A package
with an unknown media size is not guessed or started: it is marked `failed` with
`unknown_package_size`, while later packages continue.

Cloud upload failures retain their local file and stay visible through
`GET /api/tasks/<task_id>/upload-retries`. `POST /api/tasks/<task_id>/retry` schedules an
upload-only retry for a channel-library task. It never recreates a download task or fetches
Telegram media. A missing retained file remains `upload_source_missing` for an explicit
user cleanup or a later manual download, rather than being silently downloaded again.
`POST /api/tasks/<task_id>/upload-retries/cleanup` explicitly deletes retained sources
under the configured `save_path`, records `upload_source_removed`, and releases the
in-process reservation for the affected package.

The serial downloader owns the parent task lifecycle once for the whole batch. Package
callbacks receive only that package's expected IDs and message results. Package results
retain the immutable snapshot order even when an interior ID is absent. Package results
distinguish:

- `completed`, including a verified complete-local-file skip;
- `completed_with_errors` when at least one snapshotted file completed and one
  sibling file failed or was unavailable; remaining files are still processed;
- `upload_failed`;
- `failed`, including a package-scoped refetch error;
- `not_found` for an exact ID absent from a successful refetch;
- `cancelled` for interrupted or unstarted package work.

Historical `has_successful_attempt` is only promoted on success and is never cleared by
a failed explicit redownload. A user stop that returns normally still overrides the
parent Web task to `cancelled` and cancels current or unstarted package attempts.
Cancellation while waiting for the Telegram gate or inside the exact-ID refetch follows
the same cleanup path after the gate intent is released, so no task or package remains
queued/downloading.

Persisted download errors are allow-listed stable codes such as
`telegram_refetch_failed`, `download_failed`, `callback_failed`, `upload_failed`, and
`cancelled`. Raw Telegram, downloader, and callback exception text is logged
server-side and is not written to channel download rows or Web task errors.

## Recovery And Reconciliation

Startup dispatches `pending_dispatch` rows before reconciliation. Reconciliation only
uses durable Web task/file evidence. A completed package requires every expected ID to
have a downloaded or uploaded `FileSnapshot`. A package with both completed evidence
and failed/missing evidence is `completed_with_errors`; a package without any completed
evidence remains failed conservatively. Both `completed` and `completed_with_errors`
parent tasks are evaluated package by package, so proven packages stay completed while
partial packages retain their error result. Cancelled Web tasks cancel unfinished
packages. Missing or failed Web tasks fail unfinished packages. Already completed
package attempts are not regressed.

## Runner Ownership And Restart

One process-local runner claim keyed by channel database path and batch ID covers the
entire preparation, refetch, callback, and download lifecycle. A concurrent runner in
another service instance in the same process fails before Telegram refetch or package
callbacks. This is deliberately not a multi-process lease.

After process restart the in-memory claim set is empty. Before rescheduling, startup
reconciliation consumes terminal Web task evidence; a new runner then atomically resets
any remaining stale `downloading` batch/package attempts and current package summaries
to `queued`. A package-start transition only accepts `queued`; zero updated rows are a
state conflict rather than an idempotent success.
