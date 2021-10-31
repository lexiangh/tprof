#!/usr/bin/python3
import sys
sys.path.append("..")
import pickle
import inflect
import copy
import hashlib
import json
from enum import Enum
from collections import OrderedDict
from utility import Trace, Span, split_servop
from app_helper import ExampleApp
import pprint as pp
import pdb

class Bug_Type(Enum):
    is_tail = 0
    l3_mode = 1

class L3_Mode(Enum):
    FS = 0 #Full span Suspicious
    CSL = 1 #Children Start Late
    LPL = 2 #Last Parts of span are Long

class Span_Tuple():
    name = 0
    children = 1
    stats = 2
    child_diff = 3
    end_diff = 4

class Ret_Tuple():
    name = 0
    content = 1

class Stats_Tuple():
    name = 0
    stats = 1

class Res_Tuple():
    name = 0
    results = 1
    children = 2

class Diff_Tuple(): #created in L3
    l3_idx = 0
    l3_group = 1
    span_path = 2
    num_of_child = 3
    child_sub_tree = 4
    span_stats = 5
    diff_idx = 6
    diff_stats = 7

class L4_Tuple():
    l4_idx = 0
    metric_value = 1
    subspan_idx = 2
    subspan_dur = 3
    subspan_pct = 4
    count = 5
    trace_id = 6
    
class Sub_Tree():
    span_name = 0
    children = 1
    
