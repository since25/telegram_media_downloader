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
   ordered message/caption snapshots, and current package `queued` summaries.
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

## Download And Result Semantics

`run_download_batch` refetches each package's exact snapshotted message IDs under a
download-priority Telegram permit. It retains saved package titles, boundaries,
revisions, item ordering, and captions for recommended-C naming. Packages run in
ascending start-message order.

The serial downloader owns the parent task lifecycle once for the whole batch. Package
callbacks receive only that package's expected IDs and message results. Package results
retain the immutable snapshot order even when an interior ID is absent. Package results
distinguish:

- `completed`, including a verified complete-local-file skip;
- `upload_failed`;
- `failed`, including a package-scoped refetch error;
- `not_found` for an exact ID absent from a successful refetch;
- `cancelled` for interrupted or unstarted package work.

Historical `has_successful_attempt` is only promoted on success and is never cleared by
a failed explicit redownload. A user stop that returns normally still overrides the
parent Web task to `cancelled` and cancels current or unstarted package attempts.

Persisted download errors are allow-listed stable codes such as
`telegram_refetch_failed`, `download_failed`, `callback_failed`, `upload_failed`, and
`cancelled`. Raw Telegram, downloader, and callback exception text is logged
server-side and is not written to channel download rows or Web task errors.

## Recovery And Reconciliation

Startup dispatches `pending_dispatch` rows before reconciliation. Reconciliation only
uses durable Web task/file evidence. A completed package requires every expected ID to
have a downloaded or uploaded `FileSnapshot`; ambiguous skips and missing evidence are
failed conservatively. Both `completed` and `completed_with_errors` parent tasks are
evaluated package by package, so proven packages stay completed while sibling packages
fail. Cancelled Web tasks cancel unfinished packages. Missing or failed Web tasks fail
unfinished packages. Already completed package attempts are not regressed.
