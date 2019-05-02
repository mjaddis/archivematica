#!/usr/bin/env python

import django
django.setup()
# dashboard
from fpr.models import FPRule
from main.models import FileFormatVersion, Transfer, File, Event


def is_extractable(f):
    """
    Returns True if this file can be extracted, False otherwise.
    """
    # Check if an extract FPRule exists
    try:
        format = f.fileformatversion_set.get().format_version
    except FileFormatVersion.DoesNotExist:
        return False

    extract_rules = FPRule.active.filter(purpose="extract", format=format)
    if extract_rules:
        return True
    else:
        return False


def already_extracted(f):
    """
    Returns True if this package has already been extracted, False otherwise.
    """
    # Look for files in a directory that starts with the package name
    # files = File.objects.filter(transfer=f.transfer, currentlocation__startswith=f.currentlocation, removedtime__isnull=True).exclude(uuid=f.uuid)
    # Check for unpacking events that reference the package
    # if Event.objects.filter(file_uuid__in=files, event_type='unpacking', event_detail__contains=f.currentlocation).exists():
    #    return True


    # When a package is extracted the files from the package will be placed in new directory and will have entries added in the Events table (eventType = 'unpacking')
    # The fileUUID in the Events table is the newly created file in the extracted directory.  
    # The eventDetail references the UUID of the file it was extracted from, i.e. the UUID of the package.
    # Therefore, a test of whether a package has been extracted is to look for entries in the Events table that reference the UUID of the package.
    # However, in some cases, an effort to extract a package might not produce any files.  
    # In this case, the package would not be classified as extracted and extraction will be attempted again.
    # To catch this, the extraction task should add an entry to the Events table to say that extraction was attempted but with no files produced.  
    # If this references the UUID of the package in eventDetail then the same test below can be used to detect that package extraction has been done.

    if Event.objects.filter(event_type='unpacking', event_detail__contains=f.uuid).exists():
        return True
    return False


def main(job, sip_uuid):
    transfer = Transfer.objects.get(uuid=sip_uuid)
    for f in transfer.file_set.filter(removedtime__isnull=True).iterator():
        if is_extractable(f) and not already_extracted(f):
            job.pyprint(f.currentlocation, 'is extractable and has not yet been extracted.')
            return 0
    job.pyprint('No extractable files found.')
    return 1


def call(jobs):
    for job in jobs:
        with job.JobContext():
            job.set_status(main(job, job.args[1]))
