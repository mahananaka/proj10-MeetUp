
import flask
from flask import render_template
from flask import request
from flask import redirect
from flask import url_for
import uuid

import json
import logging

# Date handling 
import arrow # Replacement for datetime, based on moment.js
import datetime # But we still need time
from dateutil import tz  # For interpreting local times

# OAuth2  - Google library implementation for convenience
from oauth2client import client
import httplib2   # used in oauth2 flow

# Google API for services 
from apiclient import discovery

# Our own modules
from agenda import Appt, Agenda
from meetupdb import addMeetUp, getAllMeetUps, deleteMeetUp, getMeetUp, updateBusyTimes

###
# Globals
###
import CONFIG
import secrets.admin_secrets  # Per-machine secrets
import secrets.client_secrets # Per-application secrets
#  Note to CIS 322 students:  client_secrets is what you turn in.
#     You need an admin_secrets, but the grader and I don't use yours. 
#     We use our own admin_secrets file along with your client_secrets
#     file on our Raspberry Pis. 

app = flask.Flask(__name__)
app.debug=CONFIG.DEBUG
app.logger.setLevel(logging.DEBUG)
app.secret_key=CONFIG.secret_key

SCOPES = 'https://www.googleapis.com/auth/calendar.readonly'
CLIENT_SECRET_FILE = secrets.admin_secrets.google_key_file  ## You'll need this
APPLICATION_NAME = 'MeetMe class project'

#############################
#
#  Pages (routed from URLs)
#
#############################

@app.route("/")
@app.route("/index")
def index():
  app.logger.debug("Entering index")
  if 'begin_date' not in flask.session:
    init_session_values()
  flask.g.meetups = getAllMeetUps()
  return render_template('index.html')

@app.route("/make")
def make():
    app.logger.debug("Entering make")
    return render_template('make.html')

@app.route("/delete", methods=['POST'])
def delete():
    app.logger.debug("Entering delete")

    for delete in request.form: #delete each selected, delete variable holds id of db entry
      deleteMeetUp(delete)

    return flask.redirect(flask.url_for("index"))

@app.route("/getCalendars/<muID>")
def getCalendars(muID):
    ## We'll need authorization to list calendars 
    ## I wanted to put what follows into a function, but had
    ## to pull it back here because the redirect has to be a
    ## 'return' 
    
    record = getMeetUp(muID)
    if record == None:
        flask.session['meetupId'] = ''
        flask.flash("No MeetUp found for ID: {}".format(muID))
        return flask.redirect(flask.url_for('index'))

    flask.session['meetupId'] = muID
    if flask.session['meetupId'] == '':
      return flask.redirect(flask.url_for("index"))

    flask.session['begin_date'] = record['sdate']
    flask.session['end_date'] = record['edate']
    flask.session['begin_time'] = record['stime']
    flask.session['end_time'] = record['etime']

    app.logger.debug("Checking credentials for Google calendar access")
    credentials = valid_credentials()
    if not credentials:
      app.logger.debug("Redirecting to authorization")
      return flask.redirect(flask.url_for('oauth2callback'))

    gcal_service = get_gcal_service(credentials)
    app.logger.debug("Returned from get_gcal_service")
    flask.session["calendars"] = list_calendars(gcal_service)

    print(flask.session["calendars"])

    return render_template('calendars.html')

@app.route("/display", methods=['POST'])
def displayEvents():
    app.logger.debug("Entering displayEvents")
    credentials = valid_credentials()
    if not credentials:
      app.logger.debug("Redirecting to authorization")
      return flask.redirect(flask.url_for('oauth2callback'))

    gcal_service = get_gcal_service(credentials)

    events = []
    for selected in request.form:
      response = gcal_service.events().list(
                      calendarId=selected,
                      timeMin=flask.session['begin_date'],
                      timeMax=next_day(flask.session['end_date'])
                      ).execute()["items"]
      print(response)
      events = events + format_events(response)


    sorted_events = sorted(events, key=lambda e: e["start"])
    flask.session['events'] = sorted_events

    return render_template('busytimes.html')

