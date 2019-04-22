# -*- coding: utf-8 -*-

"""Test Verify Checksum Job in Archivematica.

Tests for the verify checksum Job in Archivematica which makes calls out to the
hashsum checksum utilities. We need to ensure that the output of the tool is
mapped consistently to something that can be understood by users when
debugging their preservation workflow.
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

from __future__ import unicode_literals
import os
import subprocess
import sys

import pytest

THIS_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.append(os.path.abspath(os.path.join(THIS_DIR, "../lib/clientScripts")))

from job import Job
from verify_checksum import Hashsum, NoHashCommandAvailable


class TestHashsum(object):
    """Hashsum test runner object."""

    @staticmethod
    def setup_hashsum(path, job):
        """Return a hashsum instance to calling functions and perform any
        other additional setup as necessary.
        """
        return Hashsum(path, job)

    def test_invalid_initialisation(self):
        """Test that we don't return a Hashsum object if there isn't a tool
        configured to work with the file path provided.
        """
        try:
            Hashsum("checksum.invalid_hash")
            assert False
        except NoHashCommandAvailable:
            assert True

    @pytest.mark.parametrize(
        "fixture",
        [
            ("metadata/checksum.md5", None),
            ("metadata/checksum.sha1", None),
            ("metadata/checksum.sha256", None),
            ("metadata/checksum_md5", False),
            ("metadata/checksum_sha1", False),
            ("metadata/checksum_sha256", False),
        ],
    )
    def test_valid_init(self, fixture):
        """Test that we don't return a Hashsum object if there isn't a tool
        configured to work with the file path provided.
        """
        try:
            assert isinstance(Hashsum(fixture[0]), Hashsum)
        except NoHashCommandAvailable:
            assert fixture[1] is False

    def test_provenance_string(self, mocker):
        """Test to ensure that the string output to the PREMIS event for this
        microservice Job is consistent with what we're expecting. Provenance
        string includes the command called, plus the utility's version string.
        """
        hash_file = "metadata/checksum.md5"
        hashsum = self.setup_hashsum(hash_file, Job("stub", "stub", ["", ""]))
        version_string = [
            "md5sum (GNU coreutils) 8.28",
            "Copyright (C) 2017 Free Software Foundation, Inc.",
        ]
        mock = mocker.patch.object(hashsum, "_call", return_value=version_string)
        assert hashsum.version() == "md5sum (GNU coreutils) 8.28"
        mock.assert_called_once_with("--version")
        mocker.patch.object(
            hashsum,
            "command_called",
            (hashsum.COMMAND,) + ("-c", "--strict", hash_file),
        )
        expected_provenance = 'program="md5sum -c --strict metadata/checksum.md5"; version="md5sum (GNU coreutils) 8.28"'
        provenance_output = hashsum.get_command_detail()
        assert provenance_output == expected_provenance

    def test_compare_hashes_failed(self, mocker):
        """Ensure we get consistent output when the checksum comparison fails.
        """
        job = Job("stub", "stub", ["", ""])
        hash_file = "metadata/checksum.sha256"
        hashsum = self.setup_hashsum(hash_file, job)
        toolname = "sha256sum"
        output_string = (
            b"objects/file1.bin: OK\n"
            b"objects/file2.bin: FAILED\n"
            b"objects/nested/\xe3\x83\x95\xe3\x82\xa1\xe3\x82\xa4\xe3\x83\xab"
            b"3.bin: FAILED\n"
            b"objects/readonly.file: FAILED open or read"
        )
        exception_string = (
            "sha256: comparison exited with status: 1 check the file's formatting\n"
            "sha256: objects/file2.bin: FAILED\n"
            "sha256: objects/nested/ファイル3.bin: FAILED\n"
            "sha256: objects/readonly.file: FAILED open or read"
        )
        mock = mocker.patch.object(hashsum, "_call", return_value=output_string)
        mocker.patch.object(hashsum, "count_and_compare_lines", return_value=True)
        mock.side_effect = subprocess.CalledProcessError(
            returncode=1, cmd=toolname, output=output_string
        )
        ret = hashsum.compare_hashes(hash_file, "")
        mock.assert_called_once_with("-c", "--strict", hash_file)
        assert ret == 1
        print(job.get_stderr().decode("utf8").strip())
        print(exception_string)
        assert job.get_stderr().decode("utf8").strip() == exception_string

    def test_compare_hashes_w_bad_files(self, mocker):
        """Ensure that the formatting of errors is consistent if improperly
        formatted files are provided to hashsum.
        """
        hash_file = "metadata/checksum.sha1"
        job = Job("stub", "stub", ["", ""])
        hashsum = self.setup_hashsum(hash_file, job)
        toolname = "sha1sum"
        no_proper_output = (
            b"sha1sum: metadata/checksum.sha1: no properly formatted SHA1 "
            b"checksum lines found"
        )
        except_string_no_proper_out = (
            "sha1: comparison exited with status: 1 check the file's formatting\n"
            "sha1: sha1sum: metadata/checksum.sha1: no properly formatted "
            "SHA1 checksum lines found"
        )
        improper_formatting = b"sha1sum: WARNING: 1 line is improperly formatted"
        except_string_improper_format = (
            "sha1: comparison exited with status: 1 check the file's formatting\n"
            "sha1: sha1sum: WARNING: 1 line is improperly formatted"
        )
        mock = mocker.patch.object(hashsum, "_call", return_value=no_proper_output)
        mocker.patch.object(hashsum, "count_and_compare_lines", return_value=True)
        mock.side_effect = subprocess.CalledProcessError(
            returncode=1, cmd=toolname, output=no_proper_output
        )
        objects_path = ""
        ret = hashsum.compare_hashes(hash_file, objects_path)
        mock.assert_called_once_with("-c", "--strict", hash_file)
        assert job.get_stderr().decode("utf8").strip() == except_string_no_proper_out
        assert ret == 1
        # Flush job.error as it isn't flushed automatically.
        job.error = ""
        mock = mocker.patch.object(hashsum, "_call", return_value=improper_formatting)
        mock.side_effect = subprocess.CalledProcessError(
            returncode=1, cmd="sha1sum", output=improper_formatting
        )
        objects_path = ""
        ret = hashsum.compare_hashes(hash_file, objects_path)
        assert job.get_stderr().decode("utf8").strip() == except_string_improper_format
        mock.assert_called_once_with("-c", "--strict", hash_file)
        assert ret == 1

    def test_line_comparison_fail(self, mocker):
        """If the checksum line and object comparison function fails then
        we want to return early and _call shouldn't be called.
        """
        hash_file = "metadata/checksum.sha1"
        hashsum = self.setup_hashsum(hash_file, Job("stub", "stub", ["", ""]))
        toolname = "sha1sum"
        mock = mocker.patch.object(hashsum, "_call", return_value=None)
        mocker.patch.object(hashsum, "count_and_compare_lines", return_value=False)
        mock.side_effect = subprocess.CalledProcessError(
            returncode=1, cmd=toolname, output=None
        )
        ret = hashsum.compare_hashes(hash_file, "")
        mock.assert_not_called()
        assert ret == 1

    @pytest.mark.parametrize(
        "fixture",
        [
            ("checksum.md5", "md5"),
            ("checksum.sha1", "sha1"),
            ("checksum.sha256", "sha256"),
            ("checksum_md5", "checksum_md5"),
            ("checksum_sha1", "checksum_sha1"),
            ("checksum_sha256", "checksum_sha256"),
        ],
    )
    def test_get_ext(self, fixture):
        """get_ext helps to format usefully."""
        assert Hashsum.get_ext(fixture[0]) == fixture[1]

    @staticmethod
    def test_decode_and_version_string():
        """Test that we can separate the version and license information
        correctly from {command} --version.
        """
        version_string = (
            b"sha256sum (GNU coreutils) 8.28\n"
            b"Copyright (C) 2017 Free Software Foundation, Inc."
        )
        assert len(Hashsum._decode(version_string)[0]) > 1
        assert Hashsum._decode(version_string)[0] == "sha256sum (GNU coreutils) 8.28"
