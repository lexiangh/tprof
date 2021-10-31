#!/usr/bin/python3

import os
import shutil
import sys
import pickle
sys.path.insert(0, "grpc-gateway")
sys.path.insert(0, "protobuf")
sys.path.insert(0, "api_v2")
sys.path.insert(0, 'jaeger/model/proto')
import grpc
import api_v2.query_pb2_grpc as query_pb2_grpc # for creating stub
import time
import math
from gather import Jaeger
from analyze_all_reqs import Analyze as Analyze_1
from analyze_by_req_type import Analyze as Analyze_2
from analyze_child_diffs import Analyze as Analyze_3
from analyze_subspans import Analyze as Analyze_4
from app_helper import ExampleApp

def main():
    channel = grpc.insecure_channel('localhost:16686')
    stub = query_pb2_grpc.QueryServiceStub(channel)
    srvs = {}

    app = ExampleApp()
    jaeger = Jaeger(stub, app)
    analyzes = [Analyze_1(jaeger, app),  Analyze_2(jaeger, app), Analyze_3(jaeger, app), Analyze_4(jaeger, app)]
    trace_ids = []
    gather_counter = 1

    print("start running applications")
    run = app.RunApp(500)
    start_time, end_time, search_depth = run.run()
    print(f"start_time: {start_time}, end_time: {end_time}, search depth: {search_depth}")
    print("Finished running applications")

    # start gathering traces from jaeger
    while(len(trace_ids) == 0):
        time.sleep(1)
        print("Try pulling traces from jaeger {} time".format(gather_counter))
        trace_ids = jaeger.find_trace_ids(srvs, start_time, end_time, search_depth)
        gather_counter = gather_counter + 1
    print("Finished gathering {} data from jaeger".format(len(trace_ids)))

    print("start analyzing traces")
    init_path = os.getcwd() + f"/results"
    shutil.rmtree(init_path, ignore_errors=True)
    os.mkdir(init_path)
    ret = process_in_layer(trace_ids, 0, analyzes, init_path, jaeger)
    file_path = init_path + f"/ret.p"
    with open(file_path, "wb") as f:
        pickle.dump(ret, f, pickle.HIGHEST_PROTOCOL)
    print("Finished dumping analysis data to a pickle file")
                        
def process_in_layer(trace_ids, layer, analyzes, path, jaeger):
    # layer: 0-4
    ret = []
    if layer<len(analyzes):
        groups = analyzes[layer].group(trace_ids)
        num_groups = len(groups)
        max_num_padding = int(math.log10(num_groups+1))
        results = []
        #get a few examples about groups
        for name, group in groups.items():
            result = analyzes[layer].profile(group)
            results.append((result, name))
            
        results.sort()

        use_idx = [False, False, True, True, True] #treat layer 1 and 2 seperately from other layers
        for i, (result, name) in enumerate(results):
            if use_idx[layer]:
                num_paddings = max_num_padding - int(math.log10(i+1))
                paddings = num_paddings * '0'
                local_path = path + f"/layer{layer+1}-{paddings}{i+1}"
            else:
                trace_obj = jaeger.get_trace(result.traces[0]) #use the first one as an example; trace objects in one bucket should share the same bitarray
                local_path = path + f"/layer{layer+1}-{name}"
            os.makedirs(local_path, exist_ok=False)
            if layer == 0 or layer == 1:
                output_file_layer_1_2(local_path, result)
            else:
                output_file(local_path, result)
            child_ret = process_in_layer(result.traces, layer+1, analyzes, local_path, jaeger)
            ret.append((name, result, child_ret))
    return ret
            
def output_file(path, result):
    length = len(result.traces)
    with open(path + f"/{length}.txt", "w") as f: #the name of the file is the number of trace ids
        f.write(f"example trace: {result.traces[0].hex()}" + "\n")
        f.write(f"example trace: {result.traces[length//2].hex()}" + "\n")
        f.write(f"example trace: {result.traces[-1].hex()}" + "\n")
        f.write(str(result) + "\n")

#TODO: merge with output_file()
def output_file_layer_1_2(path, result):
    length = len(result.traces)
    with open(path + f"/{length}.txt", "w") as f: #the name of the file is the number of trace ids
        f.write(f"example trace: {result.traces[0].hex()}" + "\n")
        f.write(f"example trace: {result.traces[length//2].hex()}" + "\n")
        f.write(f"example trace: {result.traces[-1].hex()}" + "\n")
        f.write(f"99pctl: {result.trace99}" + "\n")
        f.write(f"left_to_99pctl: {result.trace99left}" + "\n")
        f.write(f"right_to_99pctl: {result.trace99right}" + "\n")
        f.write(str(result) + "\n")

if __name__ == '__main__':    
    main()
