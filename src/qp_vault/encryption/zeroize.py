# Copyright 2026 Quantum Pipes Technologies, LLC
# SPDX-License-Identifier: Apache-2.0

"""Key material zeroization.

Securely erases key material from memory using ctypes memset.
Python's garbage collector does not guarantee secure erasure;
this function overwrites the memory before releasing it.

For FIPS 140-3: key zeroization is required when keys are no longer needed.
"""

from __future__ import annotations

import ctypes


def zeroize(data: bytearray) -> None:
    """Securely zero out a bytearray in memory.

    Uses ctypes.memset to overwrite the buffer with zeros.
    Only works with mutable types (bytearray, not bytes).

    Args:
        data: Mutable byte buffer to zero out.
    """
    if not isinstance(data, bytearray):
        return  # Can only zeroize mutable buffers
    if len(data) == 0:
        return
    ctypes.memset(
        (ctypes.c_char * len(data)).from_buffer(data),
        0,
        len(data),
    )
