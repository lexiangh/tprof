"""
This is the file for layer2:analyze_by_req_type component
"""
from analyze_functions import AnalyzeFunctions

class Analyze(AnalyzeFunctions):
        
    def group(self, trace_ids):
        trace_groups = {}
        for trace_id in trace_ids:
            identifier = self.app.trace_req_type(self.gather, trace_id)
            if identifier not in trace_groups:
                trace_groups[identifier] = []
            trace_groups[identifier].append(trace_id)
        return trace_groups
