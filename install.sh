#!/bin/bash

#install required packages and preparing environment
sudo apt -y install git
sudo apt -y install python3-pip
sudo apt -y install libcurl4
sudo apt -y install docker.io
pip3 install grpcio
pip3 install grpcio-tools
pip3 install googleapis-common-protos
pip3 uninstall -y protobuf
pip3 install --no-binary=protobuf --upgrade protobuf
pip3 install protoc-gen-swagger
pip3 install numpy
pip3 install anytree
pip3 install bitarray
pip3 install jinja2
pip3 install flask
pip3 install inflect
