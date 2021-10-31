"""
This is the file for layer3: analyze child_diffs and end_diffs
"""
import pprint
import copy
import functools
import math
import sys
import json
import statistics
from analyze_base import BaseAnalyze
from utility import GenericReprStrBase, Trace, Span, Arrow, Callee, TNode, calc_stats, get_arrows

class Analyze(BaseAnalyze):

    @functools.total_ordering
    class resultObj(GenericReprStrBase):
        def __init__(self, length):
            self.length = length
            self.overall = None
            self.norm = None
            self.tail = None
            self.diff = None
            self.traces = []
            
        def __lt__(self, other):
            return self.length > other.length #reversed ordering

        def __eq__(self, other):
            return self.length == other.length

        def __str__(self):
            output_str = ""
            level = 0
            indent = "    "
            all_output_str = ""
            norm_output_str = "" #initialize for ease of returning
            tail_output_str = "" #same as above
            diff_output_str = ""
            if self.overall:
                all_output_str = self.__create_str([self.overall], output_str, level, indent)
            if self.norm:
                norm_output_str = self.__create_str([self.norm], output_str, level, indent)
            if self.tail:                
                tail_output_str = self.__create_str([self.tail], output_str, level, indent)
            if self.diff:                
                diff_output_str = self.__create_str([self.diff], output_str, level, indent)
            return "Here is all:\n" + all_output_str + "\n\n" + "Here is norm:\n" + norm_output_str + "\n\n" + "Here is tail:\n" + tail_output_str + "\n\n" + "Here is diff:\n" + diff_output_str 
            
        def __create_str(self, structure, output_str, level, indent):
            arrow = indent*(level-1) + "--->"
            for span_tuple in structure:
                output_str +=  arrow + str(span_tuple[0]) + "\n" + indent*level + str(span_tuple[2]) + "\n" +  indent*level + "child_diff: " + pprint.pformat(span_tuple[3], indent = level*4) + "\n" + indent*level + "end_diff: " + str(span_tuple[4]) + "\n"
                output_str = self.__create_str(span_tuple[1], output_str, level+1, indent)
            return output_str

    def group(self, trace_ids):
        """
        Input: a list of trace_ids
        Output: a list of lists of groups [[trace_group0], [trace_group1], ...]
        """
        trace_groups = {}
        for trace_id in trace_ids:
            trace_obj = self.gather.get_trace(trace_id)
            identifier = self.__generate_tree(trace_obj.root, trace_obj)           
            jsonstr = json.dumps(identifier)
            if jsonstr not in trace_groups:
                trace_groups[jsonstr] = []
            trace_groups[jsonstr].append(trace_id)
        return trace_groups
    
    def __generate_tree(self, span_id, trace_obj):
        #used in group() for generating unique identifier
        span_obj = trace_obj.spans[span_id]
        children = [self.__generate_tree(child_id, trace_obj) for child_id in span_obj.children]
        children.sort()
        return (span_obj.get_func_name(), children)

    def __generate_tree_with_start_time(self, span_id, trace_obj):
        #used in analysis phase; generate a template for __build_structure()
        span_obj = trace_obj.spans[span_id]
        children = [self.__generate_tree_with_start_time(child_id, trace_obj) for child_id in span_obj.children]
        children.sort()
        end_diff = [] #occupy a place for the time from the end of the last child to the end the parent span
        return [span_obj.get_func_name(), children, span_obj.start_time, span_obj, end_diff]
    
    def __fill_in_template_2(self, template, structure, trace_obj):        
        #handle stat for this span 
        span_obj = structure[3]
        if type(template[2]) != list: #initialize if haven't
            template[2] = []
        template[2].append(span_obj.end_time - span_obj.start_time) #

        #handle child_diff for this span
        if type(template[3]) != list: #initialize if haven't
            template[3] = []
            for j in range(len(span_obj.children)):
                template[3].append([]) # initialize if haven't #

        assert(len(template[3]) == len(span_obj.children)), "Weird children_template"

        #sort children based on start_time
        child_span_objs = []
        for child_id in span_obj.children:
            child_span_objs.append(trace_obj.spans[child_id])
        child_span_objs.sort(key=lambda span_obj:span_obj.start_time)

        prev_time = span_obj.start_time
        for c in range(len(child_span_objs)):
            template[3][c].append(child_span_objs[c].start_time - prev_time)
            prev_time = child_span_objs[c].start_time

        end_diff = template[4]
        if child_span_objs:
            end_diff.append(span_obj.end_time - child_span_objs[-1].end_time) #append end_diff for this trace
        else:#no child
            end_diff.append(0)
            
        for i in range(len(template[1])): 
            self.__fill_in_template_2(template[1][i], structure[1][i], trace_obj)

    def __calculate(self, span_tuple):
        """
        output STAT object by using raw data in filled template
        """
        span_tuple[2] = calc_stats(span_tuple[2])
        span_tuple[3] = [calc_stats(child_diff) for child_diff in span_tuple[3]]
        span_tuple[4] = calc_stats(span_tuple[4])
        for i in range(len(span_tuple[1])):
            self.__calculate(span_tuple[1][i])
        span_tuple[1].sort(key=lambda span_tuple:span_tuple[2].mean, reverse=True)
    
    def __build_structure(self, trace_objs):
        #main entrance
        example_trace_obj = trace_objs[0]
        template = self.__generate_tree_with_start_time(example_trace_obj.root, example_trace_obj) #generate a template to fill in data
        for trace_obj in trace_objs:
            structure = self.__generate_tree_with_start_time(trace_obj.root, trace_obj) #the formatted data used for filling the template
            self.__fill_in_template_2(template, structure, trace_obj)
        self.__calculate(template)
        return template

    def __calc_diff(self, norm, tail):
        assert(norm[0]==tail[0]), "norm and tail don't have the same name"
        index = {norm[1][i][0]:i for i in range(len(norm[1]))}
        children = [self.__calc_diff(norm[1][index[tail[1][i][0]]], tail[1][i]) for i in range(len(tail[1])) if tail[1][i][0] in index]
        children.sort(key=lambda span_tuple:span_tuple[2].mean, reverse=True)
        return [norm[0], children, tail[2]-norm[2], [tail[3][i]-norm[3][i] for i in range(len(tail[3]))], tail[4]-norm[4]]
    
    def profile(self, trace_ids):
        """
        Input: a list of trace_ids (in a group got from group())
        """
        
        all_traces = []
        for trace_id in trace_ids:
            trace_obj = self.gather.get_trace(trace_id)
            all_traces.append(trace_obj)
        sorted_traces = sorted(all_traces, key=lambda trace_obj:trace_obj.T)
        idx_cutoff = math.floor(self.app.tail_cutoff/100 * len(sorted_traces))
        result = self.resultObj(len(trace_ids))
        result.traces = trace_ids
        result.overall = self.__build_structure(sorted_traces)
        if len(trace_ids) == 1:
            return result # return if norm and tail are meaningless
        result.norm = self.__build_structure(sorted_traces[:idx_cutoff])
        result.tail = self.__build_structure(sorted_traces[idx_cutoff:])
        result.diff = self.__calc_diff(result.norm, result.tail)
        return result

