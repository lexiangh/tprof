#This file contains methods that are example apps specific
from app_base import App
import os
import sys
import threading
import time
import math
from utility import get_time

class ExampleApp(App):
    def __init__(self, tail_cutoff = 90):
        self.tail_cutoff = tail_cutoff
        self.abbrev = {} # place to add shorthands to service and operation names

    def trace_req_type(self, gather, trace_id):
        """
        Input: gather obj, trace_id
        Output: corresponding request type
        """
        trace_obj = gather.get_trace(trace_id)
        return next(iter(trace_obj.spans.items()))[1].service_name.split("_")[0]

    class RunApp(App.Run):
        def __init__(self, num_traces):
            self.num_traces = int(num_traces)
            self.sleep_dur = 10 #get back to this when running two requests at the same time
            
        def run(self):
            start_time = get_time()
            time.sleep(2) # add time padding

            for i in range(math.ceil(self.num_traces/2)):
                os.system('./apps/ads_service')
                os.system('./apps/booking_service')
            
            time.sleep(2)
            end_time = get_time()
            search_depth = int(self.num_traces * 1.1) # adding margin
            time.sleep(self.sleep_dur) #sleep to let jaeger finish collecting data 
            return start_time, end_time, search_depth