@app.route("/addBusyTime", methods=['POST'])
def addBusyTimes():
    app.logger.debug("Entering addBusyTimes")
    
    if 'events' not in flask.session:
        app.logger.debug("Events not in session redirecting")
        return redirect(url_for('index'))

    if flask.session['meetupId'] == "":
        flask.flash("Cookie not found, are cookies enabled?")
        return flask.redirect(flask.url_for("index"))

    record = getMeetUp(flask.session['meetupId'])
    if record == None:
        flask.flash("No MeetUp found for ID: {}".format(muID))
        return flask.redirect(flask.url_for('index'))

    #All checks passed, we can add new busy times
    newTimes = flask.session['events']

    #this loop deletes removes the delkey items from newTimes
    #I found this nice simple code on Stack Overflow
    #http://stackoverflow.com/questions/1207406/remove-items-from-a-list-while-iterating
    for delkey in request.form:
        newTimes[:] = [d for d in newTimes if d.get('id') != delkey]

    #make a new list of the old busytimes and the new ones to be added
    busytimes = mergeBusyTimes(newTimes, record['busytime'], flask.session['begin_date'], flask.session['end_date'])

    #commit the busy times to the database
    updateBusyTimes(flask.session['meetupId'], sessionify(busytimes))
    
    return flask.redirect(flask.url_for('displayFreetimes', muID=flask.session['meetupId']))

@app.route("/freetime/<muID>")
def displayFreetimes(muID):
    app.logger.debug("Entering displayFreetimes")

    record = getMeetUp(muID)
    if record == None:
        flask.flash("No MeetUp found for ID: {}".format(muID))
        return flask.redirect(flask.url_for('index'))

    busytimes = record['busytime']
    freetimes = get_free_times(busytimes, record['sdate'], record['edate'], record['stime'], record['etime'])

    flask.session['free'] = sessionify(freetimes)
    flask.session['busy'] = busytimes

    return render_template('freetimes.html')

#####
#
#  Option setting:  Buttons or forms that add some
#     information into session state.  Don't do the
#     computation here; use of the information might
#     depend on what other information we have.
#   Setting an option sends us back to the main display
#      page, where we may put the new information to use. 
#
#####

@app.route('/makemeetup', methods=['POST'])
def makemeetup():
    """
    User chose a date range with the bootstrap daterange
    widget.
    """
    app.logger.debug("Entering makemeetup")  
    flask.flash("New MeetUp created")

    daterange = request.form.get('daterange')
    daterange_parts = daterange.split()

    mu_sdate = interpret_date(daterange_parts[0])
    mu_edate = interpret_date(daterange_parts[2])
    mu_stime = interpret_time(request.form.get('starttime'),"h:mma")
    mu_etime = interpret_time(request.form.get('endtime'),"h:mma")
    mu_descr = request.form.get('descr')

    addMeetUp(mu_descr,mu_sdate,mu_edate,mu_stime,mu_etime)

    app.logger.debug("Setrange parsed {} - {}  dates as {} - {}".format(
      daterange_parts[0], daterange_parts[1], 
      flask.session['begin_date'], flask.session['end_date']))
    return flask.redirect(flask.url_for("index"))

# @app.route('/setrange', methods=['POST'])
# def setrange():
#     """
#     User chose a date range with the bootstrap daterange
#     widget.
#     """
#     app.logger.debug("Entering setrange")  
#     flask.flash("Updated date and time range")

#     daterange = request.form.get('daterange')
#     daterange_parts = daterange.split()

#     flask.session['daterange'] = daterange
#     flask.session['begin_date'] = interpret_date(daterange_parts[0])
#     flask.session['end_date'] = interpret_date(daterange_parts[2])
#     flask.session['begin_time'] = interpret_time(request.form.get('starttime'),"h:mma")
#     flask.session['end_time'] = interpret_time(request.form.get('endtime'),"h:mma")

#     app.logger.debug("{},{}".format(request.form.get('starttime'),request.form.get('endtime')))
#     app.logger.debug("{},{}".format(flask.session['begin_time'],flask.session['end_time']))

#     app.logger.debug("Setrange parsed {} - {}  dates as {} - {}".format(
#       daterange_parts[0], daterange_parts[1], 
#       flask.session['begin_date'], flask.session['end_date']))
#     return flask.redirect(flask.url_for("choose"))

####
#
#   Initialize session variables 
#
####

def init_session_values():
    """
    Start with some reasonable defaults for date and time ranges.
    Note this must be run in app context ... can't call from main. 
    """
    # Default date span = tomorrow to 1 week from now
    now = arrow.now('local')     # We really should be using tz from browser
    tomorrow = now.replace(days=+1)
    nextweek = now.replace(days=+7)
    flask.session["begin_date"] = tomorrow.floor('day').isoformat()
    flask.session["end_date"] = nextweek.ceil('day').isoformat()
    flask.session["daterange"] = "{} - {}".format(
        tomorrow.format("MM/DD/YYYY"),
        nextweek.format("MM/DD/YYYY"))
    # Default time span each day, 8 to 5
    flask.session["begin_time"] = interpret_time("9am","ha")
    flask.session["end_time"] = interpret_time("5pm","ha")

