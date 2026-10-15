"""Final review: timers and healthy destinations progress during slow delivery."""
from datetime import timedelta
from threading import Event, Lock

from dota_dungeon.telegram.client import BotClient
from dota_dungeon.service.application import Application
from test_service_recovery import Store, Router, entry, NOW


def test_durable_outbox_attempt_has_no_inline_backoff_and_uses_failure_clock():
    store = Store()
    store.entries = [entry()]
    elapsed = [0]
    waits, timeouts = [], []
    def transport(url, payload, timeout):
        timeouts.append(timeout)
        elapsed[0] += 7
        return {'ok':False,'error_code':429,'description':'slow','parameters':{'retry_after':30}}
    bot = BotClient('dummy',transport=transport,sleep=waits.append)
    worker = Application(store,bot,Router(),None,clock=lambda: NOW+timedelta(seconds=elapsed[0]))
    worker.deliver_outbox(NOW)
    assert waits == [] and len(timeouts) == 1 and timeouts[0] <= 10
    assert store.retries[1] == ('429', NOW+timedelta(seconds=37))


def test_independent_workers_tick_deadline_and_deliver_other_group_while_one_is_blocked():
    blocked, release, healthy, timer = Event(), Event(), Event(), Event()
    lock = Lock()
    class ClaimedStore(Store):
        def claim_outbox(self, *, limit, now):
            with lock:
                batch, self.entries = self.entries[:limit], self.entries[limit:]
                return batch
    store = ClaimedStore()
    store.entries = [entry(chat_id=-100),{**entry(chat_id=-200),'id':2}]
    def transport(url,payload,timeout):
        if payload['chat_id']==-100:
            blocked.set()
            assert release.wait(3)
            return {'ok':False,'error_code':429,'parameters':{'retry_after':30}}
        healthy.set()
        return {'ok':True,'result':{'message_id':2}}
    worker = Application(store,BotClient('dummy',transport=transport),Router(),None,clock=lambda:NOW)
    def tick():
        if blocked.is_set():
            timer.set()
        return 0
    worker.tick_timers = tick
    # Real worker composition is shared with run(), not a test-only executor.
    threads = worker.start_workers()
    try:
        assert blocked.wait(1)
        assert healthy.wait(1), 'another group waited for slow transport'
        assert timer.wait(2), 'timer loop waited for slow transport'
        assert not release.is_set()
    finally:
        worker.stop.set()
        release.set()
        for thread in threads:
            thread.join(3)
    assert store.sent[2] == {'message_id':2}
    assert store.retries[1][0] == '429'
