"""
This file contains components for analyze_by_structure_and_order
"""
import copy
import math
import functools
import sys
import json
from abc import abstractmethod
from anytree import LevelOrderIter
from utility import GenericReprStrBase, Trace, Span, Arrow, Callee, Subspan, TNode, get_arrows, add_func_name_to_arrows, calc_stats
from analyze_base import BaseAnalyze
from pprint import pformat as pf



class Analyze(BaseAnalyze):

    @functools.total_ordering
    class resultObj(GenericReprStrBase):
        def __init__(self, length):
            self.length = length
            self.whole = []
            self.norm = [] # a lists of stats sorted by mean
            self.tail = []
            self.diff = []
            self.traces = []
            self.arrows = {}
            
        def __lt__(self, other):
            return self.length > other.length #reversed ordering

        def __eq__(self, other):
            return self.length == other.length

        def __str__(self):
            str = "Here are the time splits of:\n the all instance:\n{}\n\n the norm instance:\n{}\n\n the tail instance:\n{}\n\n the diff instance:\n{}\n\n".format(pf(self.whole), pf(self.norm), pf(self.tail), pf(self.diff))
            return str

    
    def group(self, trace_ids):
        """
        Input: a list of trace_ids
        Output: a list of lists of groups [[trace_group0], [trace_group1], ...]
        """
        trace_groups = {}
        for trace_id in trace_ids:
            arrows = self.__get_arrows_from_trace_id(trace_id)
            string_repr = self._get_string_from_arrows(arrows)
                        
            if string_repr not in trace_groups:
                trace_groups[string_repr] = []
            trace_groups[string_repr].append(trace_id)

        return trace_groups
    
    def profile(self, trace_ids):
        all_traces = []
        for trace_id in trace_ids:
            trace_obj = self.gather.get_trace(trace_id)
            all_traces.append(trace_obj)
        sorted_traces = sorted(all_traces, key=lambda trace_obj:trace_obj.T)
        idx_cutoff = math.floor(self.app.tail_cutoff/100 * len(sorted_traces))
                
        result = self.resultObj(len(trace_ids))
        result.traces = trace_ids
        result.whole = self.__calc_stat(sorted_traces)
        result.norm = self.__calc_stat(sorted_traces[:idx_cutoff])
        result.tail = self.__calc_stat(sorted_traces[idx_cutoff:])
        result.diff = self.__calc_diff(result.norm, result.tail)
        result.arrows = self.__get_arrows_from_trace_id(trace_ids[0]) #use single data point to generate the event structure
        return result

    def __calc_diff(self, norm, tail):
        diff = {}
        index = {tail[i][0]:i for i in range(len(tail))}
        for i in range(len(norm)):
            assert(norm[i][0] not in diff), "error, duplicate subspan names"
            if norm[i][0] not in index:
                continue
            diff[norm[i][0]] = tail[index[norm[i][0]]][1] - norm[i][1]
        diff_list = list(diff.items())
        sorted_diff = sorted(diff_list, key=lambda kv: kv[1].mean, reverse = True)
        return sorted_diff
    
    def _serialize_arrows(self, all_arrows):
        """
        Input: all_arrows in map
        Output: serialized_arrows in list
        """
        arrow_list = []
        for caller, callee_arrows in all_arrows.items():
            for arrow in callee_arrows:
                arrow_list.append(arrow)

        serialized_arrows = sorted(arrow_list, key=lambda Arrow:(Arrow.time, Arrow.src, Arrow.superscript, Arrow.name))
        return serialized_arrows

    def __convert_arrows_to_json_dumpable(self, arrows):
        #convert Arrow() objects to lists and eliminating unnecessary fields: time and name
        for_json = {}
        for span_name, arrows in arrows.items():
            for_json[span_name] = []
            span_arrows = for_json[span_name]
            for arrow in arrows:
                span_arrows.append([arrow.src, arrow.superscript])
            #note:span_arrows should already be sorted in get_arrows
        return for_json

    def _get_string_from_arrows(self, arrows):
        for_json = self.__convert_arrows_to_json_dumpable(arrows)
        jsonstr = json.dumps(for_json, sort_keys=True) 
        return jsonstr    
    
    def __relabel_trace(self, trace_id):
        """
        Given trace_id, relabel all the spans by adding caller info (e.g. service1 is relabeled to caller_service~service1)
        Input: trace_id in bytes
        Output: a Trace() object
        """
        trace_obj = self.gather.get_trace(trace_id)
       
        root = self.__store_in_tree_structure(trace_obj)
        self.__relabel(root)
        new_trace_obj = self.__tree_to_trace(root) #add spans to trace_obj
        new_trace_obj.trace_id = trace_obj.trace_id
        new_trace_obj.root = self.gather.master_span_name
        new_trace_obj.T = trace_obj.T
        return new_trace_obj

    def __relabel(self, node):
        index = {} # store cumulative index for naming
        for c in sorted(node.children, key=lambda node: node.start_time):
            if c.name in index:
                index[c.name] += 1
                c.name += "[" + str(index[c.name]) + "]"
            else:
                index[c.name] = 0
            self.__relabel(c)

    def __get_arrows_from_trace_id(self, trace_id):
        """
        Output:{span_name:[Arrow(), Arrow(), Arrow(), ...], ...}
                Arrows are sorted by time and then superscript (type)
        """
        trace_obj = self.__relabel_trace(trace_id)
        arrows = get_arrows(trace_obj)
        revised_arrows = add_func_name_to_arrows(trace_obj, arrows)
        return revised_arrows

    def __get_subspans_from_trace_id(self, trace_id):
        arrows = self.__get_arrows_from_trace_id(trace_id)
        subspans = self.__get_subspans(arrows)
        return subspans

    def __store_in_tree_structure(self, trace_obj):
        """
        Store a Trace() obj in a tree structure
        Input: a Trace() obj
        Output: The root of the new tree
        """
        all_nodes = {}

        # Get a set of all_span_ids
        all_span_ids = set()
        for span_id, span_obj in trace_obj.spans.items():
            all_span_ids.add(span_id)
            
        # Create all nodes
        for span_id, Span in trace_obj.spans.items():
            node_name = Span.get_func_name()
            node_start_time = Span.start_time
            node_end_time = Span.end_time
            node_sid = span_id
            new_node = TNode(node_name, node_start_time, node_end_time, node_sid)
            if node_sid not in all_nodes:
                all_nodes[node_sid] = new_node
            else:
                print("Odd, duplicated node_sid!")
                print(node_sid)
                assert(False)

        
        # Create the tree structure by assign parents to each node
        for span_id, Span in trace_obj.spans.items():
                        
            if len(Span.refs) == 1:
                parent_id = Span.refs[0] # a span should only have one parent
                current_node = all_nodes[span_id]
                parent_node =  all_nodes[parent_id]
                current_node.parent = parent_node
            elif span_id != trace_obj.root:
                print("Odd, this span doesn't have a reference or have multiple references")
                print(span_id)
                assert(False)

        return all_nodes[trace_obj.root]

    def __tree_to_trace(self, root):
        """
        Reformat tree structure to trace object
        Input: root node
        Output: a Trace() object 
        """
        trace_obj = Trace()
        trace_obj.spans = {}
        span_map = trace_obj.spans

        for node in LevelOrderIter(root):
            new_span = Span()
            new_span.service_name = self.__generate_node_name(node.path) # the service_name is the full name (path+index)
            new_span.operation_name = ""
            new_span.start_time = node.start_time
            new_span.end_time = node.end_time
            if node.parent:
                new_span.refs = [node.parent.span_id]
            else:
                new_span.refs = []
            span_map[node.span_id] = new_span

        return trace_obj

    def __generate_node_name(self, path):
        """
        Given the path from the root to a node, rename the node by adding prefixes
        Input: node.path (lib function)
        Output: new name
        """
        
        name = ""
        for node in path:
            name += node.name
            name += "~" # using "~" to seperate span names 
        return name

   
    def __get_subspans(self, all_arrows):
        """
        Create a new object Subspan() and implement the algorithm to split the spans and to get subspans :)
        Input: all_arrows in map (caller_servop, arrows)
        Output: all_subspans in map (caller_servop, subspans)
        """
        all_subspans = {}
        for caller_servop, arrows in all_arrows.items():
            if caller_servop not in all_subspans:
                all_subspans[caller_servop] = []
            subspans = all_subspans[caller_servop]
            previous_arrow = Arrow()
            _index = 0

            for current_arrow in arrows:    
                if (current_arrow.superscript == "forward") or (current_arrow.superscript == "terminate"):
                    new_subspan = Subspan()
                    new_subspan.end_time = current_arrow.time
                    new_subspan.start_time = previous_arrow.time
                    new_subspan._id = caller_servop
                    new_subspan.index = _index

                    subspans.append(new_subspan)
                    _index += 1

                previous_arrow = current_arrow

                if (current_arrow.superscript == "terminate"):
                    break
                
        return all_subspans
    
    def __collect_subspans_data(self, trace_objs):
        subspans_duration = {} #(subspan_name, [data point 1, data point 2, ...])
        for trace_obj in trace_objs:
            trace_id = bytes.fromhex(trace_obj.trace_id)
            subspan_repr = self.__get_subspans_from_trace_id(trace_id)
            for span_name, Subspans in subspan_repr.items():
                relabeled_trace = self.__relabel_trace(trace_id)
                for span_id, span_obj in relabeled_trace.spans.items(): #find the corresponding span_obj
                    if span_obj.service_name == span_name:
                        span_dur = span_obj.end_time - span_obj.start_time
                        new_span_name = span_name + "FullSpan"
                        if new_span_name not in subspans_duration:
                            subspans_duration[new_span_name] = [] #treat span as subspan with no index
                        subspans_duration[new_span_name].append(span_dur)
                        break
                for Subspan in Subspans:
                    subspan_name = span_name + str(Subspan.index)
                    if subspan_name not in subspans_duration:
                        subspans_duration[subspan_name] = []
                    subspan_data = subspans_duration[subspan_name]
                    subspan_data.append(Subspan.end_time - Subspan.start_time)
        return subspans_duration

    def __calc_stat(self, trace_objs):
        subspan_durations = self.__collect_subspans_data(trace_objs)
        subspan_results = {}
        for subspan_name, durations in subspan_durations.items():
            if subspan_name not in subspan_results:
                subspan_results[subspan_name] = []
            subspan_results[subspan_name] = calc_stats(durations)
        result_list = list(subspan_results.items())
        sorted_result = sorted(result_list, key=lambda kv: kv[1].mean if kv[0].split('~')[-1] != "FullSpan" else 0, reverse = True)
        return sorted_result
