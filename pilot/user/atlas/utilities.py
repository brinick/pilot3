#!/usr/bin/env python
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
# http://www.apache.org/licenses/LICENSE-2.0
#
# Authors:
# - Paul Nilsson, paul.nilsson@cern.ch, 2018

import os
import time
from getpass import getuser
from re import search

# from pilot.info import infosys
from .setup import get_asetup
from pilot.util.auxiliary import get_logger
from pilot.util.container import execute
from pilot.util.filehandling import read_json, copy

import logging
logger = logging.getLogger(__name__)


def get_benchmark_setup(job):
    """
    Return the proper setup for the benchmark command.

    :param job: job object.
    :return: setup string for the benchmark command.
    """

    return ''


def get_prefetcher_setup(job):
    """
    Return the proper setup for the Prefetcher.
    Prefetcher is a tool used with the Event Streaming Service.

    :param job: job object.
    :return: setup string for the Prefetcher command.
    """

    # add code here ..

    return ''


def get_network_monitor_setup(setup, job):
    """
    Return the proper setup for the network monitor.
    The network monitor is currently setup together with the payload and is start before it. The payload setup should
    therefore be provided. The network monitor setup is prepended to it.

    :param setup: payload setup string.
    :param job: job object.
    :return: network monitor setup string.
    """

    return ''


def get_memory_monitor_summary_filename(selector=None):
    """
    Return the name for the memory monitor summary file.

    :param selector: special conditions flag (boolean).
    :return: File name (string).
    """

    name = "memory_monitor_summary.json"
    if selector:
        name += '_snapshot'

    return name


def get_memory_monitor_output_filename():
    """
    Return the filename of the memory monitor text output file.

    :return: File name (string).
    """

    return "memory_monitor_output.txt"


def get_memory_monitor_setup(pid, workdir, command, setup="", use_container=True, transformation=""):
    """
    Return the proper setup for the memory monitor.
    If the payload release is provided, the memory monitor can be setup with the same release. Until early 2018, the
    memory monitor was still located in the release area. After many problems with the memory monitor, it was decided
    to use a fixed version for the setup. Currently, release 21.0.22 is used.

    :param pid: job process id (int).
    :param workdir: job work directory (string).
    :param command: payload command (string).
    :param setup: optional setup in case asetup can not be used, which uses infosys (string).
    :param use_container: optional boolean.
    :param transformation: optional name of transformation, e.g. Sim_tf.py (string).
    :return: job work directory (string).
    """

    # try to get the pid from a pid.txt file which might be created by a container_script
    pid = get_proper_pid(pid, command, use_container=use_container, transformation=transformation)

    release = "21.0.22"
    platform = "x86_64-slc6-gcc62-opt"
    if not setup:
        setup = get_asetup() + " Athena," + release + " --platform " + platform
    interval = 60
    if not setup.endswith(';'):
        setup += ';'
    # Now add the MemoryMonitor command
    _cmd = "%sMemoryMonitor --pid %d --filename %s --json-summary %s --interval %d" %\
           (setup, pid, get_memory_monitor_output_filename(), get_memory_monitor_summary_filename(), interval)
    _cmd = "cd " + workdir + ";" + _cmd

    return _cmd


def get_proper_pid(pid, command, use_container=True, transformation=""):
    """
    Return a pid from the proper source.
    The given pid comes from Popen(), but in the case containers are used, the pid should instead come from a ps aux
    lookup.

    :param pid: process id (int).
    :param command: payload command (string).
    :param use_container: optional boolean.
    :param transformation: optional name of transformation, e.g. Sim_tf.py (string).
    :return: pid (int).
    """

    if not use_container:
        return pid

    _cmd = get_trf_command(command, transformation=transformation)
    i = 0
    imax = 120
    while i < imax:
        ps = get_ps_info()
        logger.debug('ps:\n%s' % ps)

        # lookup the process id using ps aux
        _pid = get_pid_for_cmd(_cmd, ps)
        if _pid:
            logger.debug('pid=%d for command \"%s\"' % (_pid, _cmd))
            break
        else:
            logger.warning('pid not identified from payload command (#%d/#%d)' % (i + 1, imax))

        # wait until the payload has launched
        time.sleep(5)
        i += 1

    if _pid:
        pid = _pid

    logger.info('will use pid=%d for memory monitor' % pid)

    return pid


