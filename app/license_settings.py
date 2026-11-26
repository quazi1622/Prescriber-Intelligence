"""CI replaces these public (not secret) values in packaged production builds.
Never embed signing private keys or admin tokens in the executable.
"""
WORKER_URL = ""
PUBLIC_KEY_B64 = ""
