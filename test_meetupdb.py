"""
Nose tests for flask_main.py
"""
# Date handling 
import arrow # Replacement for datetime, based on moment.js
import datetime # But we still need time
from dateutil import tz  # For interpreting local times

# modules we are testing
from meetupdb import *

"""
The testing done here is focused on my modifications to agenda.py since
the baseline code is heavily tested within the file by the original author.
"""

def test_getDBCollection():
    """
    Attempt to open a connection to our db collection.
    Username/password, dbname, and collection name are all pulled
    from config files.

    All further functions in meetupdb use getDBCollection, none will 
    work if this one test fails.
    """

    assert getDBCollection != None

def test_addMeetUp():
    """
    Attempt to add a new MeetUp into the collection

    """
    descr = "TestMeetUp"
    sdate = arrow.get("01/01/2017", "MM/DD/YYYY").replace(tzinfo=tz.tzlocal()).isoformat()
    edate = arrow.get("01/07/2017", "MM/DD/YYYY").replace(tzinfo=tz.tzlocal()).isoformat()
    stime = arrow.get("01/01/2017 9:00am", "MM/DD/YYYY h:mma").replace(tzinfo=tz.tzlocal()).isoformat()
    etime = arrow.get("01/07/2017 5:00pm", "MM/DD/YYYY h:mma").replace(tzinfo=tz.tzlocal()).isoformat()

    global meetupid 
    meetupid = addMeetUp(descr,sdate,edate,stime,etime)

    #addMeetUp returns an uuid that is used to identify records.
    assert meetupid != None

def test_getMeetUp():
    """
    Using the meetupid from test_addMeetUp() try and retrieve that db record.
    """
    
    #getMeetUp returns None when nothing is found
    global record 
    record = getMeetUp(meetupid)
    assert record != None
    assert record["count"] == 0


def test_updateBusyTimes():
    """
    Using the meetupid from test_addMeetUp() try and retrieve that db record.
    """
    
    busytimes = [[{"descr":"test1","start":"2017-01-01T10:00:00-8:00","end":"2017-01-01T12:00:00-8:00"},
                  {"descr":"test2","start":"2017-01-01T15:00:00-8:00","end":"2017-01-01T14:00:00-8:00"}],
                 [{"descr":"test3","start":"2017-01-01T10:00:00-8:00","end":"2017-01-01T12:00:00-8:00"},
                  {"descr":"test4","start":"2017-01-01T10:00:00-8:00","end":"2017-01-01T12:00:00-8:00"}]]

    updateBusyTimes(meetupid, busytimes)

    record = getMeetUp(meetupid)
    assert record != None
    assert record["count"] == 1
    assert record["busytime"] == busytimes

def test_deleteMeetUp():
    """
    Using the meetupid from test_addMeetUp() try and retrieve that db record.
    """

    deleteMeetUp(meetupid)
    record = getMeetUp(meetupid)

    assert record == None