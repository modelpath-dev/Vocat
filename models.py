from dataclasses import dataclass, field
from typing import Optional
import time


@dataclass(frozen=True)
class Message:
    role: str
    content: Optional[str] = None
    timestamp: float = field(default_factory=time.time)

    def render(self):
        result = self.role + ":"
        if self.content is not None:
            result += " " + self.content
        return result

    def __str__(self):
        return self.render()