"""
booklib_web.app – Flask application factory for the BookLib web interface.
"""
from __future__ import annotations

import logging
from logging.handlers import RotatingFileHandler
from pathlib import Path
from flask import Flask, render_template

from booklib.db.database import Database
from booklib.db.repository import Repository
from booklib_web.config import WebConfig
from booklib_web.opds import opds_bp
from booklib_web.routes_api import api_bp
from booklib_web.routes_files import files_bp
from booklib_web.routes_ui import ui_bp
from booklib_web.security import (
    PairingManager, RateLimiter, apply_security_headers,
)


def create_app(config: WebConfig | None = None, repo: Repository | None = None) -> Flask:
    """Create and configure the Flask application."""
    if config is None:
        config = WebConfig()

    app = Flask(
        __name__,
        template_folder=str(Path(__file__).parent / "templates"),
        static_folder=str(Path(__file__).parent / "static"),
    )

    app.config["SECRET_KEY"] = config.secret_key
    app.config["BOOKLIB_CONFIG"] = config

    # Initialize repository if not provided
    if repo is None:
        db = Database(config.db_path)
        conn = db.connect()
        repo = Repository(conn)
    app.config["BOOKLIB_REPO"] = repo

    # Security managers
    app.config["BOOKLIB_PAIRING_MGR"] = PairingManager()
    app.config["BOOKLIB_RATE_LIMITER"] = RateLimiter()

    # Logging: Rotating access log (5 files x 5 MB)
    try:
        config.log_file.parent.mkdir(parents=True, exist_ok=True)
        handler = RotatingFileHandler(
            str(config.log_file),
            maxBytes=5 * 1024 * 1024,
            backupCount=5,
            encoding="utf-8",
        )
        handler.setFormatter(
            logging.Formatter("[%(asctime)s] %(remote_addr)s %(method)s %(url)s %(status)s", "%Y-%m-%d %H:%M:%S")
        )
        # We attach a custom after_request logger
    except Exception as exc:
        app.logger.warning("Could not setup rotating web access log: %s", exc)

    # Register blueprints
    app.register_blueprint(ui_bp)
    app.register_blueprint(api_bp)
    app.register_blueprint(files_bp)
    app.register_blueprint(opds_bp)

    # Security headers
    app.after_request(apply_security_headers)

    # Error handlers
    @app.errorhandler(401)
    def unauthorized(e):
        return render_template(
            "error.html",
            code=401,
            title="Unauthorized",
            description="You must sign in or pair this device to access the library.",
        ), 401

    @app.errorhandler(403)
    def forbidden(e):
        desc = getattr(e, "description", "Action is not allowed.")
        return render_template(
            "error.html",
            code=403,
            title="Forbidden",
            description=desc,
        ), 403

    @app.errorhandler(404)
    def not_found(e):
        desc = getattr(e, "description", "The requested page or book was not found.")
        return render_template(
            "error.html",
            code=404,
            title="Not Found",
            description=desc,
        ), 404

    @app.errorhandler(429)
    def too_many_requests(e):
        desc = getattr(e, "description", "Too many requests. Please try again later.")
        return render_template(
            "error.html",
            code=429,
            title="Rate Limit Exceeded",
            description=desc,
        ), 429

    @app.errorhandler(500)
    def server_error(e):
        return render_template(
            "error.html",
            code=500,
            title="Server Error",
            description="An unexpected internal server error occurred.",
        ), 500

    return app
