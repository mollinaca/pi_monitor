#!/bin/bash
LOGFILE="/mnt/data/pi_monitor/logs/rpi_monitor.log"
echo "=== Monitor started $(date) ===" >> $LOGFILE

while true; do
    TIMESTAMP=$(date '+%Y-%m-%d %H:%M:%S')
    TEMP=$(vcgencmd measure_temp)
    THROTTLE=$(vcgencmd get_throttled)
    MEM=$(free -m | awk 'NR==2{printf "Mem used:%sMB free:%sMB", $3, $4}')
    IOWAIT=$(iostat -c 1 1 | awk 'NR==4{print "iowait:"$4"%"}')
    echo "$TIMESTAMP | $TEMP | $THROTTLE | $MEM | $IOWAIT" >> $LOGFILE
    sleep 1
done
