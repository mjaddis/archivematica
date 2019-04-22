# -*- coding: utf-8 -*-

"""Verify Checksum Job

Archivematica wraps the hashsum utility to verify checksums provided to the
system as part of a transfer, e.g. checksum.md5 in the transfer metadata
folder.
"""

# This file is part of Archivematica.
#
# Copyright 2010-2017 Artefactual Systems Inc. <http://artefactual.com>
#
# Archivematica is free software: you can redistribute it and/or modify
# it under the terms of the GNU Affero General Public License as published by
# the Free Software Foundation, either version 3 of the License, or
# (at your option) any later version.
#
# Archivematica is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with Archivematica.  If not, see <http://www.gnu.org/licenses/>.

from __future__ import print_function, unicode_literals

import datetime
import os
import subprocess
import sys
from uuid import uuid4

import django
from django.db import transaction

django.setup()
from main.models import File

from custom_handlers import get_script_logger
from databaseFunctions import insertIntoEvents


def concurrent_instances():
    """Function docstring. N.B. Delete me."""
    return 1


logger = get_script_logger("archivematica.mcp.client.compare_hashes")


class NoHashCommandAvailable(Exception):
    """Provide feedback to the user if the checksum command cannot be found
    for the provided checksum file.
    """


class PREMISFailure(Exception):
    """Provide feedback to the user if there is a problem writing PREMIS event
    information to the database.
    """


class Hashsum(object):
    """Class to capture various functions around calling Hashsum as a mechanism
    for comparing user-supplied checksums in Archivematica.
    """

    COMMANDS = {
        "metadata/checksum.md5": "md5sum",
        "metadata/checksum.sha1": "sha1sum",
        "metadata/checksum.sha256": "sha256sum",
        "metadata/checksum.sha512": "sha512sum",
        "metadata/checksum.b2": "b2sum",
    }

    OKAY_STRING = ": OK"
    FAIL_STRING = ": FAILED"
    ZERO_STRING = "no properly formatted"
    IMPROPER_STRING = "improperly formatted"
    FAILED_OPEN = ": FAILED open or read"
    EXIT_NON_ZERO = "returned non-zero exit status 1"

    def __init__(self, path, job=print):
        """Class constructor."""
        try:
            self.COMMAND = self.COMMANDS[path]
            self.job = job
            self.command_called = None
        except KeyError:
            raise NoHashCommandAvailable()

    def _call(self, *args):
        """Make the call to Python subprocess and record the command being
        called.
        """
        self.command_called = (self.COMMAND,) + args
        return self._decode(subprocess.check_output(self.command_called))

    def count_and_compare_lines(self, hashfile, objectsdir):
        """Count the number of lines in a checksum file and compare with the
        number of objects being transferred. The requirement of hashsum as
        this microservice job is written is that the mapping is 1:1. There
        isn't space for an empty line at the end of the file.
        """
        lines = self._count_lines(hashfile)
        objects = self._count_files(objectsdir)
        if lines == objects:
            return True
        self.job.pyprint(
            "{}: Comparison failed with {} checksum lines and {} "
            "transfer files".format(self.get_ext(hashfile), lines, objects),
            file=sys.stderr,
        )
        return False

    def compare_hashes(self, hashfile, objectsdir):
        """Compare transfer files with the checksum file provided."""
        if not self.count_and_compare_lines(hashfile, objectsdir):
            return 1
        try:
            self._call("-c", "--strict", hashfile)
            return 0
        except subprocess.CalledProcessError as err:
            if self.EXIT_NON_ZERO in str(err):
                # Always output this on failure to capture outliers that can't
                # be easily captured parsing the error lines or state we
                # haven't observed yet.
                warn = "{}: comparison exited with status: {} check the file's formatting".format(
                    self.get_ext(hashfile), err.returncode
                )
                self.job.pyprint(warn, file=sys.stderr)
            for line in self._decode(err.output):
                if not line:
                    continue
                if line.endswith(self.OKAY_STRING):
                    continue
                if (
                    line.endswith(self.FAIL_STRING)
                    or self.ZERO_STRING in line
                    or self.IMPROPER_STRING in line
                ):
                    self.job.pyprint(
                        "{}: {}".format(self.get_ext(hashfile), line), file=sys.stderr
                    )
                if line.endswith(self.FAILED_OPEN):
                    self.job.pyprint(
                        "{}: {}".format(self.get_ext(hashfile), line), file=sys.stderr
                    )
            return err.returncode

    def version(self):
        """Return version information for the command being called."""
        try:
            return self._call("--version")[0]
        except subprocess.CalledProcessError:
            return self.COMMAND

    def get_command_detail(self):
        """Provide some way for the user to get information out of the class to
        write METS/PREMIS provenance information.
        """
        if not self.command_called:
            raise PREMISFailure()
        return 'program="{}"; version="{}"'.format(
            " ".join(self.command_called), self.version()
        )

    @staticmethod
    def _decode(out):
        """Decode string output in Py2 or Py3 and return a list of lines to be
        parsed elsewhere.
        """
        try:
            return str(out, "utf8").split("\n")
        except TypeError:
            return out.decode("utf8").split("\n")

    @staticmethod
    def get_ext(path):
        """Return the extension of the checksum file provided"""
        ext = os.path.splitext(path)[1]
        if not ext:
            return path
        return ext.replace(".", "")

    @staticmethod
    def _count_lines(path):
        """Count the number of lines in a checksum file."""
        count = 0
        with open(path) as hashfile:
            for count, _ in enumerate(hashfile):
                pass
        # Negate zero-based count.
        return count + 1

    @staticmethod
    def _count_files(path):
        """Walk the directories on a given path and count the number of files.
        """
        return sum([len(files) for _, _, files in os.walk(path)])


