from collections import deque

class RollingAverage:
    def __init__(self, n=100):
        self.window = deque(maxlen=n)
        self.running_sum = 0.0

    def add(self, value):
        if len(self.window) == self.window.maxlen:
            self.running_sum -= self.window[0]
        self.window.append(value)
        self.running_sum += value

    def get_average(self):
        if not self.window:
            return 0
        return self.running_sum / len(self.window)
