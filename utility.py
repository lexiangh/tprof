"""
This is the tool box which contains functions and object definitions that others are using
"""

import pprint
import statistics
import numpy as np
import time
from enum import Enum
from anytree import Node
from bitarray import bitarray #version 1.2.1

class GenericReprStrBase:
    def __repr__(self):
        return "{}({})".format(type(self).__name__, ", ".join(["{}={!r}".format(k, v) for k, v in vars(self).items()]))
    def __str__(self):
        return "{}({})".format(type(self).__name__, ", ".join(["{}={!r}".format(k, v) for k, v in vars(self).items()]))

class Trace_Status(Enum):
    span_drop = 0
    
class Trace(GenericReprStrBase):
    name_for_good = "Good_Traces"
    name_for_bad = "Erroneous_Traces"
    def __init__(self):
        self.spans = {}
        self.root = ""
        self.trace_id = ""
        self.T = None
        self.status = bitarray(len(Trace_Status)) #create empty bitarray; index 0: jaeger span missing 
        self.status.setall(False)
    
    def get_status_str(self):
        if self.status.any():
            return Trace.name_for_bad
        else:
            return Trace.name_for_good
    
class Span(GenericReprStrBase):
    delimiter = ":"
    def __init__(self):
        self.operation_name = "" #string identifier
        self.service_name = "" #string indetifiier
        self.start_time = 0 # in unix time in nano secs
        self.end_time = 0 # sane as above
        self.refs = [] # references to the parents: span_id in hex; MASTER_SPAN_NAME for master span
        self.children = []
        
    def get_func_name(self):
        if self.operation_name:
            return self.service_name + Span.delimiter + self.operation_name
        else:
            return self.service_name
        
class Arrow(GenericReprStrBase):
    def __init__(self):
        self.name = ""
        self.src = ""
        self.superscript = "" # begin, forward, receive, terminate
        self.time = 0 # in ns

class Callee(GenericReprStrBase):
    def __init__(self):
        self.start_time = 0
        self.end_time = 0

class Subspan(GenericReprStrBase):
    def __init__(self):
        self.start_time = 0
        self.end_time = 0
        self.index = 0 # number according to starting times
        self._id = ""

class TNode(Node):
    def __init__(self, name, start_time, end_time, sid, parent=None):
        self.name = name
        self.start_time = start_time #for master span, start_time is 0, and end_time is the trace duration
        self.end_time = end_time
        self.span_id = sid
        self.parent = parent

class Stat(GenericReprStrBase):
    def __init__(self):
        self.count = 0
        self.mean = None
        self.std = None
        self.pctl_50 = None
        self.pctl_99 = None

    def __sub__(self, o):
        new_obj = Stat()
        new_obj.mean = self.mean - o.mean
        new_obj.std = self.std - o.std
        new_obj.pctl_50 = self.pctl_50 - o.pctl_50
        new_obj.pctl_99 = self.pctl_99 - o.pctl_99
        return new_obj
    
    def __repr__(self):
        return "{}({})".format(type(self).__name__, ", ".join(["{}={:.2e}".format(k, v) for k, v in vars(self).items()]))

    def __str__(self):
        return "{}({})".format(type(self).__name__, ", ".join(["{}={:.2e}".format(k, v) for k, v in vars(self).items()]))
    
def split_servop(servop):
    delimiter = Span.delimiter
    delimiter_idx = servop.find(":")
    if delimiter_idx >= 0: #if op is NOT empty
        serv = servop[:delimiter_idx]
        op = servop[delimiter_idx+1:]
    else:
        serv = servop
        op = ""
    return serv, op

"""
Calculate statistics
"""
def calc_stats(data):
    """
    Input: a list of data
    Output: an Stat() obj
    """
    result = Stat()
    result.count = len(data)
    result.mean = statistics.mean(data)
    result.pctl_50, result.pctl_99 = np.percentile(data, [50, 99])
    if len(data) > 1:
        result.std = statistics.stdev(data, xbar=result.mean)
    else:
        result.std = 0 #don't put string here, otherwise the print doesn't work
    return result

