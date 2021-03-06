import os, subprocess, re, math, codecs
from otpsetup import settings

from boto import connect_s3
from boto.s3.key import Key

from xml.sax.saxutils import escape

templatedir = os.path.join(settings.GRAPH_BUILDER_RESOURCE_DIR, 'templates')
osmosisdir = os.path.join('/var/osm/osmosis')
osmfilterdir = os.path.join(settings.GRAPH_BUILDER_RESOURCE_DIR, 'osmfilter')
osmtoolsdir = os.path.join(settings.GRAPH_BUILDER_RESOURCE_DIR, 'osmtools')
otpgbdir = os.path.join(settings.GRAPH_BUILDER_RESOURCE_DIR, 'otpgb')
nedcachedir = '/mnt/nedcache'

def ned_available(polyfilename):

    polyfile = open(polyfilename, 'r')
    tiffset = set() 
    for line in polyfile:
        if re.match("^[ \t]*[0-9.\-]+[ \t]+[0-9.\-]+[ \t]*$", line) is not None:
            arr = re.split("[ \t]+",line)
            line = re.sub("^[ \t]+", '', line[:-1])
            arr = re.split("[ \t]+",line)
            x = math.floor(float(arr[0]))
            y = math.ceil(float(arr[1]))
            nsdir =  'n' if y > 0 else 's'
            ewdir =  'e' if x > 0 else 'w'
            tiff_file = "%s%02d%s%03d.tiff" % (nsdir, abs(y), ewdir, abs(x))   
            tiffset.add(tiff_file)
   
    polyfile.close

    connection = connect_s3(settings.AWS_ACCESS_KEY_ID, settings.AWS_SECRET_KEY)        
    bucket = connection.get_bucket('ned13')

    all_exist = True        
    for tiff_file in tiffset:            
        key = Key(bucket)
        key.key = tiff_file
        print "%s exists: %s" % (tiff_file, key.exists())
        all_exist = all_exist and key.exists()

    return all_exist


def generate_osm_extract_polygon(workingdir):

    print "generating extract polygon"

    # copy stop files to single directory

    stopsdir = os.path.join(workingdir, "stops")
    if not os.path.exists(stopsdir): os.makedirs(stopsdir)

    gtfsdirlist = os.listdir(os.path.join(workingdir, "gtfs"))

    for item in gtfsdirlist:
        
        gtfsfeeddir = os.path.join(workingdir, 'gtfs', item[:-4])
        print "item=%s, dir=%s" % (item, gtfsfeeddir)
        subprocess.call(['unzip', os.path.join(workingdir, 'gtfs', item), '-d', gtfsfeeddir])
        stopsfile = os.path.join(gtfsfeeddir, 'stops.txt')
        if os.path.isfile(stopsfile):
            subprocess.call(['cp', stopsfile, os.path.join(stopsdir, item+'_stops.txt')])
        else:
            print 'WARNING: could not find stops.txt file for "'+item+'" GTFS feed'


    # generate osmosis polygon
        
    polyfile = os.path.join(workingdir, 'extract_poly.txt')
    boundsfile = os.path.join(workingdir, 'extract_bounds.txt')
    cmd = 'java -jar %s %s %s %s' % (os.path.join(osmtoolsdir, 'osmtools.jar'), stopsdir, polyfile, boundsfile)
    os.system(cmd)

def generate_osm_extract(workingdir):

    print "running osm extract"

    polyfile = os.path.join(workingdir, 'extract_poly.txt')
    boundsfile = os.path.join(workingdir, 'extract_bounds.txt')

    if(not os.path.isfile(polyfile) or not os.path.isfile(boundsfile)):
        generate_osm_extract_polygon(workingdir)

    bfreader = open(boundsfile, 'r')
    boundsarr = bfreader.read().strip().split(',')
    bfreader.close()

    # run osm extract

    extractfile_tmp = os.path.join(workingdir, 'extract_tmp.osm')
    extractfile = os.path.join(workingdir, 'extract.osm')
    #cmd = os.path.join(osmosisdir,'bin/osmosis')+' --rb '+settings.PLANET_OSM_PATH+' --bounding-polygon file='+polyfile+' --wx '+extractfile + "-tmp"
    #os.system(cmd)
    #cmdarr = [ os.path.join(osmosisdir,'bin/osmosis'), '--read-pgsql', 'host="localhost"', 'database="osmna"', 'user="otp"', 'password="osm"', '--dbb', 'left=%s' % boundsarr[0], 'right=%s' % boundsarr[1], 'bottom=%s' % boundsarr[2], 'top=%s' % boundsarr[3], '--bounding-polygon', 'file=%s' % polyfile, '--wx', extractfile_tmp]
    #print cmdarr
    #subprocess.call(cmdarr)
    
    os.system('/var/osm/osmosis/bin/osmosis --read-pgsql host="localhost" database="osmna" user="otp" password="osm" --dbb left=%s right=%s bottom=%s top=%s --bounding-polygon file=%s --wx %s' % (boundsarr[0], boundsarr[1], boundsarr[2], boundsarr[3], polyfile, extractfile_tmp))


    #run osmfilter to exclude everything we don't use.
    #remember to keep this in sync with OSMGBI
    cmd = os.path.join(osmfilterdir, 'osmfilter --keep-ways="highway= platform=" --keep-relations="(type=multipolygon and area=yes) or type=restriction or (type=route and route=road) or type=level_map" --keep-nodes= ' + extractfile_tmp + ' -o=' + extractfile)
    os.system(cmd)
    os.unlink(extractfile_tmp)
    