def interpret_time( text, time_format="h:mma"):
    """
    Read time in a human-compatible format and
    interpret as ISO format with local timezone.
    May throw exception if time can't be interpreted. In that
    case it will also flash a message explaining accepted formats.
    """
    #time_formats = ["ha", "h:mma",  "h:mm a", "H:mm"]
    try:
        as_arrow = arrow.get(text, time_format)
        as_arrow = as_arrow.replace(tzinfo=tz.tzlocal())
        as_arrow = as_arrow.replace(year=2016) #HACK see below
        app.logger.debug("Succeeded interpreting time")
    except:
        app.logger.debug("Failed to interpret time")
        flask.flash("Time '{}' didn't match accepted formats 13:30 or 1:30pm"
              .format(text))
        raise
    return as_arrow.isoformat()
    #HACK #Workaround
    # isoformat() on raspberry Pi does not work for some dates
    # far from now.  It will fail with an overflow from time stamp out
    # of range while checking for daylight savings time.  Workaround is
    # to force the date-time combination into the year 2016, which seems to
    # get the timestamp into a reasonable range. This workaround should be
    # removed when Arrow or Dateutil.tz is fixed.
    # FIXME: Remove the workaround when arrow is fixed (but only after testing
    # on raspberry Pi --- failure is likely due to 32-bit integers on that platform)


def interpret_date( text, fmt="MM/DD/YYYY" ):
    """
    Convert text of date to ISO format used internally,
    with the local time zone.
    """
    try:
      as_arrow = arrow.get(text, fmt)
      as_arrow = as_arrow.replace(tzinfo=tz.tzlocal())
    except:
        flask.flash("Date '{}' didn't fit expected format 12/31/2001")
        raise
    return as_arrow.isoformat()

def end_of_day( text, fmt="MM/DD/YYYY"):
    """
    Convert text of date to ISO format used internally,
    with time set to end of day and the local time zone.
    """
    try:
      as_arrow = arrow.get(text, fmt)
      as_arrow = as_arrow.replace(tzinfo=tz.tzlocal(),hours=23,minutes=59,seconds=59)
    except:
        flask.flash("Date '{}' didn't fit expected format 12/31/2001")
        raise
    return as_arrow.isoformat()

####
#
#  Functions (NOT pages) that return some information
#
####

def combine_date_time(arw_date, arw_time):
    """
    Combines and arrow date and time
    """
    output = datetime.datetime.combine(arw_date.date(),arw_time.time())
    return output.replace(tzinfo=tz.tzlocal()).isoformat()

def next_day(isotext):
    """
    ISO date + 1 day (used in query to Google calendar)
    """
    as_arrow = arrow.get(isotext)
    return as_arrow.replace(days=+1).isoformat()

def same_date(x,y):
    """
    Takes two isoformated datetime objects and determines if they are the same date
    """
    x_arw = arrow.get(x)
    y_arw = arrow.get(y)

    return x_arw.date() == y_arw.date()
  
def list_calendars(service):
    """
    Given a google 'service' object, return a list of
    calendars.  Each calendar is represented by a dict.
    The returned list is sorted to have
    the primary calendar first, and selected (that is, displayed in
    Google Calendars web app) calendars before unselected calendars.
    """
    app.logger.debug("Entering list_calendars")  
    calendar_list = service.calendarList().list().execute()["items"]
    result = [ ]
    for cal in calendar_list:
        id = cal["id"]
        summary = cal["summary"]
        # Optional binary attributes with False as default
        selected = ("selected" in cal) and cal["selected"]

        result.append(
          { "id": id,
            "summary": summary,
            "selected": selected,
            })
    return sorted(result, key=cal_sort_key)

def format_events(events):
    """
    Given a google 'service' object, return a list of
    calendars.  Each calendar is represented by a dict.
    The returned list is sorted to have
    the primary calendar first, and selected (that is, displayed in
    Google Calendars web app) calendars before unselected calendars.
    """
    app.logger.debug("Entering format_events")
    result = [ ]
    for e in events:
        if("date" in e["start"]):
          start = interpret_date(e["start"]["date"],"YYYY-MM-DD")
          end = end_of_day(e["start"]["date"],"YYYY-MM-DD")
        else:
          start = e["start"]["dateTime"]
          end = e["end"]["dateTime"]

        if("transparency" in e):
          show = False
        else:
          show = True

        print(e["summary"])
        if(in_time_frame(start,end,flask.session['begin_time'],flask.session['end_time'])):
          result.append(
            { "kind": e["kind"],
              "id": e["id"],
              "summary": e["summary"],
              "start": start,
              "end": end,
              "show": show
              })

    return result

