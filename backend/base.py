from abc import ABC, abstractmethod

class XBRLProvider(ABC):
    @abstractmethod
    def get_facts(self, identifier: str) -> dict:
        pass
