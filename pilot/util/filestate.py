#!/usr/bin/env python
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
# http://www.apache.org/licenses/LICENSE-2.0
#
# Authors:
# - Paul Nilsson, paul.nilsson@cern.ch, 2022

import logging

logger = logging.getLogger(__name__)


class FileState(object):

    """
    FS = FileState(file_status={'lfns': ['LFN1.DAT', 'LFN2.DAT']})
    FS.update(lfn='LFN1.DAT', state='TRANSFERRED')
    print(FS.get_file_states())
    """

    _file_states = {}
    _lfns = []
    _state_list = ['NOT_YET_TRANSFERRED', 'TRANSFER_IN_PROGRESS', 'TRANSFERRED', 'TRANSFER_FAILED']

    def __init__(self, file_states={}):
        """
        Default init function.
        """

        self._lfns = file_states.get('lfns', [])
        self.set_initial_list()

    def set_initial_list(self):
        """
        Set the initial file states list.
        """

        for lfn in self._lfns:
            self._file_states[lfn] = 'NOT_YET_TRANSFERRED'

    def get_file_states(self):
        """
        Return the current file states list.
        """

        return self._file_states

    def update(self, lfn='', state=''):
        """
        Update the state for a given LFN.
        """

        if not lfn or not state:
            logger.warning('must set lfn/state')
            return

        if state not in self._state_list:
            logger.warning(f'unknown state: {state} (must be in: {self._state_list})')
            return

        self._file_states[lfn] = state
