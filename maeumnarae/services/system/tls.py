"""Verified HTTPS contexts compatible with Windows enterprise trust stores."""
import ssl
import sys

import certifi


def ssl_context():
    if sys.platform != 'win32':
        return ssl.create_default_context(cafile=certifi.where())

    context = ssl.create_default_context()
    context.load_verify_locations(cafile=certifi.where())
    # Older enterprise CAs can lack Authority Key Identifier. Match pre-3.13
    # format compatibility while retaining chain and hostname verification.
    context.verify_flags &= ~ssl.VERIFY_X509_STRICT
    return context