def get_ps_info(whoami=getuser(), options='axfo pid,user,rss,pcpu,args'):
    """
    Return ps info for the given user.

    :param whoami: user name (string).
    :return: ps aux for given user (string).
    """

    cmd = "ps %s | grep %s" % (options, whoami)
    exit_code, stdout, stderr = execute(cmd)

    return stdout


def get_pid_for_cmd(cmd, ps, whoami=getuser()):
    """
    Return the process id for the given command and user.
    Note: function returns 0 in case pid could not be found.

    :param cmd: command string expected to be in ps output (string).
    :param ps: ps output (string).
    :param whoami: user name (string).
    :return: pid (int) or None if no such process.
    """

    pid = None
    found = None

    for line in ps.split('\n'):
        if cmd in line:
            found = line
            break
    if found:
        # extract pid
        _pid = search(r'(\d+) ', found)
        try:
            pid = int(_pid.group(1))
        except Exception as e:
            logger.warning('pid has wrong type: %s' % e)
        else:
            logger.debug('extracted pid=%d from ps output: %s' % (pid, found))
    else:
        logger.debug('command not found in ps output: %s' % cmd)

    return pid


def get_trf_command(command, transformation=""):
    """
    Return the last command in the full payload command string.
    Note: this function returns the last command in job.command which is only set for containers.

    :param command: full payload command (string).
    :param transformation: optional name of transformation, e.g. Sim_tf.py (string).
    :return: trf command (string).
    """

    payload_command = ""
    if command:
        if not transformation:
            payload_command = command.split(';')[-2]
        else:
            if transformation in command:
                payload_command = command[command.find(transformation):]

        # clean-up the command, remove '-signs and any trailing ;
        payload_command = payload_command.strip()
        payload_command = payload_command.replace("'", "")
        payload_command = payload_command.rstrip(";")

    return payload_command


def get_memory_monitor_info_path(workdir, allowtxtfile=False):
    """
    Find the proper path to the utility info file
    Priority order:
       1. JSON summary file from workdir
       2. JSON summary file from pilot initdir
       3. Text output file from workdir (if allowtxtfile is True)

    :param workdir: relevant work directory (string).
    :param allowtxtfile: boolean attribute to allow for reading the raw memory monitor output.
    :return: path (string).
    """

    pilot_initdir = os.environ.get('PILOT_HOME', '')
    path = os.path.join(workdir, get_memory_monitor_summary_filename())
    init_path = os.path.join(pilot_initdir, get_memory_monitor_summary_filename())

    if not os.path.exists(path):
        if os.path.exists(init_path):
            path = init_path
        else:
            logger.info("neither %s, nor %s exist" % (path, init_path))
            path = ""

        if path == "" and allowtxtfile:
            path = os.path.join(workdir, get_memory_monitor_output_filename())
            if not os.path.exists(path):
                logger.warning("file does not exist either: %s" % (path))

    return path