def in_time_frame(startTime, endTime, lowerbound, upperbound):
    """
    This function takes a time frame and compares to established
    session time window to see if it matters. We do this because
    the query to the google calendar api grabs everything on the
    dates in the range and we now filter down to the times that 
    matter.
    """
    print("{}, {}, {}, {}".format(startTime,endTime,lowerbound,upperbound))

    arw_lowerbound = arrow.get(lowerbound).to('local').time()
    arw_upperbound = arrow.get(upperbound).to('local').time()
    start = arrow.get(startTime).to('local').time()
    end = arrow.get(endTime).to('local').time()
    retval = False

    if(start <= arw_lowerbound and end >= arw_lowerbound): #event starts before time-frame but ends after time-frame start
        retval = True

    if(start >= arw_lowerbound and end <= arw_upperbound): #event starts and ends inside the time-frame
        retval = True

    if(start <= arw_upperbound and end >= arw_upperbound): #event starts before end of time-frame and continues past it
        retval = True

    if(start <= arw_lowerbound and end >= arw_upperbound): #event completely overlapse the time-frame
        retval = True
          
    return retval

def get_busy_free_times(events, dStart, dEnd, tStart, tEnd):
    busytimes = []
    freetimes = []
    
    begin = arrow.get(dStart)
    end = arrow.get(dEnd)
    time_begin = combine_date_time(begin, arrow.get(tStart))
    time_end = combine_date_time(begin, arrow.get(tEnd))
    i = 0

    for day in arrow.Arrow.range('day',begin,end):
      busytimes_today = Agenda()
      
      for e in events[i:]:
        if same_date(day.isoformat(), e['start']):
          busytimes_today.append(Appt.from_iso_date(e['start'],e['end'],'Busy')) #using 'Busy' because we don't want private info any further
          i = i+1

      #we have all busy times for a single day now
      #lets generate free times from busy times and and append both to their respective arrays
      timeframe = Appt.from_iso_date(time_begin,time_end,"Free Time")
      freetimes.append(busytimes_today.complement(timeframe))
      busytimes.append(busytimes_today.normalized())

      #advance the day to sync with the next iteration
      time_begin = next_day(time_begin)
      time_end = next_day(time_end)


    #return this as a dict of the free and busy times
    return {"busy":busytimes, "free":freetimes}

def mergeBusyTimes(newTimes, oldTimes, dStart, dEnd):
    busytimes = []
    begin = arrow.get(dStart)
    end = arrow.get(dEnd)
    i = 0
    j = 0

    for day in arrow.Arrow.range('day',begin,end):
      busytimes_today = Agenda()

      for appt in newTimes[i:]:
        if same_date(day.isoformat(), appt['start']):
          busytimes_today.append(Appt.from_iso_date(appt['start'],appt['end'],'Busy'))
          i=i+1

      if(len(oldTimes) > j):
        for appt in oldTimes[j]:
          busytimes_today.append(Appt.from_iso_date(appt['start'],appt['end'],appt['descr']))

      busytimes.append(busytimes_today)
      j=j+1

    return busytimes


def get_free_times(busytimes, dStart, dEnd, tStart, tEnd):
    freetimes = []

    begin = arrow.get(dStart)
    end = arrow.get(dEnd)
    time_begin = combine_date_time(begin, arrow.get(tStart))
    time_end = combine_date_time(begin, arrow.get(tEnd))
    i = 0

    for day in busytimes:
      busytimes_today = Agenda()

      for item in day:
        busytimes_today.append(Appt.from_iso_date(item['start'],item['end'],item['descr']))

      timeframe = Appt.from_iso_date(time_begin,time_end,"Free Time")
      freetimes.append(busytimes_today.complement(timeframe))

      #advance the day to sync with the next iteration
      time_begin = next_day(time_begin)
      time_end = next_day(time_end)

    return freetimes

def sessionify(agenda):
    schedule = []

    for day in agenda:
      itinerary = []
      for appt in day.appts:
        block = {"descr": appt.desc,
                  "start": appt.begin.isoformat(),
                  "end": appt.end.isoformat()}
        itinerary.append(block)
      schedule.append(itinerary)

    return schedule


def cal_sort_key( cal ):
    """
    Sort key for the list of calendars:  primary calendar first,
    then other selected calendars, then unselected calendars.
    (" " sorts before "X", and tuples are compared piecewise)
    """
    if cal["selected"]:
       selected_key = " "
    else:
       selected_key = "X"
    if cal["primary"]:
       primary_key = " "
    else:
       primary_key = "X"
    return (primary_key, selected_key, cal["summary"])