def write_premis_event_per_file(transfer_uuid, event_detail):
    """Write a PREMIS event for every file in the transfer on success."""
    group_type = "transfer_id"
    event_type = "fixity_check"
    event_outcome = "pass"
    # Retrieve file UUIDs from the database.
    kwargs = {"removedtime__isnull": True, group_type: transfer_uuid}
    with transaction.atomic():
        file_uuids = File.objects.filter(**kwargs).values_list("uuid")
        if not file_uuids:
            raise PREMISFailure()
        for (fileUUID,) in file_uuids:
            insertIntoEvents(
                fileUUID=fileUUID,
                eventIdentifierUUID=str(uuid4()),
                eventType=event_type,
                eventDateTime=datetime.datetime.now()
                .replace(microsecond=0)
                .isoformat(),
                eventDetail=event_detail,
                eventOutcome=event_outcome,
                eventOutcomeDetailNote="",
            )


def run_hashsum_commands(job):
    """Run hashsum commands and generate a cumulative return code."""
    transfer_dir = None
    transfer_uuid = None
    try:
        transfer_dir = job.args[1]
        transfer_uuid = job.args[2]
    except IndexError:
        logger.error("Cannot access expected module arguments: %s", job.args)
        return 1
    ret = 0
    for hashfile in Hashsum.COMMANDS:
        os.chdir(transfer_dir)
        objectsdir = "objects/"
        hashsum = None
        if os.path.exists(hashfile):
            try:
                hashsum = Hashsum(hashfile, job)
            except NoHashCommandAvailable:
                job.pyprint(
                    "Nothing to do for {}. No command available.".format(
                        Hashsum.get_ext(hashfile)
                    )
                )
                continue
        if hashsum:
            job.pyprint(
                "Comparing transfer checksums with the supplied {} file".format(
                    Hashsum.get_ext(hashfile)
                ),
                file=sys.stderr,
            )
            result = hashsum.compare_hashes(hashfile=hashfile, objectsdir=objectsdir)
            # Add to PREMIS on success only.
            if result == 0:
                job.pyprint("{}: Comparison was OK".format(Hashsum.get_ext(hashfile)))
                write_premis_event_per_file(
                    transfer_uuid=transfer_uuid,
                    event_detail=hashsum.get_command_detail(),
                )
                continue
            ret += result
    return ret


def call(jobs):
    """Primary entry point for MCP Client script."""
    current_directory = os.getcwd()
    for job in jobs:
        with job.JobContext(logger=logger):
            job.set_status(run_hashsum_commands(job))
    os.chdir(current_directory)
