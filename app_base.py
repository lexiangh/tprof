"""
This is the file for Run component
"""
from abc import ABC, abstractmethod

class App(object):
    """This is App base class"""
    def __init__(self, tail_cutoff = 90, abbrev = {}):
        self.tail_cutoff = tail_cutoff
        self.abbrev = abbrev
    
    @abstractmethod
    def trace_req_type(self):
        # return request type
        return "Unknown_request_type"

    @abstractmethod
    def get_tail_cutoff(self):
        return self.tail_cutoff

    @abstractmethod
    def get_abbrev(self):
        return self.abbrev

    class Run:
        @abstractmethod
        def run(self):
            pass
