"""
This file contains shared methods between layer1:analyze_all_reqs and layer2:analyze_by_req_type
"""
from pprint import pformat as pf
import copy
import functools
import math
import sys
import json
from analyze_base import BaseAnalyze
from anytree import LevelOrderIter
from abc import abstractmethod
from utility import GenericReprStrBase, Trace, Span, Arrow, Callee, TNode, calc_stats, get_arrows


class AnalyzeFunctions(BaseAnalyze):

    @functools.total_ordering
    class resultObj(GenericReprStrBase):
        def __init__(self, length):
            self.length = length
            self.all_operation = [] # a lists of stats sorted by mean
            self.norm_operation = [] # followings are same as above
            self.tail_operation = []
            self.diff_operation = []
            self.all_operation_self = []
            self.norm_operation_self = []
            self.tail_operation_self = []
            self.diff_operation_self = []
            self.traces = []
            
        def __lt__(self, other):
            return self.length > other.length #reversed ordering

        def __eq__(self, other):
            return self.length == other.length

        def __str__(self):
            str = "Length: {}\n Here are the time splits of \n all operation instances:\n{}\n\n norm operation instance:\n{}\n\n tail operation instances:\n{}\n\n diff operation instances:\n{}\n\n all operation_self instances:\n{}\n\n norm operation_self instance:\n{}\n\n tail operation_self instances:\n{}\n\n diff operation_self instances:\n{}\n\n".format(self.length, pf(self.all_operation), pf(self.norm_operation), pf(self.tail_operation), pf(self.diff_operation), pf(self.all_operation_self), pf(self.norm_operation_self), pf(self.tail_operation_self), pf(self.diff_operation_self))
            return str

    @abstractmethod    
    def group(self, trace_ids):
        """
        Input: a list of trace_ids
        Output: a list of lists of groups [[trace_group0], [trace_group1], ...]
        """
        pass
    
    def profile(self, trace_ids):
        """
        Input: a list of trace_ids (in a group got from group())
        Output: TBA
        """
        
        all_traces = []
        for trace_id in trace_ids:
            trace_obj = self.gather.get_trace(trace_id)
            all_traces.append(trace_obj)
        sorted_traces = sorted(all_traces, key=lambda trace_obj:trace_obj.T)
        idx_cutoff = math.floor(self.app.tail_cutoff/100 * len(sorted_traces))

        idx_99 = math.floor(0.99*len(sorted_traces))
        idx_99left = idx_99 - 1
        idx_99right = idx_99 + 1

        result = self.resultObj(len(trace_ids))
        result.traces = trace_ids

        result.trace99 = sorted_traces[idx_99].trace_id
        result.trace99left = "0"
        result.trace99right = "0"
        if len(sorted_traces) > 100:
            result.trace99left = sorted_traces[idx_99left].trace_id
            result.trace99right = sorted_traces[idx_99right].trace_id

        result.all_operation = self.__calc_operation(sorted_traces)
        result.norm_operation = self.__calc_operation(sorted_traces[:idx_cutoff])
        result.tail_operation = self.__calc_operation(sorted_traces[idx_cutoff:])
        result.diff_operation = self.__calc_diff(result.norm_operation, result.tail_operation)
        result.all_operation_self = self.__calc_operation_self(sorted_traces)
        result.norm_operation_self = self.__calc_operation_self(sorted_traces[:idx_cutoff])
        result.tail_operation_self = self.__calc_operation_self(sorted_traces[idx_cutoff:])
        
        result.diff_operation_self = self.__calc_diff(result.norm_operation_self, result.tail_operation_self)
        return result

    def __calc_diff(self, norm, tail):
        #this function currently is the same as the one in analyze_subspans.py except for the error messages
        diff = {}
        index = {tail[i][0]:i for i in range(len(tail))}
        for i in range(len(norm)):
            assert(norm[i][0] not in diff), "error, duplicate function names"
            if norm[i][0] not in index:
                continue
            diff[norm[i][0]] = tail[index[norm[i][0]]][1] - norm[i][1]
        diff_list = list(diff.items())
        sorted_diff = sorted(diff_list, key=lambda kv: kv[1].mean, reverse = True)
        return sorted_diff

    def __calc_operation(self, traces):
        all_operation = {}
        for trace_obj in traces:
            arrows = get_arrows(trace_obj)
            #TODO: optimize by not using get_arrows
            for span_id, span_arrows in arrows.items():
                span = trace_obj.spans[span_id]
                span_func_name = span.get_func_name() 
                if span_func_name not in all_operation:
                    all_operation[span_func_name] = []
                all_operation[span_func_name].append(span.end_time - span.start_time)
                    
        all_operation_result = {}
        for span_func_name, times in all_operation.items():
            all_operation_result[span_func_name] = calc_stats(times)
        result_list = list(all_operation_result.items())
        sorted_result = sorted(result_list, key=lambda kv: (kv[1].mean * kv[1].count), reverse = True)
        return sorted_result
    
    def __calc_operation_self(self, traces):
        all_operation_self = {} # it should be a map (function name0 : [operation_self_time0, operation_self_time1, operation_self_time2, ...])
        for trace_obj in traces:
            arrows = get_arrows(trace_obj)
            for span_id, span_arrows in arrows.items():
                #calculate operation_self time for one span
                job_counter = 0
                time_counter = 0
                prev_time = 0
                for arrow in span_arrows:
                    if arrow.superscript == "begin":
                        prev_time = arrow.time
                    elif arrow.superscript == "forward":
                        if job_counter == 0:
                            time_counter = time_counter + (arrow.time - prev_time)
                        job_counter = job_counter + 1
                    elif arrow.superscript == "receive":
                        if job_counter == 1:
                            prev_time = arrow.time
                        job_counter = job_counter - 1
                    elif arrow.superscript == "terminate":
                        if job_counter == 0:
                            time_counter = time_counter + (arrow.time - prev_time)
                        break
                span = trace_obj.spans[span_id]
                span_func_name = span.get_func_name()
                if span_func_name not in all_operation_self:
                    all_operation_self[span_func_name] = []
                all_operation_self[span_func_name].append(time_counter)
                                
        all_operation_self_result = {}
        for span_func_name, times in all_operation_self.items():
            all_operation_self_result[span_func_name] = calc_stats(times)
        result_list = list(all_operation_self_result.items())
        sorted_result = sorted(result_list, key=lambda kv: (kv[1].mean * kv[1].count), reverse = True)
        return sorted_result
