#!/usr/bin/env python
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
# http://www.apache.org/licenses/LICENSE-2.0
#
# Authors:
# - Mario Lassnig, mario.lassnig@cern.ch, 2016-2017
# - Daniel Drizhuk, d.drizhuk@gmail.com, 2017
# - Tobias Wegner, tobias.wegner@cern.ch, 2017
# - Paul Nilsson, paul.nilsson@cern.ch, 2017-2019
# - Wen Guan, wen.guan@cern.ch, 2018

import time
import os
import signal
from subprocess import PIPE

from pilot.common.errorcodes import ErrorCodes
from pilot.control.job import send_state
from pilot.util.auxiliary import get_logger, set_pilot_state
from pilot.util.config import config
from pilot.util.container import execute
from pilot.util.constants import UTILITY_BEFORE_PAYLOAD, UTILITY_WITH_PAYLOAD, UTILITY_AFTER_PAYLOAD_STARTED, \
    UTILITY_AFTER_PAYLOAD_FINISHED, PILOT_PRE_SETUP, PILOT_POST_SETUP, PILOT_PRE_PAYLOAD, PILOT_POST_PAYLOAD
from pilot.util.filehandling import write_file
from pilot.util.timing import add_to_pilot_timing
from pilot.common.exception import PilotException

import logging
logger = logging.getLogger(__name__)

errors = ErrorCodes()


