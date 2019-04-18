#!/usr/bin/env python
# -*- coding: utf-8 -*-

"""Unit tests for the various components associated with PID (persistent
identifier binding and declaration in Archivematica.

The tests in this module cover both the two bind_pid(s) microservice jobs but
also limited unit testing in create_mets_v2 (AIP METS generation).
"""
from __future__ import unicode_literals
from itertools import chain
import os
import sys

from django.core.management import call_command

from job import Job
from main.models import Directory, File, SIP, DashboardSetting

import pytest
import vcr


THIS_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.append(os.path.abspath(os.path.join(THIS_DIR, "../lib/clientScripts")))
sys.path.append(
    os.path.abspath(os.path.join(THIS_DIR, "../../archivematicaCommon/lib"))
)

vcr_cassettes = vcr.VCR(
    cassette_library_dir=os.path.join(THIS_DIR, "fixtures", "vcr_cassettes"),
    path_transformer=vcr.VCR.ensure_suffix(".yaml"),
)

import bind_pid
import bind_pids
import create_mets_v2
import namespaces as ns


class TestPIDComponents(object):
    """PID binding and declaration test runner class."""

    job = Job("stub", "stub", [])
    identifier_types = ("UUID", "hdl", "URI")

    # Information we'll refer back to in our tests.
    package_uuid = "cb5ebaf5-beda-40b4-8d0c-fefbd546b8de"
    do_not_bind = "Configuration indicates that PIDs should not be bound."
    bound_uri = "http://195.169.88.240:8017/12345/"
    bound_hdl = "12345/"

    @pytest.fixture(scope="class")
    def django_db_setup(self, django_db_setup, django_db_blocker):
        # Load our fixtures.
        pid_dir = "pid_binding"
        fixture_files = [
            "sip.json",
            "dashboard_settings.json",
            "transfer.json",
            "files.json",
            "directories.json",
        ]
        fixtures = []
        for fixture in fixture_files:
            fixtures.append(os.path.join(THIS_DIR, "fixtures", pid_dir, fixture))
        with django_db_blocker.unblock():
            for fixture in fixtures:
                call_command("loaddata", fixture)

    def test_bind_pids_not_set(self, caplog):
        """Test the output of the code without any args.

        bind_pids should return zero, for no-error. It won't have performed
        any actions on the database either.
        """
        assert (
            bind_pids.main(self.job, None, None, None) == 0
        ), "Return from bind_pids is something other than expected."
        assert (
            caplog.records[0].message == self.do_not_bind
        ), "Captured logging message from bind_pids is different than anticipated."
        assert (
            bind_pids.main(self.job, None, None, False) == 0
        ), "Return from bind_pids is something other than expected."
        assert (
            caplog.records[1].message == self.do_not_bind
        ), "Captured logging message from bind_pids is different than anticipated."

    @pytest.mark.django_db
    def test_bind_pids_no_config(self):
        """Test the output of the code without any args.

        In this instance, we want bind_pids to thing that there is some
        configuration available but we haven't provided any other information
        so we should see a non-zero status returned as an error.
        """
        assert (
            bind_pids.main(self.job, None, None, True) == 1
        ), "Incorrect return value for bind_pids with incomplete configuration."

    @pytest.mark.django_db
    def test_bind_pids(self, mocker):
        """Test the bind_pids function end-to-end and ensure that the
        result is that which is anticipated.

        The bind_pids module is responsible for binding persistent identifiers
        to the SIP and the SIP's directories so we only test that here.
        """
        identifiers_count = 2
        dir_count = 2
        # We might want to return a unique accession number, but we can also
        # test here using the package UUID, the function's fallback position.
        mocker.patch.object(
            bind_pids, "_get_unique_acc_no", return_value=self.package_uuid
        )
        with vcr_cassettes.use_cassette(
            "test_bind_pids_to_sip_and_dirs.yaml"
        ) as cassette:
            # Primary entry-point for the bind_pids microservice job.
            bind_pids.main(self.job, self.package_uuid, "", True)
        assert cassette.all_played
        # Retrieve our SIP model again.
        sip_mdl = SIP.objects.filter(uuid=self.package_uuid).first()
        assert (
            len(sip_mdl.identifiers.all()) == identifiers_count
        ), "Number of SIP identifiers is greater than anticipated"
        dirs = Directory.objects.filter(sip=self.package_uuid).all()
        assert (
            len(dirs) == dir_count
        ), "Number of directories is something other than anticipated"
        for mdl in chain(dirs, (sip_mdl,)):
            bound = [(idfr.type, idfr.value) for idfr in mdl.identifiers.all()]
            assert len(bound) == identifiers_count
            pid_types = []
            for pid in bound:
                pid_types.append(pid[0])
            assert (
                "hdl" in pid_types
            ), "An expected hdl persistent identifier isn't in the result set"
            assert "URI" in pid_types, "An expected URI isn't in the result set"
            bound_hdl = "{}{}".format(self.bound_hdl, mdl.pk)
            bound_uri = "{}{}".format(self.bound_uri, mdl.pk)
            pids = []
            for pid in bound:
                pids.append(pid[1])
            assert (
                bound_hdl in pids
            ), "Handle PID bound to SIP is something other than anticipated"
            assert (
                bound_uri in pids
            ), "URI PID bound to SIP is something other than anticipated"
            # Once we know we're creating identifiers as expected, test to ensure
            # that those identifiers are output as expected by the METS functions
            # doing that work.
            dir_dmd_sec = create_mets_v2.getDirDmdSec(mdl, "")
            id_type = dir_dmd_sec.xpath(
                "//premis:objectIdentifierType", namespaces={"premis": ns.premisNS}
            )
            id_value = dir_dmd_sec.xpath(
                "//premis:objectIdentifierValue", namespaces={"premis": ns.premisNS}
            )
            id_types = [item.text for item in id_type]
            id_values = [item.text for item in id_value]
            identifiers_dict = dict(zip(id_types, id_values))
            for key in identifiers_dict.keys():
                assert key in self.identifier_types
            assert bound_hdl in identifiers_dict.values()
            assert bound_uri in identifiers_dict.values()

    @pytest.mark.django_db
    def test_bind_pids_no_confid(self, caplog):
        """Test the output of the code when bind_pids is set to True but there
        are no handle settings in the Dashboard. Conceivably then the dashboard
        settings could be in-between two states, complete and not-complete,
        here we test for the two opposites on the assumption they'll be the
        most visible errors to the user.
        """
        DashboardSetting.objects.filter(scope="handle").delete()
        try:
            bind_pids.main(self.job, self.package_uuid, "", True)
        except KeyError as err:
            assert "handle_archive_pid_source" in err.message

    def test_bind_pid_not_set(self, caplog):
        """Ensure that the behavior of bind_pid is as anticipated when we're
        not asking it to bind_pids, i.e. it doesn't runaway and try and bind
        anyway, or something that isn't there.
        """
        assert (
            bind_pid.main(self.job, None, None) == 0
        ), "Return from bind_pid is something other than expected"
        assert (
            caplog.records[0].message == self.do_not_bind
        ), "Captured logging message from bind_pid is different than anticipated"
        assert (
            bind_pid.main(self.job, None, False) == 0
        ), "Return from bind_pid is something other than expected"
        assert (
            caplog.records[1].message == self.do_not_bind
        ), "Captured logging message from bind_pid is different than anticipated"

    @pytest.mark.django_db
    def test_bind_pid(self, mocker):
        """Test the bind_pid function end-to-end and ensure that the
        result is that which is anticipated.

        The bind_pid module is responsible for binding persistent identifiers
        to the SIP's files and so we test for that here.
        """
        file_count = 4
        files = File.objects.filter(sip=self.package_uuid).all()
        assert (
            len(files) is file_count
        ), "Number of files returned from package is different from that anticipated"
        for file_ in files:
            with vcr_cassettes.use_cassette("test_bind_pid_to_files.yaml") as cassette:
                # Primary entry point for bind_pid microservice job.
                bind_pid.main(self.job, file_.pk, True)
        assert cassette.all_played
        for count, file_mdl in enumerate(files):
            bound = {idfr.type: idfr.value for idfr in file_mdl.identifiers.all()}
            assert (
                "hdl" in bound
            ), "An expected hdl persistent identifier isn't in the result set"
            assert "URI" in bound, "An expected URI isn't in the result set"
            bound_hdl = "{}{}".format(self.bound_hdl, file_mdl.pk)
            bound_uri = "{}{}".format(self.bound_uri, file_mdl.pk)
            assert bound.get("hdl") == bound_hdl
            assert bound.get("URI") == bound_uri
            # Then test to see that the PREMIS objects are created correctly in
            # the AIP METS generation code.
            file_level_premis = create_mets_v2.create_premis_object(file_mdl.pk)
            id_type = file_level_premis.xpath(
                "//premis:objectIdentifierType", namespaces={"premis": ns.premisNS}
            )
            id_value = file_level_premis.xpath(
                "//premis:objectIdentifierValue", namespaces={"premis": ns.premisNS}
            )
            id_types = [item.text for item in id_type]
            id_values = [item.text for item in id_value]
            identifiers_dict = dict(zip(id_types, id_values))
            for key in identifiers_dict.keys():
                assert key in self.identifier_types
            assert bound_hdl in identifiers_dict.values()
            assert bound_uri in identifiers_dict.values()
        assert (
            count + 1
        ) is file_count, (
            "The number of handles minted does not match the number of files."
        )

    @pytest.mark.django_db
    def test_bind_pid_no_settings(self, caplog):
        """Test the output of the code when bind_pids is set to True but there
        are no handle settings in the Dashboard. Conceivably then the dashboard
        settings could be in-between two states, complete and not-complete,
        here we test for the two opposites on the assumption they'll be the
        most visible errors to the user.
        """
        file_count = 4
        DashboardSetting.objects.filter(scope="handle").delete()
        files = File.objects.filter(sip=self.package_uuid).all()
        assert len(files), "Files haven't been retrieved from the model as expected"
        for file_ in files:
            bind_pid.main(self.job, file_.pk, True)
        for file_number in range(file_count):
            assert (
                caplog.records[file_number].message
                == "A value for parameter naming_authority is required"
            )