def get_arrows(trace_obj):
    """
    Generate arrow-representation of a Trace() object
    Input: trace_obj
    Output: all_arrows in map - span_id:[Arrow0(), Arrow1(), ...], which doesn't contain the master span
    """

    all_arrows={}

    # Get a set of all_span_ids
    all_span_ids = set()
    for span_id, span_object in trace_obj.spans.items():
        all_span_ids.add(span_id)

    # Organize the calls: refs_id -> span_id
    
    """
    The structure of all_calls is
    {
      caller_id0:{
        callee_id0: callee_obj0,
        callee_id1: callee_obj1,
        ...,
      },
      caller_id1:{
        callee_id20: callee_obj20,
        callee_id21: callee_obj21,
        ...,
      },
      ...,
    }
    """
    #TODO: repeated codes, resolve later
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
        if caller_id not in all_arrows:
            all_arrows[caller_id] = []

        arrows = all_arrows[caller_id]

        # create start and end Arrows first
        #TODO: change src/name to parent/child
        new_arrow_start = Arrow()
        new_arrow_start.src = caller_id
        new_arrow_start.time = trace_obj.spans[caller_id].start_time
        new_arrow_start.superscript = "begin"
        new_arrow_start.name = caller_id
        arrows.append(new_arrow_start)

        new_arrow_end = Arrow()
        new_arrow_end.src = caller_id
        new_arrow_end.time = trace_obj.spans[caller_id].end_time
        new_arrow_end.superscript = "terminate"
        new_arrow_end.name = caller_id
        arrows.append(new_arrow_end)

        for callee_id, callee_object in callee_map.items():

            # create a calling arrow
            new_arrow_forward = Arrow()
            new_arrow_forward.src = caller_id
            new_arrow_forward.name = callee_id
            new_arrow_forward.superscript = "forward"
            new_arrow_forward.time = callee_object.start_time
            arrows.append(new_arrow_forward)

            # create a feedback arrow
            new_arrow_backward = Arrow()
            new_arrow_backward.src = caller_id
            new_arrow_backward.name = callee_id
            new_arrow_backward.superscript = "receive"
            new_arrow_backward.time = callee_object.end_time
            arrows.append(new_arrow_backward)

    # add arrows for other single spans that were not callers
    for span_id in all_span_ids:
        if span_id not in all_calls:
            if span_id not in all_arrows:
                all_arrows[span_id] = []
            else:
                print("weird span name")
                print(span_id)
                assert(False)

            arrows = all_arrows[span_id]

            # create start and end Arrows first
            new_arrow_start = Arrow()
            new_arrow_start.src = span_id
            new_arrow_start.time = trace_obj.spans[span_id].start_time
            new_arrow_start.superscript = "begin"
            new_arrow_start.name = span_id
            arrows.append(new_arrow_start)

            new_arrow_end = Arrow()
            new_arrow_end.src = span_id
            new_arrow_end.time = trace_obj.spans[span_id].end_time
            new_arrow_end.superscript = "terminate"
            new_arrow_end.name = span_id
            arrows.append(new_arrow_end)

    for span_id in all_arrows:
        all_arrows[span_id].sort(key=lambda arrow: (arrow.time, arrow.superscript)) # sort the arrows based on time and type
    return all_arrows

def add_func_name_to_arrows(trace_obj, arrows):
    """
    change the arrow map from using span_id to function name as identifier
    """
    revised_arrows = {}
    for span_id, Arrows in arrows.items():
        span_name = trace_obj.spans[span_id].get_func_name()
        if span_name not in revised_arrows:
            revised_arrows[span_name] = []
        for this_Arrow in Arrows:
            new_arrow = Arrow()
            new_arrow.name = trace_obj.spans[this_Arrow.name].get_func_name()
            new_arrow.src = trace_obj.spans[this_Arrow.src].get_func_name()
            new_arrow.superscript = this_Arrow.superscript
            new_arrow.time = this_Arrow.time
            revised_arrows[span_name].append(new_arrow)
    return revised_arrows
    
def get_time():
    """
    convert unix_time to nano seconds
    """
    unix_time = time.time()
    return unix_time*(10**9)
