#!/usr/bin/env python2
# -*- coding: utf8

"""pid_declaration.py

Given an identifiers.json file, supplying third-party persistent identifiers
(PIDS), such as handle (hdl) or doi, identifiers; associate those identifiers
with the objects in the transfer, so be translated to PREMIS objects in the
AIP METS.
"""
from __future__ import unicode_literals
from functools import wraps
import json
import os
import sys

def concurrent_instances(): return 1


class DeclarePIDsException(Exception):
    """Exception to raise if METS validation fails."""


class DeclarePIDsWarning(Exception):
    """Exception to raise when we haven't a"""
    exit_code = 0


class DeclarePIDs(object):
    """Class to wrap PID declaration features and provide some mechanism of
    recording state.
    """

    def __init__(self, job):
        """Class constructor"""
        self.job = job

    def exit_on_known_exception(func):
        """Decorator to allows us to raise an exception but still exit-zero when
        the exception is cleaner to return than ad-hoc integer values.
        """
        @wraps(func)
        def wrapped(*_args, **kwargs):
            try:
                func(*_args, **kwargs)
            except (DeclarePIDsWarning) as err:
                return err.exit_code
        return wrapped

    @exit_on_known_exception
    def pid_declaration(self, metadata_dir):
        """Process an identifiers.json file and add its values to the correct
        models in the database.
        """
        identifiers = os.path.join(metadata_dir, "identifiers.json")
        try:
            with open(identifiers, 'r') as identifiers_file:
                # TODO: test for an invalid JSON file.
                json.load(identifiers_file)
        except (IOError, AttributeError) as err:
            self.job.pyprint("No identifiers.json file found:", err, file=sys.stderr)
            raise DeclarePIDsWarning()


def call(jobs):
    """Primary entry point for this script."""
    for job in jobs:
        with job.JobContext():
            try:
                metadata_dir = job.args[1]
            except IndexError as err:
                job.pyprint("Cannot access Job arguments:", err, file=sys.stderr)
            DeclarePIDs(job).pid_declatation(metadata_dir)
