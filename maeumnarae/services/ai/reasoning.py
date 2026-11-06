"""청크 경계에서 잘린 think 태그도 추론/답변으로 분리한다."""
from .types import GenerationEvent


class ThinkStreamSplitter:
    def __init__(self):
        self.buffer = ''
        self.thinking = False

    def feed(self, text: str, *, final: bool = False):
        self.buffer += text
        events = []
        while self.buffer:
            marker = '</think>' if self.thinking else '<think>'
            index = self.buffer.find(marker)
            if index >= 0:
                if index:
                    events.append(GenerationEvent('reasoning' if self.thinking else 'text', self.buffer[:index]))
                self.buffer = self.buffer[index + len(marker):]
                self.thinking = not self.thinking
                continue
            keep = 0
            if not final:
                for length in range(1, min(len(marker), len(self.buffer) + 1)):
                    if self.buffer.endswith(marker[:length]):
                        keep = length
            ready = self.buffer[:-keep] if keep else self.buffer
            if ready:
                events.append(GenerationEvent('reasoning' if self.thinking else 'text', ready))
            self.buffer = self.buffer[-keep:] if keep else ''
            break
        return events