class Report():
    def __init__(self, raw_data):
        self.app = ExampleApp()
        self.root_name = "THEMASTERSPAN" #TODO: get rid of hard-coded string
        self.raw_data = raw_data
        self.search_width = {"l1":10, "l2":2, "l3":2, "l4":2} # l1, l2, l3, l4 respectively
        self.tail_multiple = 4 #Is the average of that {self.tail_multiple} times more than that of normal_operation_self?
        self.root_entry = None
        self.end_diff_idx = -1
        self.no_diff_idx = -2
        self.proc = {}
        self.agg_trace_json = {}
        self.show_subspan = True #highlight problematic (sub)span in aggregate trace
        
    def generate(self):
        return self._layer1() #call layer2() and pass the relevant data through; return appended bug reports in tree structure back

    def get_agg_trace_json(self, trace_id):
        return self.agg_trace_json.get(trace_id)
    
    def _find_worst_span(self, spans, bug_name): # for layer3
        duration_so_far = -1
        worst_span_so_far = None
        for span_tuple in spans:
            span_name = span_tuple[Span_Tuple.name]
            if span_name == bug_name:
                span_stats = span_tuple[Span_Tuple.stats]
                duration = span_stats.count * span_stats.mean
                if duration > duration_so_far:
                    worst_span_so_far = span_tuple
                    duration_so_far = duration
            duration_so_far_children, worst_span_so_far_children = _find_worst_span(span_tuple[Span_Tuple.children], bug_name)
            if duration_so_far_children > duration_so_far:
                worst_span_so_far = worst_span_so_far_children
                duration_so_far = duration_so_far_children
        return duration_so_far, worst_span_so_far

    def _calc_dur(self, spans, bug_name): # for layer3
        duration = 0
        for span_tuple in spans:
            span_name = span_tuple[Span_Tuple.name]
            if span_name == bug_name:
                span_stats = span_tuple[Span_Tuple.stats]
                duration += span_stats.count * span_stats.mean
            duration += _calc_dur(span_tuple[Span_Tuple.children], bug_name)
        return duration

    #revert simplified service_name and operation_name to their full versions
    def _inv_abbrev(self, serv, op):
        inv_abbrev = {v: k for k, v in self.app.abbrev.items()}
        full_serv = inv_abbrev[serv] if serv in inv_abbrev else serv
        full_op = inv_abbrev[op] if op in inv_abbrev else op
        return full_serv, full_op
    
    def _layer1(self):
        bug_report = {} # for storing half-baked bug report statistics
        bug_report["l1"] = {}
        bug_reports = []
        known_bugs_1 = []
        
        result1 = None
        for trace_group in self.raw_data:
            group_name = trace_group[Ret_Tuple.name]
            if group_name == Trace.name_for_good:
                result1 = trace_group
                break
        assert(result1), f"All traces are bad!"

        #start finding in layer 1
        r1_all_operation = result1[Res_Tuple.results].all_operation
        for entry in r1_all_operation:
            if entry[Span_Tuple.name] == self.root_name:
                self.root_entry = entry
                break #found and quit
        assert self.root_entry, "Error! Root entry doesn't exist in layer 1"
    
        r1_all = result1[Res_Tuple.results].all_operation_self
        bug_count = 0
        for bug in r1_all:
            bug_name = bug[Stats_Tuple.name]
            serv, op = split_servop(bug_name)
            if serv == self.root_name and not op:
                continue
            full_serv_name, full_op_name = self._inv_abbrev(serv, op)
            bug_report["l1"]["serv"] = full_serv_name
            bug_report["l1"]["op"] = full_op_name
            bug_report["l1"]["op_count"] = bug[Stats_Tuple.stats].count
            bug_report["l1"]["req_count"] = self.root_entry[Stats_Tuple.stats].count
            bug_report["l1"]["op_dur"] = bug[Stats_Tuple.stats].mean
            bug_reports.append(self._layer2(result1[Res_Tuple.children], bug_name, known_bugs_1, bug_report))
            known_bugs_1.append(bug_name)
            bug_report["l1"] = {} #restore

            if len(bug_reports) >= self.search_width["l1"]:
                break            
        return bug_reports

    """
    l2_groups: all groups to analyze in layer 2
    bug_to_find: bug name; specifically, service_name:operation_name
    bugs_found: a list of bug names that has been examined in former recursions
    bug_report: half-baked bug_report passed in from upper layers; completing it by appending more layer-specific analyzed info onto it
    """
    def _layer2(self, l2_groups, bug_to_find, bugs_found, bug_report):
        known_bugs_2 = [] #servop
        bug_report["l2"] = {}
        #bug_report_2 = bug_report["l2"]
        bug_reports = []
        is_tail = False
        #group_idx_2 = -1

        #sort l2_groups based on count*tail_avg_time
        l2_groups_sorted_by_tail = sorted(l2_groups, key = lambda group: next((bug[Stats_Tuple.stats].mean*bug[Stats_Tuple.stats].count for bug in group[Res_Tuple.results].tail_operation_self if bug[Stats_Tuple.name]==bug_to_find), 0), reverse=True)

        #sort l2_groups based on count*all_avg_time
        l2_groups_sorted_by_all = sorted(l2_groups, key = lambda group: next((bug[Stats_Tuple.stats].mean*bug[Stats_Tuple.stats].count for bug in group[Res_Tuple.results].all_operation_self if bug[Stats_Tuple.name]==bug_to_find), 0), reverse=True)
        
        for idx, result in enumerate(l2_groups_sorted_by_tail):
            r_tail = result[Res_Tuple.results].tail_operation_self
            idx = 0 #idx to look at from top down
            for i in range(0, len(r_tail)): #excluding known_bugs
                if r_tail[i][Stats_Tuple.name] not in bugs_found:
                    idx = i
                    break
            if r_tail[idx][Stats_Tuple.name] == bug_to_find:
                #found bug: top entry match bug found in 1
                bug_in_2 = r_tail[idx] #(name, stats in l2)

                #find in normal: Is the average of that X times more than that of normal-operation_excl?
                r_norm = result[Res_Tuple.results].norm_operation_self
                for idx, entry in enumerate(r_norm):
                    if entry[Stats_Tuple.name] == bug_in_2[Stats_Tuple.name]:
                        if bug_in_2[Stats_Tuple.stats].mean > self.tail_multiple * entry[Stats_Tuple.stats].mean:
                            is_tail = True 
                            bug_report["l2"][Bug_Type.is_tail.name] = True
                            bug_report["l2"]['req_type'] = result[Res_Tuple.name]
                            bug_report["l2"]['dir_l2'] = f'./layer2-{bug_report["l2"]["req_type"]}/'
                            bug_report["l2"]['tail_scale'] = bug_in_2[Stats_Tuple.stats].mean / entry[Stats_Tuple.stats].mean
                            bug_report["l2"]['l2_group_length'] = result[Res_Tuple.results].length

                            #get the average duration for root span for statistics in reports
                            root_entry_l2 = None
                            r_all_operation = result[Res_Tuple.results].all_operation
                            for entry in r_all_operation:
                                if entry[Span_Tuple.name] == self.root_name:
                                    root_entry_l2 = entry
                                    break #found and quit
                            assert root_entry_l2, "Error! Root entry doesn't exist in layer 2"
                            bug_report["l2"]["req_dur"] = root_entry_l2[Stats_Tuple.stats].pctl_99
    
                            known_bugs_2.append(result[Res_Tuple.name])
                            bug_reports.append(self._layer3(result[Res_Tuple.children], bug_to_find, is_tail, bug_report))
                            bug_report["l2"] = {} #restore
                            if len(bug_reports) >= self.search_width["l2"]:
                                return bug_reports
            
                            
        #see which group (in l2) has the largest count*duration of the bug found in l1
        for result in l2_groups_sorted_by_all:            
            if result[Res_Tuple.name] in known_bugs_2:
                continue #excluding groups that has been analyzed as tail

            r_all = result[Res_Tuple.results].all_operation_self
            for entry in r_all:
                if entry[Stats_Tuple.name] == bug_to_find: #find the right one in all
                    is_tail = False
                    bug_report["l2"][Bug_Type.is_tail.name] = False
                    bug_report["l2"]['req_type'] = result[Res_Tuple.name]
                    bug_report["l2"]["dir_l2"] = f'./layer2-{bug_report["l2"]["req_type"]}/'
                    bug_report["l2"]['l2_group_length'] = result[Res_Tuple.results].length
                    #get the average duration for root span for statistics in reports
                    root_entry_l2 = None
                    r_all_operation = result[Res_Tuple.results].all_operation
                    for entry in r_all_operation:
                        if entry[Span_Tuple.name] == self.root_name:
                            root_entry_l2 = entry
                            break #found and quit
                    assert root_entry_l2, "Error! Root entry doesn't exist in layer 2"
                    bug_report["l2"]["req_dur"] = root_entry_l2[Stats_Tuple.stats].mean

                    known_bugs_2.append(result[Res_Tuple.name])
                    bug_reports.append(self._layer3(result[Res_Tuple.children], bug_to_find, is_tail, bug_report))
                    bug_report["l2"] = {} #restore
                    if len(bug_reports) >= self.search_width["l2"]:
                        return bug_reports

        return bug_reports

    #generate tuple_sub_tree in embedded list structure e.g. ('A', [('B', []), ('C', [('D', []), ('E', [])])])
    def _get_sub_tree(self, span_tuple):
        return (span_tuple[Span_Tuple.name], [self._get_sub_tree(child) for child in span_tuple[Span_Tuple.children]])
            
    #iterating through all matching spans (i.e. invocations) in a l3 group, and return a list of (group, path, tuple_sub_tree, span_stats, diff_idx, diff_stats)
    #the path is a list: e.g. ['Root', 'B', 'A']
    def _find_spans(self, l3_idx, group, bug_to_find, span_tuples, path):
        diff_tuples = []
        for span_tuple in span_tuples:
            span_name = span_tuple[Span_Tuple.name]
            path.append(span_name)
            if span_name == bug_to_find:
                new_path = copy.deepcopy(path)
                children_tuple = span_tuple[Span_Tuple.children]
                if not children_tuple: #span doesn't have any child
                    diff_tuples.append((l3_idx, group, new_path, 0, self._get_sub_tree(span_tuple), span_tuple[Span_Tuple.stats], self.no_diff_idx, None))
                    path.remove(span_name) #restore
                    break
                for child_diff_idx, child_diff_stats in enumerate(span_tuple[Span_Tuple.child_diff]):
                    diff_tuples.append((l3_idx, group, new_path, len(children_tuple), self._get_sub_tree(span_tuple), span_tuple[Span_Tuple.stats], child_diff_idx, child_diff_stats))
                diff_tuples.append((l3_idx, group, new_path, len(children_tuple), self._get_sub_tree(span_tuple), span_tuple[Span_Tuple.stats], self.end_diff_idx, span_tuple[Span_Tuple.end_diff])) #append end_diff
            diff_tuples.extend(self._find_spans(l3_idx, group, bug_to_find, span_tuple[Span_Tuple.children], path))
            path.remove(span_name) #restore
        return diff_tuples

    """
    l3_groups: all groups to analyze in layer 3
    bug_to_find: bug name; specifically, service_name:operation_name
    bugs_found: a list of bug names that has been examined in former recursions
    bug_report: half-baked bug_report passed in from upper layers; completing it by appending more layer-specific analyzed info onto it
    Note: end_diff has index self.end_diff_idx
    """
    def _layer3(self, l3_groups, bug_to_find, is_tail, bug_report):
        diff_tuples = [] #each element is a tuple (l3_group_idx, l3_group, path_to_problematic_span, num_of_child, tuple_sub_tree, problematic_span_stats, problematic_diff_idx, corresponding_diff_stats)
        bug_reports = []
        bug_report["l3"] = {}
        group_sizes = []
        
        #find all corresponding spans and put required information in diff_info
        for l3_idx, group in enumerate(l3_groups):
            # store group size in a list, where the index is the l3_idx (starting from 0)
            group_sizes.append(group[Res_Tuple.results].length)
            results = None
            if not is_tail:
                results = [group[Res_Tuple.results].overall] #TODO: clean up []
            else:
                if not group[Res_Tuple.results].tail:
                    continue
                results = [group[Res_Tuple.results].tail]
                
            diff_tuples.extend(self._find_spans(l3_idx, group, bug_to_find, results, []))
                    
        #sort diff_info based on severity (diff_count*diff_time)
        diff_tuples.sort(key = lambda diff_tuple: diff_tuple[Diff_Tuple.diff_stats].count*diff_tuple[Diff_Tuple.diff_stats].mean if diff_tuple[Diff_Tuple.diff_stats] else 0, reverse = True)
        
        #iterating through diff_info and call layer4
        for diff_tuple in diff_tuples:
            if diff_tuple[Diff_Tuple.diff_idx] == self.no_diff_idx:
                l3_mode = L3_Mode.FS.name
                bug_report["l3"]["l3_group_idx"] = diff_tuple[Diff_Tuple.l3_idx]+1 #offset by 1
                bug_report["l3"]["ordinal_idx"] = inflect.engine().ordinal(diff_tuple[Diff_Tuple.l3_idx]+1)
                bug_report["l3"][Bug_Type.l3_mode.name] = L3_Mode.FS.name
                bug_report["l3"]["num_of_child"] = diff_tuple[Diff_Tuple.num_of_child]
                bug_report["l3"]["l3_group_length"] = group_sizes[diff_tuple[Diff_Tuple.l3_idx]]
                bug_reports.append(self._layer4(diff_tuple[Diff_Tuple.l3_group][Res_Tuple.children], diff_tuple[Diff_Tuple.span_path], diff_tuple[Diff_Tuple.child_sub_tree], diff_tuple[Diff_Tuple.diff_idx], diff_tuple[Diff_Tuple.diff_stats], is_tail, l3_mode, bug_report))
                bug_report["l3"] = {}
                
            elif diff_tuple[Diff_Tuple.diff_idx] == self.end_diff_idx:
                l3_mode = L3_Mode.LPL.name
                bug_report["l3"]["l3_group_idx"] = diff_tuple[Diff_Tuple.l3_idx]+1
                bug_report["l3"]["ordinal_idx"] = inflect.engine().ordinal(diff_tuple[Diff_Tuple.l3_idx]+1)
                bug_report["l3"][Bug_Type.l3_mode.name] = L3_Mode.LPL.name
                bug_report["l3"]["num_of_child"] = diff_tuple[Diff_Tuple.num_of_child]
                bug_report["l3"]["last_pct"] = diff_tuple[Diff_Tuple.diff_stats].mean/diff_tuple[Diff_Tuple.span_stats].mean
                bug_report["l3"]["l3_group_length"] = group_sizes[diff_tuple[Diff_Tuple.l3_idx]]
                bug_reports.append(self._layer4(diff_tuple[Diff_Tuple.l3_group][Res_Tuple.children], diff_tuple[Diff_Tuple.span_path], diff_tuple[Diff_Tuple.child_sub_tree], diff_tuple[Diff_Tuple.diff_idx], diff_tuple[Diff_Tuple.diff_stats], is_tail, l3_mode, bug_report))
                bug_report["l3"] = {}

            else:
                l3_mode = L3_Mode.CSL.name
                bug_report["l3"]["l3_group_idx"] = diff_tuple[Diff_Tuple.l3_idx]+1
                bug_report["l3"]["ordinal_idx"] = inflect.engine().ordinal(diff_tuple[Diff_Tuple.l3_idx]+1)
                bug_report["l3"][Bug_Type.l3_mode.name] = L3_Mode.CSL.name
                bug_report["l3"]["num_of_child"] = diff_tuple[Diff_Tuple.num_of_child]
                bug_report["l3"]['child_idx'] = inflect.engine().ordinal(diff_tuple[Diff_Tuple.diff_idx]+1)
                bug_report["l3"]['child_pct'] = diff_tuple[Diff_Tuple.diff_stats].mean/diff_tuple[Diff_Tuple.span_stats].mean
                bug_report["l3"]["l3_group_length"] = group_sizes[diff_tuple[Diff_Tuple.l3_idx]]
                bug_reports.append(self._layer4(diff_tuple[Diff_Tuple.l3_group][Res_Tuple.children], diff_tuple[Diff_Tuple.span_path], diff_tuple[Diff_Tuple.child_sub_tree], diff_tuple[Diff_Tuple.diff_idx], diff_tuple[Diff_Tuple.diff_stats], is_tail, l3_mode, bug_report))
                bug_report["l3"] = {}
                                
            if len(bug_reports) >= self.search_width["l3"]:
                break
        return bug_reports                

    #tree in nested tuple format defined by self._get_sub_tree()
    #sub_path is half-baked path
    def _convert_sub_tree_to_sub_paths(self, tree, sub_path=""):
        sub_path += tree[Sub_Tree.span_name] + "~" # e.g.: "A~B~"; there is always a "~" at the end of path
        sub_paths = [sub_path] #complete paths
        for child in tree[Sub_Tree.children]:
            sub_paths.extend(self._convert_sub_tree_to_sub_paths(child, sub_path))
        return sub_paths

    def _match_sub_paths(self, A, B):
        if len(A) != len(B):
            return False
        else:
            A.sort()
            B.sort()
            if A == B:
                return True
            else:
                return False

    """            
    strip indices from a path, for example:
    original: "A[1]~B[2]~C~"
    goal: "A~B~C~"
    """
    def _strip_idx(self, path):
        split_path = path.split("~")
        split_path.remove("") #remove trailing ""
        stripped_path = ""
        for elmt in split_path:
            if elmt.find("[") >= 0:
                stripped_path += elmt[:elmt.find("[")] + "~"
            else:
                stripped_path += elmt + "~"
        return stripped_path
    
    """
    Explore a bug in layer4
    bug_to_find: problematic span's path in a list (e.g. ['Root', 'A', 'B'])
    sub_tree: bug_to_find's children for identifiying the problematic span that shares path with other spans
    diff_idx: idx for the problematic child_diff (-1 for end_diff)
    diff_stats: corresponding diff statistics
    is_tail: True or False
    l3_mode: CSL(Child Start Late) or LPL(Last Part Long)
    bug_report: incomplete bug_report passed from higher layers
    #store matched paths in a dict as keys using prefix match; append all paths with common path stripped as values; convert sub_tree to a list of path; compare the sub_tree paths and l4 paths for exactly match (use len() as a quick check at the beginning; if len() matech, then sort both lists and do item-wise comparison); 
    #use metric: child_diff*subspan*count^2 to identify the problematic subspan within a span
    #loop through all l4_groups and find the one that has the largest value
    #complete the bug_report, make a deepcopy and return
    """
    def _layer4(self, l4_groups, bug_to_find, sub_tree, diff_idx, diff_stats, is_tail, l3_mode, bug_report):
        bug_reports = []
        bug_report["l4"] = {}

        l4_tuples = [] #each element is a tuple (l4_idx, metric_value, subspan_idx, subspan_dur, subspan_pct, aggregate_trace)
        group_sizes = []
        for l4_idx, group in enumerate(l4_groups):
            # store group size in a list, where the index is the l4_idx (starting from 0)
            group_sizes.append(group[Res_Tuple.results].length)
            stats = None
            if is_tail:
                stats = group[Res_Tuple.results].tail
            else:
                stats = group[Res_Tuple.results].whole

            matched_paths = {} #keys: matched prefix in l4; vals: sub_paths in l4 which share matched prefix
            for stat in stats:
                #use l4 path to find problematic span
                path = stat[Stats_Tuple.name].split('~')
                if path[-1] == "FullSpan": #only loop through span stats (i.e. excluding chunk ones)
                    path.remove("FullSpan")
                    if len(path) < len(bug_to_find):
                        continue #not the right path
                    match = True
                    matched_path = ""
                    for idx, component in enumerate(bug_to_find):
                        if path[idx].startswith(component):
                            matched_path += path[idx] + "~" #TODO: clean, store "~" in a global variable
                        else:
                            match = False
                            break
                    if match: 
                        # found match, append to matched_paths by cutting off FullSpan at the end
                        sub_path_start_idx = matched_path.rstrip("~").rfind("~")+1 #find the start idx of sub_path by finding idx of the second last "~"
                        sub_path = stat[Stats_Tuple.name][sub_path_start_idx:-len("FullSpan")]
                        stripped_sub_path = self._strip_idx(sub_path)
                        if matched_path not in matched_paths:
                            matched_paths[matched_path] = []
                        matched_paths[matched_path].append(stripped_sub_path)

            assert(len(matched_paths) >= 1), "Odd! No matched paths in layer4"

            sub_paths_to_match = self._convert_sub_tree_to_sub_paths(sub_tree)

            matched_prefixes = [] 
            if len(matched_paths) == 1:
                matched_prefixes.append(next(iter(matched_paths)))
            else:
                for path, sub_paths in matched_paths.items():
                    if self._match_sub_paths(sub_paths, sub_paths_to_match):
                        matched_prefixes.append(path)

            assert(len(matched_prefixes) >= 1), "Odd! No matched prefix"
            for prefix in matched_prefixes: #usually one, but can be multiple in cases that the target spans are indistinguishable 
                subspan_idx = -1
                if l3_mode == L3_Mode.CSL.name:
                    subspan_idx = diff_idx
                    subspan_name = prefix + str(subspan_idx)
                elif l3_mode == L3_Mode.LPL.name: #L3_Mode is LPL
                    max_subspan_idx = -1
                    for stat in stats:
                        if stat[Stats_Tuple.name].startswith(prefix) and stat[Stats_Tuple.name][len(prefix):].isnumeric():
                            if int(stat[Stats_Tuple.name][len(prefix):]) > max_subspan_idx:
                                max_subspan_idx = int(stat[Stats_Tuple.name][len(prefix):])
                    subspan_idx = max_subspan_idx
                    subspan_name = prefix + str(subspan_idx)
                else: #l3_Mode is FS
                    subspan_name = prefix + "FullSpan"
                subspan_stats = next(stat for stat in stats if stat[Stats_Tuple.name] == subspan_name)[Stats_Tuple.stats]
                span_stats = next(stat for stat in stats if stat[Stats_Tuple.name] == prefix + "FullSpan")[Stats_Tuple.stats]
                if l3_mode == L3_Mode.CSL.name or l3_mode == L3_Mode.LPL.name:
                    metric_value = subspan_stats.mean * subspan_stats.count * subspan_stats.mean/span_stats.mean #TODO: merge
                else: #l3_mode is FS
                    metric_value = subspan_stats.mean * subspan_stats.count * subspan_stats.mean/span_stats.mean
                subspan_dur = subspan_stats.mean
                subspan_pct = subspan_dur/span_stats.mean
                trace_id = str(len(self.agg_trace_json) + 1) # start with "1"
                self.agg_trace_json[trace_id] = self.generate_aggregate_trace(group[Res_Tuple.results].arrows, stats, trace_id, subspan_name)
                l4_tuple = (l4_idx, metric_value, subspan_idx, subspan_dur, subspan_pct, subspan_stats.count, trace_id)
                l4_tuples.append(l4_tuple)

        l4_tuples.sort(key = lambda l4_tuple: l4_tuple[L4_Tuple.metric_value], reverse = True)

        for l4_tuple in l4_tuples:
            #each element is a tuple (l4_idx, metric_value, subspan_idx, subspan_dur, subspan_pct)
            bug_report["l4"]['l4_group_idx'] = l4_tuple[L4_Tuple.l4_idx] + 1 #offset by 1
            bug_report["l4"]['subspan_idx'] = inflect.engine().ordinal(l4_tuple[L4_Tuple.subspan_idx]+1)
            bug_report["l4"]['subspan_dur'] = l4_tuple[L4_Tuple.subspan_dur]
            bug_report["l4"]['subspan_pct'] = l4_tuple[L4_Tuple.subspan_pct]
            bug_report["l4"]['l4_count_pct'] = l4_tuple[L4_Tuple.count]/self.root_entry[Stats_Tuple.stats].count #percentage of traces in a l4 group among all traces collected
            bug_report["l4"]['trace_id'] = l4_tuple[L4_Tuple.trace_id]
            bug_report["l4"]['l4_group_length'] = group_sizes[l4_tuple[L4_Tuple.l4_idx]]
            new_bug_report = copy.deepcopy(bug_report)
            bug_reports.append(new_bug_report)
            bug_report["l4"] = {}

            if len(bug_reports) >= self.search_width["l4"]:
                break
        return bug_reports

    
    #check if a given serviceName already had a matched process in self.proc; return process id in str (e.g. "p1") if match found, otherwise return -1;
    def get_proc(self, serviceName):
        for pid, pinfo in self.proc.items():
            if pinfo["serviceName"] == serviceName: #found match
                return pid
        return -1 #no match found

    #generate span stats in json format
    #base_time: 1617233601000000 in microseconds
    #span_id and parent_id in str; span_path example: "A~B1~C~"; span_start_time and span_time are local time in nanosec; inv_abbrev is the inverted abbrevation dict for the given application; highlight for generating/highlighting artificial subspan
    def generate_span(self, span_id, parent_id, span_path, span_start_time, span_time, trace_id, highlight=False):
        base_time = 1617233601000000
        span = {}
        span["traceID"] = trace_id
        span["spanID"] = str(span_id) #TODO: why str()?
        span["flags"] = 1

        span_path_lst = span_path.split("~")
        if not span_path_lst[-1]:
            span_path_lst.remove("")
        span_name = span_path_lst[-1]
        assert span_name, "Odd! Span name is empty"
        serv, op = split_servop(span_name)
        full_serv_name, full_op_name = self._inv_abbrev(serv, op)
        span["operationName"] = full_op_name

        if parent_id:
            span["references"] = [{"refType": "CHILD_OF", "traceID": trace_id, "spanID": parent_id}]
        else:
            span["references"] = []
        span["startTime"] = base_time + round(span_start_time/1000) 
        span["duration"] = round(span_time/1000)

        pid = -1
        if highlight:
            pid = f"p{len(self.proc)+1}"
            if span_path.split("~")[-1] == "FullSpan":
                new_proc = {pid: {"serviceName": "PROBLEMATIC_SPAN"}}
            else:
                new_proc = {pid: {"serviceName": "PROBLEMATIC_SUBSPAN"}}
            self.proc.update(new_proc)
        else:
            pid = self.get_proc(full_serv_name) #in str, e.g. "p1"

            if pid == -1: #the process with the exact service name doesn't exist; create a new one
                pid = f"p{len(self.proc)+1}"
                new_proc = {pid: {"serviceName": full_serv_name}}
                self.proc.update(new_proc)
        span["processID"] = pid
        return span

    #generate unique span_id in hex by span path, for example
    #Input: "THEMASTERSPAN"
    #Output: "c6408ae2b375c34d864538e048d721b53734c495"[:16] in str
    def generate_span_id(self, span):
        return hashlib.sha1(span.encode()).hexdigest()[:16] if span != f"{self.root_name}~" else None

    #get average duration of span or subspan specified by name from a list of stats generated in layer 4
    def get_span_or_subspan_time(self, stats, name):
        try:
            return next(stat for stat in stats if stat[Stats_Tuple.name] == name)[Stats_Tuple.stats].mean
        except StopIteration:# TODO: mak this a fall-back to layer 3
            return 0

    #generate spans in required json format
    #Inputs: span_start_time relative to the start of the root span; span path; parent span id; all_events and stats from layer 4; prob_subspan is the subspan path with idx in l4 for highlighting purpose
    def generate_spans(self, span_start_time, span, parent_id, all_events, stats, trace_id, prob_subspan):
        span_id = self.generate_span_id(span)
        span_time = self.get_span_or_subspan_time(stats, f"{span}FullSpan")
        generated_spans = [self.generate_span(span_id, parent_id, span, span_start_time, span_time, trace_id)] if span_id else []
        child_start_idx = {} # the position of the child start time in the start_time list
        start_time = [0] # local time of all associated events
        subspan_idx = 0
        events = all_events[span]
        
        for idx, event in enumerate(events):
            if event.superscript == "forward" or event.superscript == "terminate":
                subspan_start_time = start_time[-1]
                subspan_dur = self.get_span_or_subspan_time(stats, f"{span}{subspan_idx}")
                start_time.append(subspan_start_time + subspan_dur) #get subspan time
                if self.show_subspan and prob_subspan[:prob_subspan.rfind("~")+1] == span: #the current span_path match the path of the problematic subspan
                    prob_subspan_idx = prob_subspan[prob_subspan.rfind("~")+1:]
                    if prob_subspan_idx == "FullSpan" or subspan_idx == int(prob_subspan_idx): #Display full span or subspan
                        generated_spans.append(self.generate_span(self.generate_span_id(prob_subspan), span_id, prob_subspan, span_start_time+subspan_start_time, subspan_dur, trace_id, True))
                if event.superscript == "forward":
                    child_start_idx[event.name] = idx #event.name refers to the child span's name
                    generated_spans.extend(self.generate_spans(span_start_time+start_time[-1], event.name, span_id, all_events, stats, trace_id, prob_subspan))
                subspan_idx += 1
            elif event.superscript == "receive":
                start_time.append(start_time[child_start_idx[event.name]] + self.get_span_or_subspan_time(stats, f"{event.name}FullSpan")) #get child span time 
        return generated_spans
    
    #generate aggregate trace output in json format; prob_subspan is the subspan path with idx in l4 for highlighting purpose
    def generate_aggregate_trace(self, all_events, stats, trace_id, prob_subspan_name):
        spans = self.generate_spans(0, f"{self.root_name}~", None, all_events, stats, trace_id, prob_subspan_name)
        json_format = {"data": [{"traceID": trace_id, "spans": spans, "processes": self.proc}]}
        self.proc = {} #clear
        return json_format

def main():
    if not len(sys.argv) == 2:
        print("Please give path to a pickle")
        sys.exit(1)
    with open(sys.argv[1], "rb") as f:
        ret = pickle.load(f) #ret[]

    report = Report(ret)
    bug_reports = report.generate()
    pp.pprint(bug_reports)
    
if __name__ == "__main__":
    main()