def get_memory_monitor_info(workdir, allowtxtfile=False):
    """
    Add the utility info to the node structure if available.

    :param workdir: relevant work directory (string).
    :param allowtxtfile: boolean attribute to allow for reading the raw memory monitor output.
    :return: node structure (dictionary).
    """

    node = {}

    # Get the values from the memory monitor file (json if it exists, otherwise the preliminary txt file)
    # Note that only the final json file will contain the totRBYTES, etc
    summary_dictionary = get_memory_values(workdir)

    logger.debug("summary_dictionary=%s" % str(summary_dictionary))

    # Fill the node dictionary
    if summary_dictionary and summary_dictionary != {}:
        try:
            node['maxRSS'] = summary_dictionary['Max']['maxRSS']
            node['maxVMEM'] = summary_dictionary['Max']['maxVMEM']
            node['maxSWAP'] = summary_dictionary['Max']['maxSwap']
            node['maxPSS'] = summary_dictionary['Max']['maxPSS']
            node['avgRSS'] = summary_dictionary['Avg']['avgRSS']
            node['avgVMEM'] = summary_dictionary['Avg']['avgVMEM']
            node['avgSWAP'] = summary_dictionary['Avg']['avgSwap']
            node['avgPSS'] = summary_dictionary['Avg']['avgPSS']
        except Exception as e:
            logger.warning("exception caught while parsing memory monitor file: %s" % e)
            logger.warning("will add -1 values for the memory info")
            node['maxRSS'] = -1
            node['maxVMEM'] = -1
            node['maxSWAP'] = -1
            node['maxPSS'] = -1
            node['avgRSS'] = -1
            node['avgVMEM'] = -1
            node['avgSWAP'] = -1
            node['avgPSS'] = -1
        else:
            logger.info("extracted standard info from memory monitor json")
        try:
            node['totRCHAR'] = summary_dictionary['Max']['totRCHAR']
            node['totWCHAR'] = summary_dictionary['Max']['totWCHAR']
            node['totRBYTES'] = summary_dictionary['Max']['totRBYTES']
            node['totWBYTES'] = summary_dictionary['Max']['totWBYTES']
            node['rateRCHAR'] = summary_dictionary['Avg']['rateRCHAR']
            node['rateWCHAR'] = summary_dictionary['Avg']['rateWCHAR']
            node['rateRBYTES'] = summary_dictionary['Avg']['rateRBYTES']
            node['rateWBYTES'] = summary_dictionary['Avg']['rateWBYTES']
        except Exception:
            logger.warning("standard memory fields were not found in memory monitor json (or json doesn't exist yet)")
        else:
            logger.info("extracted standard memory fields from memory monitor json")
    else:
        logger.info("memory summary dictionary not yet available")

    return node


def get_max_memory_monitor_value(value, maxvalue, totalvalue):
    """
    Return the max and total value (used by memory monitoring).
    Return an error code, 1, in case of value error.

    :param value: value to be tested (integer).
    :param maxvalue: current maximum value (integer).
    :param totalvalue: total value (integer).
    :return: exit code, maximum and total value (tuple of integers).
    """

    ec = 0
    try:
        value_int = int(value)
    except Exception as e:
        logger.warning("exception caught: %s" % e)
        ec = 1
    else:
        totalvalue += value_int
        if value_int > maxvalue:
            maxvalue = value_int

    return ec, maxvalue, totalvalue


def convert_unicode_string(unicode_string):
    """
    Convert a unicode string into str.

    :param unicode_string:
    :return: string.
    """

    if unicode_string is not None:
        return str(unicode_string)
    return None


