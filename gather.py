#!/usr/bin/python3

from abc import ABC,abstractmethod
from google.protobuf.duration_pb2 import Duration
from google.protobuf.timestamp_pb2 import Timestamp
import api_v2.query_pb2 as query_pb2
from utility import Trace, Span, Callee, Trace_Status
import sys
import pickle
from datetime import datetime

class Gather(ABC):

    def __init__(self, app):
        self.cache = {} # map(trace_id_in_bytes, trace_obj)
        self.app = app
        
    @abstractmethod
    def find_trace_ids(self, srvs, time_start, time_end, num_results):
        """
        Given stub, services maps, start time, end time and search depth, return all the associated trace ids
        Inputs: stub, services in map, time_start in nanosec, time_end in nanosec, and number of results 
        Output: a list of all associated traces ids

        An example of services maps:
        srvs = {
        "user-timeline-services":[operation1, operation2],
        }
        """
        pass
    
    @abstractmethod
    def get_trace(self, trace_id_in_bytes):
        """
        Given trace_id, return all the spans associated with that trace
        Inputs: trace id
        Outputs: a trace object (i.e. all spans in that trace)
        """
        pass

class Jaeger(Gather):
    """This is the class for using jaeger tracing system"""

    def __init__(self, stub, app):
        super().__init__(app)
        self.master_span_name = "THEMASTERSPAN"
        self.stub = stub
        self.DUR_MIN = 1 # in nano sec
        self.DUR_MAX = 10 * 60 * 1000 * 1000 * 1000 # 10 min
        self.abbrev = app.abbrev
    
    def find_trace_ids(self, srvs, time_start, time_end, num_results):

        # By default, if the srvs is left blank, search for all services
        if len(srvs) == 0:
            services = self.__get_services()
        else:
            services = srvs.keys()

        all_trace_ids = set()
        duration_min = Duration()
        duration_min.FromNanoseconds(self.DUR_MIN)
        duration_max = Duration()
        duration_max.FromNanoseconds(self.DUR_MAX)
        start_min = time_start
        start_max = time_end

        for service in services:
            # By default, if the operation is left blank, search for all possible operations
            if service in srvs and len(srvs[service])>0:
                operations = srvs[service]
            else:
                operations = self.__get_operations(service)
                
            for operation in operations:
                request = query_pb2.FindTracesRequest(query=query_pb2.TraceQueryParameters(service_name=service, operation_name=operation, tags={}, start_time_min=self.__get_ts(start_min), start_time_max=self.__get_ts(start_max), duration_min=duration_min, duration_max=duration_max, search_depth=num_results))
                spans_pkg = self.stub.FindTraces(request)           
                for spans_in_a_trace in spans_pkg:
                    for span in spans_in_a_trace.spans:
                        assert(span.trace_id != 0), "weird! trace_id = 0"
                        all_trace_ids.add(span.trace_id)

        return list(all_trace_ids)

    def __get_services(self):
        response = self.stub.GetServices(query_pb2.GetServicesRequest())
        return response.services

    def __get_operations(self, service):
        """
        Given service name, get all the associated operations
        Input: stub, service
        Output: all the operations in list
        """
        response = self.stub.GetOperations(query_pb2.GetOperationsRequest(service = service))
        return response.operations

    def get_trace(self, trace_id_in_bytes):
        # if in cache, return immediately
        if trace_id_in_bytes in self.cache.keys():
            return self.cache[trace_id_in_bytes] #TODO: assume trace_ids are unique?
        all_spans = []
        spans_pkg = self.stub.GetTrace(query_pb2.GetTraceRequest(trace_id=trace_id_in_bytes))

        for spans in spans_pkg:
            for a_span in spans.spans:
                all_spans.append(a_span)

        trace_obj = self.__create_trace_obj(trace_id_in_bytes, all_spans)
        self.cache[trace_id_in_bytes] = trace_obj
        return trace_obj
    
    def __create_trace_obj(self, trace_id_in_bytes, all_spans):
        """
        Create a Trace() object
        Input: spans in a trace
        Output: a Trace() object
        """        
        trace_obj = Trace()
        trace_obj.trace_id = trace_id_in_bytes.hex() #store trace_id in hex for human to interpret
        trace_obj.root = self.master_span_name
        very_start = float('inf')
        very_end = 0

        # Get a set of all_span_ids
        all_span_ids = set()

        for span in all_spans:
            all_span_ids.add(span.span_id)
            
        for span in all_spans:
            span_trace_id = span.trace_id.hex()
            span_id = span.span_id.hex()
            if span_id not in trace_obj.spans:
                trace_obj.spans[span_id] = Span()
            else:
                print("Odd, duplicate span")
                print(span_trace_id)
                print(span_id)
                assert(False)

            #Construct a new span
            new_span = trace_obj.spans[span_id]
            new_span.operation_name = self.__simplify_name(span.operation_name)
            new_span.service_name = self.__simplify_name(span.process.service_name)
            new_span.start_time = span.start_time.seconds*(10**9)+span.start_time.nanos
            new_span.end_time = new_span.start_time + span.duration.seconds*(10**9) + span.duration.nanos

            #for debugging purposes:
            if new_span.end_time - new_span.start_time > 10**11:
                with open("debugging.txt", "a") as f:
                    f.write(f"{datetime.now().strftime('%H:%M:%S')}\n new_span={new_span}\n span={span}\n")
                
            #Calcuate T (trace duration)
            if new_span.start_time < very_start:
                very_start = new_span.start_time
            if new_span.end_time > very_end:
                very_end = new_span.end_time

            #TODO: optimize the if else structure
            if len(span.references) > 0:
                for reference in span.references:
                    if span_trace_id != reference.trace_id.hex():
                        print("Odd, reference other trace id")
                        print(reference.trace_id.hex())
                        print(reference.span_id.hex())
                        assert(False)
                    elif reference.span_id not in all_span_ids:
                        print(f"The reference span_id doesn't exist in this trace. There might be warnings in jaeger, trace:{span_trace_id}, span:{span_id}")
                        new_span.refs.append(trace_obj.root)
                        trace_obj.status[Trace_Status.span_drop.value] = 1
                    else:
                        new_span.refs.append(reference.span_id.hex())
            else:
                new_span.refs.append(trace_obj.root)

            
        #jaeger traces doesn't have master spans, add an aritificial one so that each trace only has one root
        trace_obj.spans[trace_obj.root] = Span()
        master_span = trace_obj.spans[trace_obj.root]
        master_span.service_name = trace_obj.root
        master_span.start_time = very_start
        master_span.end_time = very_end
        trace_obj.T = very_end - very_start

        #add children to trace
        all_calls={}
        for span_id, span_object in trace_obj.spans.items():
            if span_id == trace_obj.root:
                continue
            assert len(span_object.refs)==1,"span {}:{} has more than one or no parents".format(span_id, span_object)
            refs_id = span_object.refs[0] # a span only has a single parent
            if refs_id not in all_calls.keys():
                all_calls[refs_id] = {}
            calls = all_calls[refs_id]
            if span_id not in calls.keys():
                calls[span_id] = Callee()
            else:
                assert False, "Looping the same span {} again, weird".format(span_id)
            call = calls[span_id]
            call.start_time = span_object.start_time
            call.end_time = span_object.end_time

        for caller_id, callee_map in all_calls.items():
            for callee_id in callee_map.keys():
                trace_obj.spans[caller_id].children.append(callee_id)

        return trace_obj

    def __simplify_name(self,name):
        """
        A helper function for simplify the span names
        """
        if name in self.abbrev:
            return self.abbrev[name]
        else:
            return name

    def __get_ts(self, ts):
        """
        Convert t from seconds to a Timestamp() object
        """
        unix_time = ts/(10**9)
        return Timestamp(seconds =int(unix_time), nanos=int((unix_time - int(unix_time)) * 10**9))