####
#
#  Google calendar authorization:
#      Returns us to the main /choose screen after inserting
#      the calendar_service object in the session state.  May
#      redirect to OAuth server first, and may take multiple
#      trips through the oauth2 callback function.
#
#  Protocol for use ON EACH REQUEST: 
#     First, check for valid credentials
#     If we don't have valid credentials
#         Get credentials (jump to the oauth2 protocol)
#         (redirects back to /choose, this time with credentials)
#     If we do have valid credentials
#         Get the service object
#
#  The final result of successful authorization is a 'service'
#  object.  We use a 'service' object to actually retrieve data
#  from the Google services. Service objects are NOT serializable ---
#  we can't stash one in a cookie.  Instead, on each request we
#  get a fresh serivce object from our credentials, which are
#  serializable. 
#
#  Note that after authorization we always redirect to /choose;
#  If this is unsatisfactory, we'll need a session variable to use
#  as a 'continuation' or 'return address' to use instead. 
#
####

def valid_credentials():
    """
    Returns OAuth2 credentials if we have valid
    credentials in the session.  This is a 'truthy' value.
    Return None if we don't have credentials, or if they
    have expired or are otherwise invalid.  This is a 'falsy' value. 
    """
    if 'credentials' not in flask.session:
      return None

    credentials = client.OAuth2Credentials.from_json(
        flask.session['credentials'])

    if (credentials.invalid or
        credentials.access_token_expired):
      return None
    return credentials


def get_gcal_service(credentials):
  """
  We need a Google calendar 'service' object to obtain
  list of calendars, busy times, etc.  This requires
  authorization. If authorization is already in effect,
  we'll just return with the authorization. Otherwise,
  control flow will be interrupted by authorization, and we'll
  end up redirected back to /choose *without a service object*.
  Then the second call will succeed without additional authorization.
  """
  app.logger.debug("Entering get_gcal_service")
  http_auth = credentials.authorize(httplib2.Http())
  service = discovery.build('calendar', 'v3', http=http_auth)
  app.logger.debug("Returning service")
  return service

@app.route('/oauth2callback')
def oauth2callback():
  """
  The 'flow' has this one place to call back to.  We'll enter here
  more than once as steps in the flow are completed, and need to keep
  track of how far we've gotten. The first time we'll do the first
  step, the second time we'll skip the first step and do the second,
  and so on.
  """
  app.logger.debug("Entering oauth2callback")

  app.logger.debug(flask.url_for('oauth2callback', _external=True))
  #return_url = "http://localhost:5000" + flask.url_for('oauth2callback')
  flow =  client.flow_from_clientsecrets(
      CLIENT_SECRET_FILE,
      scope= SCOPES,
      redirect_uri=flask.url_for('oauth2callback', _external=True))
  ## Note we are *not* redirecting above.  We are noting *where*
  ## we will redirect to, which is this function. 
  
  ## The *second* time we enter here, it's a callback 
  ## with 'code' set in the URL parameter.  If we don't
  ## see that, it must be the first time through, so we
  ## need to do step 1. 
  app.logger.debug("Got flow")
  if 'code' not in flask.request.args:
    app.logger.debug("Code not in flask.request.args")
    auth_uri = flow.step1_get_authorize_url()
    return flask.redirect(auth_uri)
    ## This will redirect back here, but the second time through
    ## we'll have the 'code' parameter set
  else:
    ## It's the second time through ... we can tell because
    ## we got the 'code' argument in the URL.
    app.logger.debug("Code was in flask.request.args")
    auth_code = flask.request.args.get('code')
    credentials = flow.step2_exchange(auth_code)
    flask.session['credentials'] = credentials.to_json()
    ## Now I can build the service and execute the query,
    ## but for the moment I'll just log it and go back to
    ## the main screen
    app.logger.debug("Got credentials")
    return flask.redirect(flask.url_for('getCalendars',muID=flask.session['meetupId']))


#################
#
# Functions used within the templates
#
#################

@app.template_filter( 'fmtdate' )
def format_arrow_date( date ):
    try: 
        normal = arrow.get( date )
        return normal.format("MMM D")
    except:
        return "(bad date)"

@app.template_filter( 'fmttime' )
def format_arrow_time( time ):
    try:
        normal = arrow.get( time )
        return normal.format("h:mma")
    except:
        return "(bad time)"
    
#############


if __name__ == "__main__":
  # App is created above so that it will
  # exist whether this is 'main' or not
  # (e.g., if we are running under green unicorn)
  app.run(port=CONFIG.PORT,host="0.0.0.0")
    
