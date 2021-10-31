"""
This is the files for layer1:analyze_all_requests component
"""
from analyze_functions import AnalyzeFunctions

class Analyze(AnalyzeFunctions):

    def group(self, trace_ids):
        trace_groups = {}
        for trace_id in trace_ids:
            trace_obj = self.gather.get_trace(trace_id)
            status_str = trace_obj.get_status_str()
            if status_str not in trace_groups:
                trace_groups[status_str] = []
            trace_groups[status_str].append(trace_id)
        return trace_groups