def generate_graph_config(workingdir, fare_factory, extra_props_dict):

    polyfile = os.path.join(workingdir, 'extract_poly.txt')
    if(not os.path.isfile(polyfile)):
        generate_osm_extract_polygon(workingdir)

    # generate graph-builder config file
    use_ned = settings.NED_ENABLED and ned_available(polyfile)
    extractfile = os.path.join(workingdir, 'extract.osm')

    if use_ned:
        templatefile = open(os.path.join(templatedir, 'gb_ned.xml'), 'r')
    else:
        templatefile = open(os.path.join(templatedir, 'gb_no_ned.xml'), 'r')

    gbxml = templatefile.read()
    templatefile.close()

    gtfslist = ''
    gtfsdirlist = os.listdir(os.path.join(workingdir, "gtfs"))
    for item in gtfsdirlist:
        if os.path.isdir(os.path.join(workingdir, "gtfs", item)):
            continue
        gtfslist += '                        <bean class="org.opentripplanner.graph_builder.model.GtfsBundle">\n'
        gtfslist += '                            <property name="path" value="'+os.path.join(workingdir, 'gtfs', item)+'" />\n'

        if(extra_props_dict[item] != None):
            gtfslist += extra_props_dict[item]
        
        gtfslist += '                        </bean>\n'

    if use_ned:
        gbxml = gbxml.format(graphpath=workingdir, gtfslist=gtfslist, osmpath=extractfile, nedcachepath=nedcachedir, awsaccesskey=settings.AWS_ACCESS_KEY_ID, awssecretkey=settings.AWS_SECRET_KEY, fare_factory=fare_factory)
    else:
        gbxml = gbxml.format(graphpath=workingdir, gtfslist=gtfslist, osmpath=extractfile, fare_factory=fare_factory)

    gbfilepath = os.path.join(workingdir, 'gb.xml')
    gbfile = open(gbfilepath, 'w')
    gbfile.write(gbxml)
    gbfile.close()

def generate_graph_config_managed(workingdir, feeds):

    print "gen managed gb.xml"

    polyfile = os.path.join(workingdir, 'extract_poly.txt')
    if(not os.path.isfile(polyfile)):
        generate_osm_extract_polygon(workingdir)


    # generate graph-builder config file
    use_ned = settings.NED_ENABLED and ned_available(polyfile)
    extractfile = os.path.join(workingdir, 'extract.osm')
    fare_factory = 'org.opentripplanner.routing.impl.DefaultFareServiceFactory'

    if use_ned:
        templatefile = codecs.open(os.path.join(templatedir, 'gb_ned.xml'), encoding='utf-8')
    else:
        templatefile = codecs.open(os.path.join(templatedir, 'gb_no_ned.xml'), encoding='utf-8')

    gbxml = templatefile.read()
    templatefile.close()

    gtfslist = u''
    for feed in feeds:
        print " - %s" % feed['key']
        feedpath = os.path.join(workingdir, 'gtfs', '%s.zip' % feed['key'].split('/')[-1])
        gtfslist += u'                        <bean class="org.opentripplanner.graph_builder.model.GtfsBundle">\n'
        gtfslist += u'                            <property name="path" value="' + feedpath + '" />\n'
        if 'defaultAgencyId' in feed:
            escapedId = escape(feed['defaultAgencyId'])
            gtfslist += u'                            <property name="defaultAgencyId" value="'+escapedId+'" />\n'
        if 'extraProperties' in feed:
            gtfslist += feed['extraProperties']
        #if 'defaultBikesAllowed' in feed:
        #    gtfslist += '                            <property name="defaultBikesAllowed" value="'+feed['defaultBikesAllowed']+'" />\n'

        gtfslist += u'                        </bean>\n'

    if use_ned:
        gbxml = gbxml.format(graphpath=workingdir, gtfslist=gtfslist, osmpath=extractfile, nedcachepath=nedcachedir, awsaccesskey=settings.AWS_ACCESS_KEY_ID, awssecretkey=settings.AWS_SECRET_KEY, fare_factory=fare_factory)
    else:
        gbxml = gbxml.format(graphpath=workingdir, gtfslist=gtfslist, osmpath=extractfile, fare_factory=fare_factory)

    gbfilepath = os.path.join(workingdir, 'gb.xml')
    gbfile = codecs.open(gbfilepath, encoding='utf-8', mode='w')
    gbfile.write(gbxml)
    gbfile.close()



def run_graph_builder(workingdir):
    print 'running OTP graph builder'

    gbfilepath = os.path.join(workingdir, 'gb.xml')
    otpjarpath = os.path.join(otpgbdir, 'graph-builder.jar')
    if not os.path.exists(nedcachedir): os.makedirs(nedcachedir) 

    result = subprocess.Popen(["java", "-Xms15G", "-Xmx15G", "-jar", otpjarpath, gbfilepath], stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    
    gb_stdout = result.stdout.read()
    gb_stderr = result.stderr.read()
    graphpath = os.path.join(workingdir, 'Graph.obj')
    graphsuccess = os.path.exists(graphpath) and os.path.getsize(graphpath) > 0
    
    results = {}

    gb_output = 'STDOUT:\n\n%s\n\nSTDERR:\n\n%s' % (gb_stdout, gb_stderr)    
    
    results['success'] = graphsuccess
    results['output'] = gb_output 
    
    print "gb complete"
    print gb_output
    return results

