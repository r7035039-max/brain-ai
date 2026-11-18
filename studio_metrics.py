"""Read-only memory sampling without a heavyweight process dependency."""
import ctypes
import os
from pathlib import Path


def memory_usage(pid=None):
    result = {'total_bytes': None, 'available_bytes': None, 'process_bytes': None}
    try:
        if os.name == 'nt':
            from ctypes import wintypes
            class MemoryStatus(ctypes.Structure):
                _fields_ = [('length', wintypes.DWORD), ('load', wintypes.DWORD)] + [
                    (name, ctypes.c_ulonglong) for name in ('total_phys', 'avail_phys', 'total_page', 'avail_page',
                                                          'total_virtual', 'avail_virtual', 'avail_extended')]
            kernel = ctypes.WinDLL('kernel32', use_last_error=True)
            kernel.GlobalMemoryStatusEx.argtypes = [ctypes.POINTER(MemoryStatus)]
            kernel.GlobalMemoryStatusEx.restype = wintypes.BOOL
            status = MemoryStatus()
            status.length = ctypes.sizeof(status)
            if kernel.GlobalMemoryStatusEx(ctypes.byref(status)):
                result.update(total_bytes=status.total_phys, available_bytes=status.avail_phys)
            if pid:
                class ProcessMemory(ctypes.Structure):
                    _fields_ = [('cb', wintypes.DWORD), ('faults', wintypes.DWORD)] + [
                        (name, ctypes.c_size_t) for name in ('peak_working', 'working', 'peak_paged', 'paged',
                                                           'peak_nonpaged', 'nonpaged', 'pagefile', 'peak_pagefile', 'private')]
                kernel.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
                kernel.OpenProcess.restype = wintypes.HANDLE
                kernel.CloseHandle.argtypes = [wintypes.HANDLE]
                psapi = ctypes.WinDLL('psapi', use_last_error=True)
                psapi.GetProcessMemoryInfo.argtypes = [wintypes.HANDLE, ctypes.POINTER(ProcessMemory), wintypes.DWORD]
                psapi.GetProcessMemoryInfo.restype = wintypes.BOOL
                handle = kernel.OpenProcess(0x1000 | 0x10, False, int(pid))
                if handle:
                    try:
                        memory = ProcessMemory()
                        memory.cb = ctypes.sizeof(memory)
                        if psapi.GetProcessMemoryInfo(handle, ctypes.byref(memory), memory.cb):
                            result['process_bytes'] = memory.working
                    finally:
                        kernel.CloseHandle(handle)
        else:
            fields = {}
            for line in Path('/proc/meminfo').read_text().splitlines():
                key, value = line.split(':', 1)
                fields[key] = int(value.strip().split()[0]) * 1024
            result.update(total_bytes=fields.get('MemTotal'), available_bytes=fields.get('MemAvailable'))
            if pid:
                for line in Path(f'/proc/{int(pid)}/status').read_text().splitlines():
                    if line.startswith('VmRSS:'): result['process_bytes'] = int(line.split()[1]) * 1024
    except (OSError, ValueError, AttributeError):
        pass
    return result