class Executor(object):
    def __init__(self, args, job, out, err, traces):
        self.__args = args
        self.__job = job
        self.__out = out
        self.__err = err
        self.__traces = traces
        self.__payload_stdout = config.Payload.payloadstdout
        self.__payload_stderr = config.Payload.payloadstderr
        self.__preprocess_stdout = ''
        self.__preprocess_stderr = ''
        self.__postprocess_stdout = ''
        self.__postprocess_stderr = ''

    def get_job(self):
        """
        Get the job object.
        :return: job object.
        """
        return self.__job

    def pre_setup(self, job):
        """
        Functions to run pre setup
        :param job: job object
        """
        # write time stamps to pilot timing file
        add_to_pilot_timing(job.jobid, PILOT_PRE_SETUP, time.time(), self.__args)

    def post_setup(self, job):
        """
        Functions to run post setup
        :param job: job object
        """
        # write time stamps to pilot timing file
        add_to_pilot_timing(job.jobid, PILOT_POST_SETUP, time.time(), self.__args)

    def utility_before_payload(self, job):
        """
        Prepare commands/utilities to run before payload.
        These commands will be executed later (as eg the payload command setup is unknown at this point, which is
        needed for the preprocessing. Preprocessing is prepared here).

        :param job: job object.
        """
        cmd = ""
        log = get_logger(job.jobid, logger)

        # get the payload command from the user specific code
        pilot_user = os.environ.get('PILOT_USER', 'generic').lower()
        user = __import__('pilot.user.%s.common' % pilot_user, globals(), locals(), [pilot_user], 0)  # Python 2/3

        # should we run any additional commands? (e.g. special monitoring commands)
        cmd_dictionary = user.get_utility_commands(order=UTILITY_BEFORE_PAYLOAD, job=job)
        if cmd_dictionary:
            cmd = '%s %s' % (cmd_dictionary.get('command'), cmd_dictionary.get('args'))
            log.debug('utility command to be executed before the payload: %s' % cmd)

        return cmd

    def utility_with_payload(self, job):
        """
        Functions to run with payload.

        :param job: job object.
        """
        log = get_logger(job.jobid, logger)

        # get the payload command from the user specific code
        pilot_user = os.environ.get('PILOT_USER', 'generic').lower()
        user = __import__('pilot.user.%s.common' % pilot_user, globals(), locals(), [pilot_user], 0)  # Python 2/3

        # should any additional commands be prepended to the payload execution string?
        cmd_dictionary = user.get_utility_commands(order=UTILITY_WITH_PAYLOAD, job=job)
        if cmd_dictionary:
            cmd = '%s %s' % (cmd_dictionary.get('command'), cmd_dictionary.get('args'))
            log.debug('utility command to be executed with the payload: %s' % cmd)

        return cmd

    def utility_after_payload_started(self, job):
        """
        Functions to run after payload started
        :param job: job object
        """
        log = get_logger(job.jobid, logger)

        # get the payload command from the user specific code
        pilot_user = os.environ.get('PILOT_USER', 'generic').lower()
        user = __import__('pilot.user.%s.common' % pilot_user, globals(), locals(), [pilot_user], 0)  # Python 2/3

        # should any additional commands be executed after the payload?
        cmd_dictionary = user.get_utility_commands(order=UTILITY_AFTER_PAYLOAD_STARTED, job=job)
        if cmd_dictionary:
            cmd = '%s %s' % (cmd_dictionary.get('command'), cmd_dictionary.get('args'))
            log.info('utility command to be executed after the payload: %s' % cmd)

            # how should this command be executed?
            utilitycommand = user.get_utility_command_setup(cmd_dictionary.get('command'), job)
            if not utilitycommand:
                log.warning('empty utility command - nothing to run')
                return
            try:
                proc1 = execute(utilitycommand, workdir=job.workdir, returnproc=True, usecontainer=False,
                                stdout=PIPE, stderr=PIPE, cwd=job.workdir, job=job)
            except Exception as e:
                log.error('could not execute: %s' % e)
            else:
                # store process handle in job object, and keep track on how many times the command has been launched
                # also store the full command in case it needs to be restarted later (by the job_monitor() thread)
                job.utilities[cmd_dictionary.get('command')] = [proc1, 1, utilitycommand]

    def utility_after_payload_finished(self, job):
        """
        Prepare commands/utilities to run after payload has finished.

        This command will be executed later.

        :param job: job object.
        """

        cmd = ""
        log = get_logger(job.jobid, logger)

        # get the payload command from the user specific code
        pilot_user = os.environ.get('PILOT_USER', 'generic').lower()
        user = __import__('pilot.user.%s.common' % pilot_user, globals(), locals(), [pilot_user], 0)  # Python 2/3

        # should any additional commands be prepended to the payload execution string?
        cmd_dictionary = user.get_utility_commands(order=UTILITY_AFTER_PAYLOAD_FINISHED, job=job)
        if cmd_dictionary:
            cmd = '%s %s' % (cmd_dictionary.get('command'), cmd_dictionary.get('args'))
            log.debug('utility command to be executed after the payload has finished: %s' % cmd)

        return cmd

    def execute_utility_command(self, cmd, job, label):
        """
        Execute a utility command (e.g. pre/postprocess commands; label=preprocess etc).

        :param cmd: full command to be executed (string).
        :param job: job object.
        :param label: command label (string).
        :return: exit code (int).
        """

        log = get_logger(job.jobid, logger)
        exit_code, stdout, stderr = execute(cmd, workdir=job.workdir, cwd=job.workdir, usecontainer=False)
        if exit_code:
            log.warning('command returned non-zero exit code: %s (exit code = %d) - see utility logs for details' % (cmd, exit_code))
            if label == 'preprocess':
                err = errors.PREPROCESSFAILURE
            elif label == 'postprocess':
                err = errors.POSTPROCESSFAILURE
            else:
                err = errors.UNKNOWNPAYLOADFAILURE
            if exit_code != 160:  # ignore no-more-data-points exit code
                job.piloterrorcodes, job.piloterrordiags = errors.add_error_code(err)

        # write output to log files
        self.write_utility_output(job.workdir, label, stdout, stderr)

        return exit_code

    def write_utility_output(self, workdir, step, stdout, stderr):
        """
        Write the utility command output to stdout, stderr files to the job.workdir for the current step.
        -> <step>_stdout.txt, <step>_stderr.txt
        Example of step: preprocess, postprocess.

        :param workdir: job workdir (string).
        :param step: utility step (string).
        :param stdout: command stdout (string).
        :param stderr: command stderr (string).
        :return:
        """

        # dump to file
        try:
            name_stdout = step + '_stdout.txt'
            name_stderr = step + '_stderr.txt'
            if step == 'preprocess':
                self.__preprocess_stdout = name_stdout
                self.__preprocess_stderr = name_stderr
            elif step == 'postprocess':
                self.__postprocess_stdout = name_stdout
                self.__postprocess_stderr = name_stderr
            write_file(os.path.join(workdir, step + '_stdout.txt'), stdout, unique=True)
        except PilotException as e:
            logger.warning('failed to write utility stdout to file: %s, %s' % (e, stdout))
        try:
            write_file(os.path.join(workdir, step + '_stderr.txt'), stderr, unique=True)
        except PilotException as e:
            logger.warning('failed to write utility stderr to file: %s, %s' % (e, stderr))

    def pre_payload(self, job):
        """
        Calls to functions to run before payload.
        E.g. write time stamps to timing file.

        :param job: job object.
        """
        # write time stamps to pilot timing file
        add_to_pilot_timing(job.jobid, PILOT_PRE_PAYLOAD, time.time(), self.__args)

    def post_payload(self, job):
        """
        Calls to functions to run after payload.
        E.g. write time stamps to timing file.

        :param job: job object
        """
        # write time stamps to pilot timing file
        add_to_pilot_timing(job.jobid, PILOT_POST_PAYLOAD, time.time(), self.__args)

    def run_payload(self, job, cmd, out, err):
        """
        Setup and execute the main payload process.

        :param job: job object.
        :param out: (currently not used; deprecated)
        :param err: (currently not used; deprecated)
        :return: proc (subprocess returned by Popen())
        """

        log = get_logger(job.jobid, logger)

        # main payload process steps

        # add time for PILOT_PRE_PAYLOAD
        self.pre_payload(job)

        _cmd = self.utility_with_payload(job)
        if _cmd:
            log.info('could have executed: %s (currently not used)' % _cmd)

        log.info("\n\npayload execution command:\n\n%s\n" % cmd)
        try:
            proc = execute(cmd, workdir=job.workdir, returnproc=True,
                           usecontainer=True, stdout=out, stderr=err, cwd=job.workdir, job=job)
        except Exception as e:
            log.error('could not execute: %s' % str(e))
            return None
        if type(proc) == tuple and not proc[0]:
            log.error('failed to execute payload')
            return None

        log.info('started -- pid=%s executable=%s' % (proc.pid, cmd))
        job.pid = proc.pid
        job.pgrp = os.getpgid(job.pid)
        set_pilot_state(job=job, state="running")

        self.utility_after_payload_started(job)

        return proc

    def extract_setup(self, cmd):
        """
        Extract the setup from the payload command (cmd).
        E.g. extract the full setup from the payload command will be prepended to the pre/postprocess command.

        :param cmd: payload command (string).
        :return: updated secondary command (string).
        """

        # remove any trailing spaces and ;-signs
        cmd = cmd.strip()
        cmd = cmd[:-1] if cmd.endswith(';') else cmd
        last_bit = cmd.split(';')[-1]
        setup = cmd.replace(last_bit.strip(), '')

        return setup

    def wait_graceful(self, args, proc, job):
        """
        (add description)
        :param args:
        :param proc:
        :param job:
        :return:
        """

        log = get_logger(job.jobid, logger)

        breaker = False
        exit_code = None
        try:
            iteration = long(0)  # Python 2, do not use 0L since it will create a syntax error in spite of the try
        except Exception:
            iteration = 0  # Python 3, long doesn't exist
        while True:
            time.sleep(0.1)

            iteration += 1
            for i in range(60):  # Python 2/3
                if args.graceful_stop.is_set():
                    breaker = True
                    log.info('breaking -- sending SIGTERM pid=%s' % proc.pid)
                    os.killpg(os.getpgid(proc.pid), signal.SIGTERM)
                    # proc.terminate()
                    break
                time.sleep(1)
            if breaker:
                log.info('breaking -- sleep 3s before sending SIGKILL pid=%s' % proc.pid)
                time.sleep(3)
                proc.kill()
                break

            exit_code = proc.poll()

            if iteration % 10 == 0:
                log.info('running: iteration=%d pid=%s exit_code=%s' % (iteration, proc.pid, exit_code))
            if exit_code is not None:
                break
            else:
                # send_state(job, args, 'running')
                continue

        return exit_code

    def get_payload_command(self, job):
        """
        Return the payload command string.

        :param job: job object.
        :return: command (string).
        """

        log = get_logger(str(job), logger)

        cmd = ""
        # for testing looping job:    cmd = user.get_payload_command(job) + ';sleep 240'
        try:
            pilot_user = os.environ.get('PILOT_USER', 'generic').lower()
            user = __import__('pilot.user.%s.common' % pilot_user, globals(), locals(), [pilot_user],
                              0)  # Python 2/3
            cmd = user.get_payload_command(job)
        except PilotException as error:
            self.post_setup(job)
            import traceback
            log.error(traceback.format_exc())
            job.piloterrorcodes, job.piloterrordiags = errors.add_error_code(error.get_error_code())
            self.__traces.pilot['error_code'] = job.piloterrorcodes[0]
            log.fatal(
                'could not define payload command (traces error set to: %d)' % self.__traces.pilot['error_code'])

        return cmd

    def run_preprocess(self, job):
        """
        Run any preprocess payloads.

        :param job: job object.
        :return:
        """

        log = get_logger(str(self.__job.jobid), logger)
        exit_code = 0

        try:
            # note: this might update the jobparams
            cmd_before_payload = self.utility_before_payload(job)
        except Exception as e:
            log.error(e)
            raise e

        if cmd_before_payload:
            cmd_before_payload = job.setup + cmd_before_payload
            log.info("\n\npreprocess execution command:\n\n%s\n" % cmd_before_payload)
            exit_code = self.execute_utility_command(cmd_before_payload, job, 'preprocess')
            if exit_code == 160:
                log.fatal('no more HP points - time to abort processing loop')
            elif exit_code:
                # set error code
                job.piloterrorcodes, job.piloterrordiags = errors.add_error_code(errors.PREPROCESSFAILURE)
                log.fatal('cannot continue since preprocess failed: exit_code=%d' % exit_code)
            else:
                # in case the preprocess produced a command, chmod it
                path = os.path.join(job.workdir, job.containeroptions.get('containerExec', 'does_not_exist'))
                if os.path.exists(path):
                    log.debug('chmod 0o755: %s' % path)
                    os.chmod(path, 0o755)

        return exit_code

    def run(self):  # noqa: C901
        """
        Run all payload processes (including pre- and post-processes, and utilities).
        In the case of HPO jobs, this function will loop over all processes until the preprocess returns a special
        exit code.
        :return:
        """
        log = get_logger(str(self.__job.jobid), logger)

        # get the payload command from the user specific code
        self.pre_setup(self.__job)
        cmd = self.get_payload_command(self.__job)
        # extract the setup in case the preprocess command needs it
        self.__job.setup = self.extract_setup(cmd)
        self.post_setup(self.__job)

        # a loop is needed for HPO jobs
        # abort when nothing more to run, or when the preprocess returns a special exit code
        iteration = 1
        while True:
            log.info('payload iteration loop #%d' % iteration)

            # first run the preprocess (if necessary) - note: this might update jobparams -> must update cmd
            jobparams_pre = self.__job.jobparams
            exit_code = self.run_preprocess(self.__job)
            jobparams_post = self.__job.jobparams
            if exit_code:
                if exit_code == 160:
                    exit_code = 0
                break
            if jobparams_pre != jobparams_post:
                log.debug('jobparams were updated by utility_before_payload()')
                # must update cmd
                cmd = cmd.replace(jobparams_pre, jobparams_post)

            # now run the main payload, when it finishes, run the postprocess (if necessary)
            proc = self.run_payload(self.__job, cmd, self.__out, self.__err)
            proc_co = None
            if proc is None:
                break
            else:
                # the process is now running, update the server
                send_state(self.__job, self.__args, self.__job.state)

                # start any coprocess if necessary
                if self.__job.coprocess:
                    log.debug('starting coprocess')
                    # proc_co = self.run_coprocess(self.__job)

                log.info('will wait for graceful exit')
                exit_code = self.wait_graceful(self.__args, proc, self.__job)
                state = 'finished' if exit_code == 0 else 'failed'
                set_pilot_state(job=self.__job, state=state)
                log.info('\n\nfinished pid=%s exit_code=%s state=%s\n' % (proc.pid, exit_code, self.__job.state))

                # stop the coprocess if necessary
                if proc_co:
                    log.debug('stopping coprocess')
                    # self.stop_coprocess(proc_co)

                if exit_code is None:
                    log.warning('detected unset exit_code from wait_graceful - reset to -1')
                    exit_code = -1

                if state != 'failed':
                    try:
                        cmd_after_payload = self.utility_after_payload_finished(self.__job)
                    except Exception as e:
                        log.error(e)
                    else:
                        if cmd_after_payload:
                            cmd_after_payload = self.__job.setup + cmd_after_payload
                            log.info("\n\npostprocess execution command:\n\n%s\n" % cmd_after_payload)
                            exit_code = self.execute_utility_command(cmd_after_payload, self.__job, 'postprocess')

                self.post_payload(self.__job)

                # stop any running utilities
                if self.__job.utilities != {}:
                    self.stop_utilities()

            if self.__job.is_hpo:
                # in case there are more hyper-parameter points, move away the previous log files
                #self.rename_log_files(iteration)
                iteration += 1
            else:
                break

        return exit_code

    def stop_utilities(self):
        """
        Stop any running utilities.

        :return:
        """

        pilot_user = os.environ.get('PILOT_USER', 'generic').lower()

        for utcmd in list(self.__job.utilities.keys()):  # Python 2/3
            utproc = self.__job.utilities[utcmd][0]
            if utproc:
                user = __import__('pilot.user.%s.common' % pilot_user, globals(), locals(), [pilot_user], 0)  # Python 2/3
                sig = user.get_utility_command_kill_signal(utcmd)
                logger.info("stopping process \'%s\' with signal %d" % (utcmd, sig))
                try:
                    os.killpg(os.getpgid(utproc.pid), sig)
                except Exception as e:
                    logger.warning('exception caught: %s (ignoring)' % e)

                user.post_utility_command_action(utcmd, self.__job)

    def rename_log_files(self, iteration):
        """

        :param iteration:
        :return:
        """

        names = [self.__payload_stdout, self.__payload_stderr, self.__preprocess_stdout, self.__preprocess_stderr,
                 self.__postprocess_stdout, self.__postprocess_stderr]
        for name in names:
            if os.path.exists(name):
                os.rename(name, name + '%d' % iteration)
            else:
                logger.warning('cannot rename %s since it does not exist' % name)
