"""
booklib_web – Local Web Access and OPDS Server for BookLib.
"""
from booklib_web.app import create_app
from booklib_web.config import WebConfig
from booklib_web.server import WebServerThread

__all__ = ["create_app", "WebConfig", "WebServerThread"]