def get_average_summary_dictionary(path):
    """
    Loop over the memory monitor output file and create the averaged summary dictionary.

    :param path: path to memory monitor output file (string).
    :return: summary dictionary.
    """

    maxvmem = -1
    maxrss = -1
    maxpss = -1
    maxswap = -1
    avgvmem = 0
    avgrss = 0
    avgpss = 0
    avgswap = 0
    totalvmem = 0
    totalrss = 0
    totalpss = 0
    totalswap = 0
    n = 0
    summary_dictionary = {}

    rchar = None
    wchar = None
    rbytes = None
    wbytes = None

    first = True
    with open(path) as f:
        for line in f:
            # Skip the first line
            if first:
                first = False
                continue
            line = convert_unicode_string(line)
            if line != "":
                try:
                    # Remove empty entries from list (caused by multiple \t)
                    _l = filter(None, line.split('\t'))
                    # _time = _l[0]  # 'Time' not user
                    vmem = _l[1]
                    pss = _l[2]
                    rss = _l[3]
                    swap = _l[4]
                    # note: the last rchar etc values will be reported
                    if len(_l) == 9:
                        rchar = int(_l[5])
                        wchar = int(_l[6])
                        rbytes = int(_l[7])
                        wbytes = int(_l[8])
                    else:
                        rchar = None
                        wchar = None
                        rbytes = None
                        wbytes = None
                except Exception:
                    logger.warning("unexpected format of utility output: %s (expected format: Time, VMEM,"
                                   " PSS, RSS, Swap [, RCHAR, WCHAR, RBYTES, WBYTES])" % (line))
                else:
                    # Convert to int
                    ec1, maxvmem, totalvmem = get_max_memory_monitor_value(vmem, maxvmem, totalvmem)
                    ec2, maxpss, totalpss = get_max_memory_monitor_value(pss, maxpss, totalpss)
                    ec3, maxrss, totalrss = get_max_memory_monitor_value(rss, maxrss, totalrss)
                    ec4, maxswap, totalswap = get_max_memory_monitor_value(swap, maxswap, totalswap)
                    if ec1 or ec2 or ec3 or ec4:
                        logger.warning("will skip this row of numbers due to value exception: %s" % (line))
                    else:
                        n += 1

        # Calculate averages and store all values
        summary_dictionary = {"Max": {}, "Avg": {}, "Other": {}}
        summary_dictionary["Max"] = {"maxVMEM": maxvmem, "maxPSS": maxpss, "maxRSS": maxrss, "maxSwap": maxswap}
        if rchar:
            summary_dictionary["Other"]["rchar"] = rchar
        if wchar:
            summary_dictionary["Other"]["wchar"] = wchar
        if rbytes:
            summary_dictionary["Other"]["rbytes"] = rbytes
        if wbytes:
            summary_dictionary["Other"]["wbytes"] = wbytes
        if n > 0:
            avgvmem = int(float(totalvmem) / float(n))
            avgpss = int(float(totalpss) / float(n))
            avgrss = int(float(totalrss) / float(n))
            avgswap = int(float(totalswap) / float(n))
        summary_dictionary["Avg"] = {"avgVMEM": avgvmem, "avgPSS": avgpss, "avgRSS": avgrss, "avgSwap": avgswap}

    return summary_dictionary


def get_memory_values(workdir):
    """
    Find the values in the memory monitor output file.

    In case the summary JSON file has not yet been produced, create a summary dictionary with the same format
    using the output text file (produced by the memory monitor and which is updated once per minute).

    FORMAT:
       {"Max":{"maxVMEM":40058624,"maxPSS":10340177,"maxRSS":16342012,"maxSwap":16235568},
        "Avg":{"avgVMEM":19384236,"avgPSS":5023500,"avgRSS":6501489,"avgSwap":5964997},
        "Other":{"rchar":NN,"wchar":NN,"rbytes":NN,"wbytes":NN}}

    :param workdir: relevant work directory (string).
    :return: memory values dictionary.
    """

    summary_dictionary = {}

    # Get the path to the proper memory info file (priority ordered)
    path = get_memory_monitor_info_path(workdir, allowtxtfile=True)
    if os.path.exists(path):
        logger.info("using path: %s" % (path))

        # Does a JSON summary file exist? If so, there's no need to calculate maximums and averages in the pilot
        if path.lower().endswith('json'):
            # Read the dictionary from the JSON file
            summary_dictionary = read_json(path)
        else:
            # Loop over the output file, line by line, and look for the maximum PSS value
            summary_dictionary = get_average_summary_dictionary(path)
    else:
        if path == "":
            logger.warning("filename not set for memory monitor output")
        else:
            # Normally this means that the memory output file has not been produced yet
            pass

    return summary_dictionary


def post_memory_monitor_action(job):
    """
    Perform post action items for memory monitor.

    :param job: job object.
    :return:
    """

    log = get_logger(job.jobid)

    nap = 3
    path1 = os.path.join(job.workdir, get_memory_monitor_summary_filename())
    path2 = os.environ.get('PILOT_HOME')
    i = 0
    maxretry = 20
    while i <= maxretry:
        if os.path.exists(path1):
            break
        log.info("taking a short nap (%d s) to allow the memory monitor to finish writing to the summary file (#%d/#%d)"
                 % (nap, i, maxretry))
        time.sleep(nap)
        i += 1

    try:
        copy(path1, path2)
    except Exception as e:
        log.warning('failed to copy memory monitor output: %s' % e)
