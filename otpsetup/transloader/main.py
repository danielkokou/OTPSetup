#!/usr/bin/python

from boto import connect_s3
from boto.s3.key import Key
from datetime import datetime
from kombu import Exchange, Queue
from otpsetup.shortcuts import DjangoBrokerConnection
from otpsetup.client.models import GtfsFile
from otpsetup import settings
from shutil import copyfileobj
from tempfile import TemporaryFile
from urllib2 import urlopen

exchange = Exchange("amq.direct", type="direct", durable=True)
queue = Queue("transload", exchange=exchange, routing_key="transload")

def s3_bucket(cache = {}):
    if not 'bucket' in cache:
        
        connection = connect_s3(settings.AWS_ACCESS_KEY_ID, settings.AWS_SECRET_KEY)
        bucket = connection.get_bucket(settings.S3_BUCKET)
        cache['bucket'] = bucket
    else:
        return cache['bucket']
    return bucket

def s3_key(bucket, irequest):
    k = Key(bucket)
    k.key = "uploads/%s/%s" % (irequest.id, datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%S.zip"))
    return k

def process_transload(conn, body, message):
    #attempt to download the URL
    url = body['transload']
    #make sure this still makes sense
    gtfs = GtfsFile.objects.get(id=body['id'])
    irequest = gtfs.instance_request
    if irequest.state != "pre_transload":
        #this request has already been cancelled or is otherwise irrelevant
        print "wrong state"
        message.ack()
        return 

    try:
        resp = urlopen(url)
    except urllib2.HTTPError:
        print "failed"
        #this is a permanent failure, so we want to alert the user.
        notify_user_of_failure(url)
        irequest.state = "failed"
        irequest.save()
        message.ack()
        return
    
    tmpfile = TemporaryFile()
    copyfileobj(resp, tmpfile)

    bucket = s3_bucket()
    key = s3_key(bucket, irequest)

    key.set_contents_from_file(tmpfile)

    gtfs.s3_key = key.key
    gtfs.save()
    allDownloaded = True
    s3_keys = []
    for gtfs in irequest.gtfsfile_set.all():
        if not gtfs.s3_key:
            allDownloaded = False
            break
        s3_keys.append(gtfs.s3_key)
    if allDownloaded:
        publisher = conn.Producer(routing_key="validate_request",
                                  exchange=exchange)
        publisher.publish({"files" : s3_keys, "request_id" : irequest.id})
        irequest.state = "submitted"
        irequest.save()

    message.ack()

with DjangoBrokerConnection() as conn:

    with conn.Consumer(queue, callbacks=[lambda body, message: process_transload(conn, body, message)]) as consumer:
        # Process messages and handle events on all channels
        while True:
            conn.drain_events()