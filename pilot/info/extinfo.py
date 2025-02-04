# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
# http://www.apache.org/licenses/LICENSE-2.0
#
# Authors:
# - Alexey Anisenkov, anisyonk@cern.ch, 2018-2021
# - Paul Nilsson, paul.nilsson@cern.ch, 2018-2022

"""
Information provider from external source(s)
which is mainly used to retrive Queue, Site, etc data required for Information Service

:author: Alexey Anisenkov
:contact: anisyonk@cern.ch
:date: January 2018
"""

import os
import json
import random

from pilot.util.config import config
from .dataloader import DataLoader, merge_dict_data

import logging
logger = logging.getLogger(__name__)


class ExtInfoProvider(DataLoader):
    """
        Information provider to retrive data from external source(s)
        (e.g. AGIS, PanDA, CVMFS)
    """

    def __init__(self, cache_time=60):
        """
            :param cache_time: Default cache time in seconds
        """

        self.cache_time = cache_time

    @classmethod
    def load_schedconfig_data(self, pandaqueues=[], priority=[], cache_time=60):
        """
        Download the (AGIS-extended) data associated to PandaQueue from various sources (prioritized).
        Try to get data from CVMFS first, then AGIS or from Panda JSON sources (not implemented).

        For the moment PanDA source does not provide the full schedconfig description

        :param pandaqueues: list of PandaQueues to be loaded
        :param cache_time: Default cache time in seconds.
        :return:
        """

        pandaqueues = sorted(set(pandaqueues))

        cache_dir = config.Information.cache_dir
        if not cache_dir:
            cache_dir = os.environ.get('PILOT_HOME', '.')

        cric_url = getattr(config.Information, 'queues_url', None) or 'https://atlas-cric.cern.ch/cache/schedconfig/{pandaqueue}.json'
        cric_url = cric_url.format(pandaqueue=pandaqueues[0] if len(pandaqueues) == 1 else 'pandaqueues')
        cvmfs_path = self.get_cvmfs_path(config.Information.queues_cvmfs, 'cric_pandaqueues.json')

        sources = {'CVMFS': {'url': cvmfs_path,
                             'nretry': 1,
                             'fname': os.path.join(cache_dir, 'agis_schedconf.cvmfs.json')},
                   'CRIC': {'url': cric_url,
                            'nretry': 3,
                            'sleep_time': lambda: 15 + random.randint(0, 30),  ## max sleep time 45 seconds between retries
                            'cache_time': 3 * 60 * 60,  # 3 hours
                            'fname': os.path.join(cache_dir, 'agis_schedconf.agis.%s.json' % (pandaqueues[0] if len(pandaqueues) == 1 else 'pandaqueues'))},
                   'LOCAL': {'url': os.environ.get('LOCAL_AGIS_SCHEDCONF'),
                             'nretry': 1,
                             'cache_time': 3 * 60 * 60,  # 3 hours
                             'fname': os.path.join(cache_dir, getattr(config.Information, 'queues_cache', None) or 'agis_schedconf.json')},
                   'PANDA': None  ## NOT implemented, FIX ME LATER
                   }

        pilot_user = os.environ.get('PILOT_USER', 'generic').lower()
        user = __import__('pilot.user.%s.setup' % pilot_user, globals(), locals(), [pilot_user], 0)
        queuedata_source_priority = user.get_schedconfig_priority()
        priority = priority or queuedata_source_priority
        logger.debug(f'schedconfig priority={priority}')

        return self.load_data(sources, priority, cache_time)

    @staticmethod
    def get_cvmfs_path(url, fname):
        """
        Return a proper path for cvmfs.

        :param url: URL (string).
        :param fname: file name for CRIC JSON (string).
        :return: cvmfs path (string).
        """

        if url:
            cvmfs_path = url.replace('CVMFS_PATH', os.environ.get('ATLAS_SW_BASE', '/cvmfs'))
        else:
            cvmfs_path = '%s/atlas.cern.ch/repo/sw/local/etc/%s' % (os.environ.get('ATLAS_SW_BASE', '/cvmfs'), fname)

        return cvmfs_path

    @classmethod
    def load_queuedata(self, pandaqueue, priority=[], cache_time=60):
        """
        Download the queuedata from various sources (prioritized).
        Try to get data from PanDA, CVMFS first, then AGIS

        This function retrieves only min information of queuedata provided by PanDA cache for the moment.

        :param pandaqueue: PandaQueue name
        :param cache_time: Default cache time in seconds.
        :return:
        """

        if not pandaqueue:
            raise Exception('load_queuedata(): pandaqueue name is not specififed')

        pandaqueues = [pandaqueue]

        cache_dir = config.Information.cache_dir
        if not cache_dir:
            cache_dir = os.environ.get('PILOT_HOME', '.')

        def jsonparser_panda(c):
            dat = json.loads(c)
            if dat and isinstance(dat, dict) and 'error' in dat:
                raise Exception('response contains error, data=%s' % dat)
            return {pandaqueue: dat}

        queuedata_url = (os.environ.get('QUEUEDATA_SERVER_URL') or getattr(config.Information, 'queuedata_url', '')).format(**{'pandaqueue': pandaqueues[0]})
        cric_url = getattr(config.Information, 'queues_url', None)
        cric_url = cric_url.format(pandaqueue=pandaqueues[0] if len(pandaqueues) == 1 else 'pandaqueues')
        cvmfs_path = self.get_cvmfs_path(getattr(config.Information, 'queuedata_cvmfs', None), 'cric_pandaqueues.json')

        sources = {'CVMFS': {'url': cvmfs_path,
                             'nretry': 1,
                             'fname': os.path.join(cache_dir, 'agis_schedconf.cvmfs.json')},
                   'CRIC': {'url': cric_url,
                            'nretry': 3,
                            'sleep_time': lambda: 15 + random.randint(0, 30),  # max sleep time 45 seconds between retries
                            'cache_time': 3 * 60 * 60,  # 3 hours
                            'fname': os.path.join(cache_dir, 'agis_schedconf.agis.%s.json' % (pandaqueues[0] if len(pandaqueues) == 1 else 'pandaqueues'))},
                   'LOCAL': {'url': None,
                             'nretry': 1,
                             'cache_time': 3 * 60 * 60,  # 3 hours
                             'fname': os.path.join(cache_dir, getattr(config.Information, 'queuedata_cache', None) or 'queuedata.json'),
                             'parser': jsonparser_panda
                             },
                   'PANDA': {'url': queuedata_url,
                             'nretry': 3,
                             'sleep_time': lambda: 15 + random.randint(0, 30),  # max sleep time 45 seconds between retries
                             'cache_time': 3 * 60 * 60,  # 3 hours,
                             'fname': os.path.join(cache_dir, getattr(config.Information, 'queuedata_cache', None) or 'queuedata.json'),
                             'parser': jsonparser_panda
                             }
                   }

        pilot_user = os.environ.get('PILOT_USER', 'generic').lower()
        user = __import__('pilot.user.%s.setup' % pilot_user, globals(), locals(), [pilot_user], 0)
        queuedata_source_priority = user.get_queuedata_priority()
        priority = priority or queuedata_source_priority
        logger.debug(f'queuedata priority={priority}')

        return self.load_data(sources, priority, cache_time)

    @classmethod
    def load_storage_data(self, ddmendpoints=[], priority=[], cache_time=60):
        """
        Download DDM Storages details by given name (DDMEndpoint) from various sources (prioritized).
        Unless specified as an argument in the function call, the prioritized list will be read from the user plug-in.

        :param pandaqueues: list of PandaQueues to be loaded
        :param cache_time: Default cache time in seconds.
        :return: dict of DDMEndpoint settings by DDMendpoint name as a key
        """

        ddmendpoints = sorted(set(ddmendpoints))

        cache_dir = config.Information.cache_dir
        if not cache_dir:
            cache_dir = os.environ.get('PILOT_HOME', '.')

        # list of sources to fetch ddmconf data from
        _storagedata_url = os.environ.get('STORAGEDATA_SERVER_URL', '')
        storagedata_url = _storagedata_url if _storagedata_url else getattr(config.Information, 'storages_url', None)
        cvmfs_path = self.get_cvmfs_path(config.Information.storages_cvmfs, 'cric_ddmendpoints.json')
        sources = {'USER': {'url': storagedata_url,
                            'nretry': 3,
                            'sleep_time': lambda: 15 + random.randint(0, 30),  ## max sleep time 45 seconds between retries
                            'cache_time': 3 * 60 * 60,  # 3 hours
                            'fname': os.path.join(cache_dir, 'agis_ddmendpoints.agis.%s.json' %
                                                  ('_'.join(ddmendpoints) or 'ALL'))},
                   'CVMFS': {'url': cvmfs_path,
                             'nretry': 1,
                             'fname': os.path.join(cache_dir, getattr(config.Information, 'storages_cache', None) or 'agis_ddmendpoints.json')},
                   'CRIC': {'url': (getattr(config.Information, 'storages_url', None) or 'https://atlas-cric.cern.ch/cache/ddmendpoints.json'),
                            'nretry': 3,
                            'sleep_time': lambda: 15 + random.randint(0, 30),
                            ## max sleep time 45 seconds between retries
                            'cache_time': 3 * 60 * 60,
                            # 3 hours
                            'fname': os.path.join(cache_dir, 'agis_ddmendpoints.agis.%s.json' %
                                                  ('_'.join(ddmendpoints) or 'ALL'))},
                   'LOCAL': {'url': None,
                             'nretry': 1,
                             'cache_time': 3 * 60 * 60,  # 3 hours
                             'fname': os.path.join(cache_dir, getattr(config.Information, 'storages_cache', None) or 'agis_ddmendpoints.json')},
                   'PANDA': None  ## NOT implemented, FIX ME LATER if need
                   }

        pilot_user = os.environ.get('PILOT_USER', 'generic').lower()
        user = __import__('pilot.user.%s.setup' % pilot_user, globals(), locals(), [pilot_user], 0)
        ddm_source_priority = user.get_ddm_source_priority()
        priority = priority or ddm_source_priority
        logger.debug(f'storage data priority={priority}')

        return self.load_data(sources, priority, cache_time)

    def resolve_queuedata(self, pandaqueue, schedconf_priority=None):
        """
            Resolve final full queue data details
            (primary data provided by PanDA merged with overall queue details from AGIS)

            :param pandaqueue: name of PandaQueue
            :return: dict of settings for given PandaQueue as a key
        """

        # load queuedata (min schedconfig settings)
        master_data = self.load_queuedata(pandaqueue, cache_time=self.cache_time)  ## use default priority

        # load full queue details
        r = self.load_schedconfig_data([pandaqueue], priority=schedconf_priority, cache_time=self.cache_time)

        # merge
        return merge_dict_data(r, master_data)

    def resolve_storage_data(self, ddmendpoints=[]):
        """
            Resolve final DDM Storages details by given names (DDMEndpoint)

            :param ddmendpoints: list of ddmendpoint names
            :return: dict of settings for given DDMEndpoint as a key
        """

        # load ddmconf settings
        return self.load_storage_data(ddmendpoints, cache_time=self.cache_time)  ## use default priority
