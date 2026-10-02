"""In-process background work for the single backend process.

The desktop application did this from window timers while someone was signed in: queue
collection reminders, submit up to ten queued notifications, refresh the browsable
customer folders and take any scheduled backup. The same work runs here on a plain
asyncio loop, as the most recently active signed-in user, and only while someone is
signed in, which keeps the desktop semantics. No broker, no extra process.

Each step is independent and failures are logged and retried on the next tick; a failed
optional notification can never undo a committed repair transaction, because every
business transaction has already committed before anything is queued here.
"""
import asyncio
import logging
import time
from repairshop.services import Service

log = logging.getLogger('repairshop.scheduler')
BACKUP_INTERVAL = 3600


class Scheduler:
    def __init__(self, runtime, interval):
        self.rt, self.interval = runtime, interval
        self.task = None
        self.last_backup_check = 0.0
        self.busy = False

    def start(self):
        if self.rt.db.readonly:
            return
        try:
            from repairshop.messaging import Outbox
            Outbox(Service(self.rt.db)).recover_claims()
        except Exception:
            log.exception('Could not recover interrupted notification claims')
        self.task = asyncio.get_running_loop().create_task(self._loop())

    async def stop(self):
        if self.task:
            self.task.cancel()
            try:
                await self.task
            except asyncio.CancelledError:
                pass
            self.task = None

    async def _loop(self):
        while True:
            await asyncio.sleep(self.interval)
            await asyncio.to_thread(self.tick)

    def service(self):
        user_id = self.rt.sessions.most_recent_user()
        if not user_id:
            return None
        s = Service(self.rt.db)
        try:
            s.resume(user_id)
        except Exception:
            return None
        return s

    def tick(self):
        """One pass of background work. Safe to call directly, e.g. from tests."""
        if self.busy:
            return {}
        self.busy = True
        done = {}
        try:
            s = self.service()
            if s is None:
                return done
            done['messages'] = self._step('notifications', lambda: self._notifications(s))
            done['folders'] = self._step('customer folders', lambda: self._folders(s))
            if time.monotonic() - self.last_backup_check >= BACKUP_INTERVAL or not self.last_backup_check:
                self.last_backup_check = time.monotonic()
                done['backups'] = self._step('scheduled backup', lambda: self._backups(s))
            return done
        finally:
            self.busy = False

    @staticmethod
    def _step(name, work):
        try:
            return work()
        except Exception as exc:
            log.warning('Background %s did not complete: %s', name, exc)
            return None

    @staticmethod
    def _notifications(s):
        from repairshop.messaging import Outbox
        out = Outbox(s)
        out.schedule_reminders()
        sent = 0
        for _ in range(10):
            if not out.process_one():
                break
            sent += 1
        return sent

    @staticmethod
    def _folders(s):
        from repairshop.customer_records import CustomerRecords
        return CustomerRecords(s).sync_pending()

    @staticmethod
    def _backups(s):
        from repairshop.backup import Backups
        return len(Backups(s).due())
