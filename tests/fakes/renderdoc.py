"""Minimal stand-in for the native `renderdoc` module in unit tests.

Only what the runtime reaches before a test's own controller fakes take over.
Defaults follow RenderDoc's CaptureOptions documentation.
"""
from __future__ import annotations


class CaptureOptions:
    def __init__(self) -> None:
        self.allowVSync = True
        self.allowFullscreen = True
        self.apiValidation = False
        self.captureAllCmdLists = False
        self.captureCallstacks = False
        self.captureCallstacksOnlyActions = False
        self.debugOutputMute = True
        self.delayForDebugger = 0
        self.hookIntoChildren = False
        self.refAllResources = False
        self.softMemoryLimit = 0
        self.verifyBufferAccess = False
