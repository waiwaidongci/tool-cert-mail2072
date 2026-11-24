import logging
import time
from pathlib import Path
from src.services import comparisons
from src.services.execution import claim, execute, materialize_due
from src.utils.wakeup import wait

logging.basicConfig(level=logging.INFO)
log = logging.getLogger(__name__)
heartbeat = Path('/tmp/analysis-heartbeat')

# 两类任务交替优先领取，任一类都不会长期饿死。
handlers = (claim, comparisons.claim)
_turn = 0


def next_lease():
    global _turn
    for step in range(len(handlers)):
        index = (_turn + step) % len(handlers)
        lease = handlers[index]()
        if lease:
            _turn = (index + 1) % len(handlers)
            return index, lease
    return None, None


def main():
    while True:
        try:
            materialize_due()
            index, lease = next_lease()
            heartbeat.touch()
            if index is not None:
                if index == 0:
                    execute(lease)
                else:
                    comparisons.execute(*lease)
                heartbeat.touch()
            else:
                wait()
        except Exception:
            log.exception('Worker cycle failed')
            time.sleep(2)


if __name__ == '__main__':
    main()
