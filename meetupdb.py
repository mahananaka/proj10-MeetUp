"""
Just to test database functions,
outside of Flask.

We want to open our MongoDB database,
insert some memos, and read them back
"""

import pymongo
from pymongo import MongoClient
import arrow
import sys
import uuid

import secrets.admin_secrets
import secrets.client_secrets


MONGO_CLIENT_URL = "mongodb://{}:{}@{}:{}/{}".format(
    secrets.client_secrets.db_user,
    secrets.client_secrets.db_user_pw,
    secrets.admin_secrets.host,
    secrets.admin_secrets.port,
    secrets.client_secrets.db)

MONGO_ADMIN_URL = "mongodb://{}:{}@{}:{}/admin".format(
    secrets.admin_secrets.admin_user,
    secrets.admin_secrets.admin_pw,
    secrets.admin_secrets.host, 
    secrets.admin_secrets.port)

def makeDBUser():
    try: 
        dbclient = MongoClient(MONGO_ADMIN_URL)
        db = getattr(dbclient, secrets.client_secrets.db)
        db.add_user(secrets.client_secrets.db_user, password=secrets.client_secrets.db_user_pw)
        print("Created user {}".format(secrets.client_secrets.db_user))
    except Exception as err:
        print("Failed:")
        print(err)


def getDBCollection():
    try:
        dbclient = MongoClient(MONGO_CLIENT_URL)
        db = getattr(dbclient, secrets.client_secrets.db)
        collection = db.meeting
        return collection
    except Exception as err:
        print("Failed to connect to db.")
        return none

    return None

def addMeetUp(descr,sdate,edate,stime,etime):
    rid = str(uuid.uuid4())
    record = { "meetupid": rid,
               "descr": descr,
               "sdate": sdate,
               "edate": edate,
               "stime": stime,
               "etime": etime,
               "count": 0,
               "busytime": [] }

    collection = getDBCollection()
    collection.insert(record)
    return rid

def getMeetUp(meetupID):
    key = {"meetupid":meetupID}
    collection = getDBCollection()
    records = collection.find(key)

    if records.count() > 0:
      return records[0] #just the first result, should only be one.
    else:
      return None

def getAllMeetUps():
    collection = getDBCollection()
    records = collection.find()
    return records

def deleteMeetUp(meetupID):
    key = { "meetupid": meetupID }
    collection = getDBCollection()
    collection.remove(key)
    return

def updateBusyTimes(meetupID, busytimes):
    key = {"meetupid":meetupID}
    value = {"busytime":busytimes}
    collection = getDBCollection()
    collection.update(key, { '$set': value })
    collection.update(key, { '$inc':{ "count":1 }})
    return

if __name__ == "__main__":
    makeDBUser()