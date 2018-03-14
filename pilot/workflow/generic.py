#!/usr/bin/env python
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
# http://www.apache.org/licenses/LICENSE-2.0
#
# Authors:
# - Mario Lassnig, mario.lassnig@cern.ch, 2016-2017
# - Daniel Drizhuk, d.drizhuk@gmail.com, 2017
# - Paul Nilsson, paul.nilsson@cern.ch, 2017

import functools
import Queue
import signal
import threading

from collections import namedtuple

from pilot.control import job, payload, data, lifetime, monitor
from pilot.util.constants import SUCCESS


import logging
logger = logging.getLogger(__name__)


def interrupt(args, signum, frame):
    logger.info('caught signal: %s' % [v for v, k in signal.__dict__.iteritems() if k == signum][0])
    args.graceful_stop.set()


class ExcThread(threading.Thread):
    """
    Support class that allows for catching exceptions in threads.
    """

    def __init__(self, bucket):
        """
        Init function with a bucket that can be used to communicate exceptions to the caller.
        :param bucket: Queue based bucket.
        """
        threading.Thread.__init__(self)
        self.bucket = bucket

    def run(self):
        """
        Run function.
        :return:
        """

def run(args):
    """
    Main execution function for the generic workflow.

    The function sets up the internal queues which handle the flow of jobs.

    :param args: pilot arguments.
    :returns: traces.
    """

    logger.info('setting up signal handling')
    signal.signal(signal.SIGINT, functools.partial(interrupt, args))

    logger.info('setting up queues')

    queues = namedtuple('queues', ['jobs', 'payloads', 'data_in', 'data_out',
                                   'validated_jobs', 'validated_payloads',
                                   'finished_jobs', 'finished_payloads', 'finished_data_in', 'finished_data_out',
                                   'failed_jobs', 'failed_payloads', 'failed_data_in', 'failed_data_out'])

    queues.jobs = Queue.Queue()
    queues.payloads = Queue.Queue()
    queues.data_in = Queue.Queue()
    queues.data_out = Queue.Queue()

    queues.validated_jobs = Queue.Queue()
    queues.validated_payloads = Queue.Queue()

    queues.finished_jobs = Queue.Queue()
    queues.finished_payloads = Queue.Queue()
    queues.finished_data_in = Queue.Queue()
    queues.finished_data_out = Queue.Queue()

    queues.failed_jobs = Queue.Queue()
    queues.failed_payloads = Queue.Queue()
    queues.failed_data_in = Queue.Queue()
    queues.failed_data_out = Queue.Queue()

    logger.info('setting up tracing')
    traces = namedtuple('traces', ['pilot'])
    traces.pilot = {'state': SUCCESS,
                    'nr_jobs': 0}

    logger.info('starting threads')

    targets = [job.control, payload.control, data.control, lifetime.control, monitor.control]
    threads = [threading.Thread(target=target, kwargs={'queues': queues, 'traces': traces, 'args': args})
               for target in targets]

    # threads = [threading.Thread(target=job.control,
    #                             kwargs={'queues': queues,
    #                                     'traces': traces,
    #                                     'args': args}),
    #            threading.Thread(target=payload.control,
    #                             kwargs={'queues': queues,
    #                                     'traces': traces,
    #                                     'args': args}),
    #            threading.Thread(target=data.control,
    #                             kwargs={'queues': queues,
    #                                     'traces': traces,
    #                                     'args': args}),
    #            threading.Thread(target=lifetime.control,
    #                             kwargs={'queues': queues,
    #                                     'traces': traces,
    #                                     'args': args}),
    #            threading.Thread(target=monitor.control,
    #                             kwargs={'queues': queues,
    #                                     'traces': traces,
    #                                     'args': args})]

    [t.start() for t in threads]

    logger.info('waiting for interrupts')

    # Interruptible joins require a timeout
    while threading.activeCount() > 1:
        [t.join(timeout=1) for t in threads]

    return traces
