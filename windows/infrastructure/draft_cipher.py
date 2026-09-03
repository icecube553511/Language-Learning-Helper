"""Small credential-free cipher boundary for locally persisted draft state.

The Windows client uses the OS Data Protection API (DPAPI), which binds the
encrypted value to the current Windows user/profile.  The repository accepts a
duck-typed ``DraftCipher`` so tests and non-Windows tooling can inject a
deterministic implementation without weakening the production default.
"""

from __future__ import annotations

import ctypes
import os
from ctypes import wintypes
from typing import Protocol


class DraftCipherError(Exception):
    """Raised when a draft cannot be protected or unprotected."""


class DraftCipher(Protocol):
    """Port implemented by a platform secure-storage cipher."""

    def encrypt(self, plaintext: bytes) -> bytes: ...

    def decrypt(self, ciphertext: bytes) -> bytes: ...


class DpapiDraftCipher:
    """Windows DPAPI adapter with no persisted key material."""

    _CRYPTPROTECT_UI_FORBIDDEN = 0x1

    class _DataBlob(ctypes.Structure):
        _fields_ = [
            ("cbData", wintypes.DWORD),
            ("pbData", ctypes.POINTER(ctypes.c_ubyte)),
        ]

    @property
    def available(self) -> bool:
        return os.name == "nt"

    def encrypt(self, plaintext: bytes) -> bytes:
        return self._transform(plaintext, protect=True)

    def decrypt(self, ciphertext: bytes) -> bytes:
        return self._transform(ciphertext, protect=False)

    def _transform(self, value: bytes, *, protect: bool) -> bytes:
        if not isinstance(value, bytes):
            raise TypeError("draft cipher input must be bytes")
        if not self.available:
            raise DraftCipherError("Windows DPAPI is unavailable")
        if not value:
            # A zero-length value would otherwise be indistinguishable from a
            # missing ciphertext in the repository.  Reject it explicitly so
            # the cipher boundary never treats plaintext emptiness as a valid
            # protected snapshot.
            raise DraftCipherError("draft cipher input must not be empty")
        try:
            crypt32 = ctypes.WinDLL("crypt32", use_last_error=True)
            kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
            function_name = "CryptProtectData" if protect else "CryptUnprotectData"
            function = getattr(crypt32, function_name)
            blob_type = self._DataBlob
            function.argtypes = [
                ctypes.POINTER(blob_type),
                wintypes.LPCWSTR,
                ctypes.POINTER(blob_type),
                wintypes.LPVOID,
                wintypes.LPVOID,
                wintypes.DWORD,
                ctypes.POINTER(blob_type),
            ]
            function.restype = wintypes.BOOL
            source_buffer = ctypes.create_string_buffer(value)
            source = blob_type(
                len(value),
                ctypes.cast(source_buffer, ctypes.POINTER(ctypes.c_ubyte)),
            )
            output = blob_type()
            ok = function(
                ctypes.byref(source),
                None,
                None,
                None,
                None,
                self._CRYPTPROTECT_UI_FORBIDDEN,
                ctypes.byref(output),
            )
            if not ok:
                raise DraftCipherError("Windows DPAPI operation failed")
            try:
                return ctypes.string_at(output.pbData, output.cbData)
            finally:
                if output.pbData:
                    kernel32.LocalFree.argtypes = [ctypes.c_void_p]
                    kernel32.LocalFree.restype = ctypes.c_void_p
                    kernel32.LocalFree(output.pbData)
        except DraftCipherError:
            raise
        except (AttributeError, OSError, TypeError, ValueError) as error:
            # Do not include API details or input values in the exception;
            # callers may surface this message in a UI/log.
            raise DraftCipherError("Windows DPAPI operation failed") from error


def default_draft_cipher() -> DraftCipher:
    """Return the platform cipher used by the Windows composition root.

    On non-Windows hosts this still returns a DPAPI object, which fails closed
    instead of silently persisting draft plaintext.  Tests can pass an
    injected cipher to ``JsonLearningRepository``.
    """

    return DpapiDraftCipher()
