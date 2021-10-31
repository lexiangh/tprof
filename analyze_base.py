"""
This is the Analyze base class
"""
from abc import ABC, abstractmethod

class BaseAnalyze(ABC):
    def __init__(self, gather, app):
        # initialize the app object
        self.gather = gather
        self.app = app
            
        
    @abstractmethod
    def group(self, trace_ids):
        pass
    
    @abstractmethod
    def profile(self, trace_ids):
        pass
