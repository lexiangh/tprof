#!/bin/bash

# install the required packages
./install.sh

#set up jaeger-all-in-one
#using v1.21, newer versions have port changes
sudo docker run -d --name jaeger \
  -e COLLECTOR_ZIPKIN_HOST_PORT=:9411 \
  -e QUERY_BASE_PATH=/jaeger \
  -p 5775:5775/udp \
  -p 6831:6831/udp \
  -p 6832:6832/udp \
  -p 5778:5778 \
  -p 16686:16686 \
  -p 14268:14268 \
  -p 14250:14250 \
  -p 9411:9411 \
  jaegertracing/all-in-one:1.21

sleep 5

#run applications and let tprof collect/analyze traces
./tprof.py

#run flask web application to generate reports
cd ./web_app
./web_app.py ../results/*.p &
sleep 5

#open the report webpage
xdg-open http://localhost:5000/reports &

cd -
