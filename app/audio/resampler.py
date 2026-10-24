"""Small stateful polyphase resampler shared by audio capture backends."""
from math import gcd

import numpy as np
from scipy.signal import resample_poly


class Resampler:
    """Resample mono chunks while carrying incomplete input across callbacks."""

    def __init__(self, native_rate, target_rate):
        self.native_rate = native_rate
        self.target_rate = target_rate
        divisor = gcd(native_rate, target_rate)
        self._up = target_rate // divisor
        self._down = native_rate // divisor
        self._buf = np.array([], dtype=np.float32)

    def push(self, arr):
        if arr.size == 0 and self._buf.size == 0:
            return np.array([], dtype=np.float32)
        if self._up == self._down:
            if self._buf.size:
                out = np.concatenate([self._buf, arr])
                self._buf = np.array([], dtype=np.float32)
                return out
            return arr.astype(np.float32, copy=False)

        combined = np.concatenate([self._buf, arr]) if self._buf.size else arr
        usable = (len(combined) // self._down) * self._down
        if usable == 0:
            self._buf = combined
            return np.array([], dtype=np.float32)
        chunk = combined[:usable]
        self._buf = combined[usable:]
        return resample_poly(chunk, self._up, self._down).astype(np.float32)
