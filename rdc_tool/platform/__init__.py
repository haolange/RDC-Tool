"""Host platform contracts with one Windows and one POSIX implementation.

Business modules use these contracts and never inspect the running OS
themselves; ``tests/test_platform_boundary.py`` enforces that rule.
"""
