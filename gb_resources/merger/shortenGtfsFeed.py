#!/usr/bin/python
# Shorten GTFS: shorten a GTFS so that there is no service after the date specified by the first argument

from sys import argv
import csv, chardet
from cStringIO import StringIO
from zipfile import ZipFile
from sets import Set

enddate = argv[1]
infileName = argv[2]
outfileName = argv[3]

# store a list of ref'd service IDs and use it to prune trips.txt
serviceIds = Set()

# store a list of ref'd trips and use it to prune stop_times.txt
trips = Set()

def get_reader(infile, filename):
    content = infile.open(filename).read()
    if chardet.detect(content)['encoding'] == "UTF-8":
    
        content=content.decode("utf-8")
        content=content.encode("ascii", "ignore")

        f = open(filename, 'w')
        f.write(content)
        f.close()

        return csv.DictReader(open(filename), skipinitialspace=True)

    else:
        return csv.DictReader(infile.open(filename), skipinitialspace=True)
        

with ZipFile(infileName) as infile:
    with ZipFile(outfileName, 'w') as outfile:

        try:
            
            reader = get_reader(infile, "calendar.txt")
            
        except KeyError:
            pass

        else:
            output = StringIO()
            writer = csv.DictWriter(output, reader.fieldnames)
            writer.writeheader()

            for row in reader:
                if row['start_date'] > enddate:
                    continue

                if row['end_date'] > enddate:
                    row['end_date'] = enddate

                serviceIds.add(row['service_id'])
                writer.writerow(row)

            outfile.writestr('calendar.txt', output.getvalue())
            output.close()

        try:
            reader = get_reader(infile, 'calendar_dates.txt')

        except KeyError:
            pass

        else:
            output = StringIO()
            writer = csv.DictWriter(output, reader.fieldnames)
            writer.writeheader()

            for row in reader:
                if row['date'] <= enddate:
                    serviceIds.add(row['service_id'])
                    writer.writerow(row)
                
            outfile.writestr('calendar_dates.txt', output.getvalue())
            output.close()

        # Get the trips, dropping unref'd ones
        try:
            reader = get_reader(infile, 'trips.txt')
        
        except KeyError:
            pass

        else:
            output = StringIO()
            writer = csv.DictWriter(output, reader.fieldnames)
            writer.writeheader()

            for row in reader:
                if row['service_id'] in serviceIds:
                    trips.add(row['trip_id'])
                    writer.writerow(row)

            outfile.writestr('trips.txt', output.getvalue())
            output.close()

        # save some RAM
        del serviceIds

        # drop unref'd stop times
        try:
            reader = get_reader(infile, 'stop_times.txt')
        
        except KeyError:
            pass

        else:
            output = StringIO()
            writer = csv.DictWriter(output, reader.fieldnames)
            writer.writeheader()

            for row in reader:
                if row['trip_id'] in trips:
                    writer.writerow(row)

            outfile.writestr('stop_times.txt', output.getvalue())
            output.close()

        for name in infile.namelist():
            if name == 'calendar.txt' or name == 'calendar_dates.txt' or name == 'trips.txt' or name == 'stop_times.txt':
                continue
                    
            else:
               outfile.writestr(name, infile.read(name))
