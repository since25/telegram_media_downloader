"""Coordinate Telegram work with download-priority access."""

import asyncio
from contextlib import asynccontextmanager
from typing import AsyncIterator, Optional


class ActivityPermit:
    """A release-once permit for one active scan."""

    def __init__(self, gate: "TelegramActivityGate") -> None:
        self._gate = gate
        self._released = False

    def release(self) -> None:
        if self._released:
            return
        self._released = True
        self._gate._release_scan()


class DownloadIntent:
    """A queued download claim that becomes its worker permit when activated."""

    _WAITING = "waiting"
    _ACTIVE = "active"
    _RELEASED = "released"

    def __init__(self, gate: "TelegramActivityGate") -> None:
        self._gate = gate
        self._state = self._WAITING
        self._release_complete: asyncio.Future[None] = (
            asyncio.get_running_loop().create_future()
        )

    async def activate(self) -> "DownloadIntent":
        """Wait for the active scan, then convert this intent to active work."""

        return await self._gate._activate_download(self)

    def cancel(self) -> None:
        """Release an intent removed before work starts."""

        self._gate._release_download(self)

    def release(self) -> None:
        """Release active download work, or cancel it if it never activated."""

        self._gate._release_download(self)

    async def release_and_wait(self) -> None:
        """Release once and wait until the gate counters are updated."""

        self.release()
        await asyncio.shield(self._release_complete)


class TelegramActivityGate:
    """Prefer queued downloads while allowing downloads to run concurrently."""

    def __init__(self) -> None:
        self._condition = asyncio.Condition()
        self._owner_loop: Optional[asyncio.AbstractEventLoop] = None
        self._waiting_downloads = 0
        self._active_downloads = 0
        self._scan_active = False

    @property
    def owner_loop(self) -> Optional[asyncio.AbstractEventLoop]:
        """Return the event loop that first acquired this gate."""

        return self._owner_loop

    def _bind_owner_loop(self) -> asyncio.AbstractEventLoop:
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError as error:
            raise RuntimeError(
                "TelegramActivityGate operations require a running event loop"
            ) from error
        if self._owner_loop is None:
            self._owner_loop = loop
        elif self._owner_loop is not loop:
            raise RuntimeError(
                "TelegramActivityGate cannot be acquired from a second event loop"
            )
        return loop

    async def register_download_intent(self) -> DownloadIntent:
        """Register download priority before its queue item is enqueued."""

        self._bind_owner_loop()
        async with self._condition:
            intent = DownloadIntent(self)
            self._waiting_downloads += 1
            self._condition.notify_all()
            return intent

    async def acquire_download(self) -> DownloadIntent:
        """Register and activate immediate download or preview work."""

        intent = await self.register_download_intent()
        try:
            return await intent.activate()
        except BaseException:
            intent.cancel()
            raise

    async def _activate_download(self, intent: DownloadIntent) -> DownloadIntent:
        self._bind_owner_loop()
        async with self._condition:
            if intent._gate is not self:
                raise RuntimeError("download intent belongs to a different gate")
            if intent._state == DownloadIntent._ACTIVE:
                return intent
            if intent._state != DownloadIntent._WAITING:
                raise RuntimeError("download intent is no longer pending")

            try:
                await self._condition.wait_for(
                    lambda: not self._scan_active
                    or intent._state != DownloadIntent._WAITING
                )
            except BaseException:
                if intent._state == DownloadIntent._WAITING:
                    self._waiting_downloads -= 1
                    intent._state = DownloadIntent._RELEASED
                    self._condition.notify_all()
                    if not intent._release_complete.done():
                        intent._release_complete.set_result(None)
                raise

            if intent._state != DownloadIntent._WAITING:
                raise RuntimeError("download intent was cancelled before activation")
            self._waiting_downloads -= 1
            self._active_downloads += 1
            intent._state = DownloadIntent._ACTIVE
            return intent

    async def acquire_scan(self) -> ActivityPermit:
        """Acquire the single scan slot after all download activity is idle."""

        self._bind_owner_loop()
        async with self._condition:
            await self._condition.wait_for(
                lambda: not self._scan_active
                and self._waiting_downloads == 0
                and self._active_downloads == 0
            )
            self._scan_active = True
            return ActivityPermit(self)

    def _release_download(self, intent: DownloadIntent) -> None:
        loop = self._bind_owner_loop()
        if intent._gate is not self or intent._state == DownloadIntent._RELEASED:
            return
        released_state = intent._state
        intent._state = DownloadIntent._RELEASED

        async def release_download() -> None:
            async with self._condition:
                if released_state == DownloadIntent._WAITING:
                    self._waiting_downloads -= 1
                elif released_state == DownloadIntent._ACTIVE:
                    self._active_downloads -= 1
                self._condition.notify_all()
                if not intent._release_complete.done():
                    intent._release_complete.set_result(None)

        loop.create_task(release_download())

    def _release_scan(self) -> None:
        loop = self._bind_owner_loop()
        if not self._scan_active:
            return

        async def release_scan() -> None:
            async with self._condition:
                self._scan_active = False
                self._condition.notify_all()

        loop.create_task(release_scan())

    @asynccontextmanager
    async def download_permit(self) -> AsyncIterator[DownloadIntent]:
        """Hold a high-priority permit around immediate Telegram work."""

        intent = await self.acquire_download()
        try:
            yield intent
        finally:
            await intent.release_and_wait()

    @asynccontextmanager
    async def scan_permit(self) -> AsyncIterator[ActivityPermit]:
        """Hold the exclusive low-priority scan permit."""

        permit = await self.acquire_scan()
        try:
            yield permit
        finally:
            permit.release()

    async def has_download_activity(self) -> bool:
        """Return whether a download is queued or currently using Telegram."""

        self._bind_owner_loop()
        async with self._condition:
            return self._waiting_downloads > 0 or self._active_downloads > 0

    async def wait_until_downloads_idle(self) -> None:
        """Wait for download activity only, independent of the scan slot."""

        self._bind_owner_loop()
        async with self._condition:
            await self._condition.wait_for(
                lambda: self._waiting_downloads == 0 and self._active_downloads == 0
            )

    async def wait_until_idle(self) -> None:
        """Wait until no queued/active download or scan remains."""

        self._bind_owner_loop()
        async with self._condition:
            await self._condition.wait_for(
                lambda: self._waiting_downloads == 0
                and self._active_downloads == 0
                and not self._scan_active
            )


_telegram_activity_gate = TelegramActivityGate()


def get_telegram_activity_gate() -> TelegramActivityGate:
    """Return the process-wide gate, replacing it after its loop has closed."""

    global _telegram_activity_gate
    owner_loop = _telegram_activity_gate.owner_loop
    if owner_loop is not None and owner_loop.is_closed():
        _telegram_activity_gate = TelegramActivityGate()
    return _telegram_activity_gate
