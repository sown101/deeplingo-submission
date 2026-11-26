"""Canonical supported worker command: Linux prefork2, prefetch1, one queue."""
import sys


def main():
    if sys.platform != 'linux':
        raise SystemExit('Supported Content workers require Linux + prefork; Windows threads are NOT RELIABILITY QUALIFIED')
    from app.bootstrap.worker import celery_app
    celery_app.worker_main(['worker', '--pool=prefork', '--concurrency=2',
                            '--prefetch-multiplier=1', '--queues=celery', '--loglevel=INFO'])


if __name__ == '__main__':
    main()
