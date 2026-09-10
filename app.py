"""
Bharat Fincare — Loan Portfolio Executive Board (Flask).

Local dev:
    pip install -r requirements.txt
    python app.py                 # http://127.0.0.1:5000

Production (Render / any Linux host):
    gunicorn app:app --bind 0.0.0.0:$PORT --workers 2 --threads 4 --timeout 120
"""
import os
from flask import Flask, render_template, request, jsonify

from providers import build_board, PAIRS

app = Flask(__name__)


@app.context_processor
def _static_versioning():
    """static_url('app.js') -> /static/app.js?v=<mtime> so browsers re-fetch
    changed assets after a deploy instead of serving a stale cached copy."""
    def static_url(filename):
        from flask import url_for
        path = os.path.join(app.static_folder, filename)
        try:
            v = int(os.path.getmtime(path))
        except OSError:
            v = 0
        return url_for("static", filename=filename, v=v)
    return {"static_url": static_url}


@app.route("/")
def index():
    return render_template("dashboard.html")


@app.route("/healthz")
def healthz():
    """Lightweight health check for Render (no upstream calls)."""
    return {"status": "ok"}


@app.route("/api/board")
def api_board():
    pair = request.args.get("pair", "eli_nbl")
    if pair not in PAIRS:
        pair = "eli_nbl"
    try:
        return jsonify(build_board(pair))
    except Exception as exc:  # noqa: BLE001
        app.logger.exception("board build failed")
        return jsonify({"error": str(exc)}), 500


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "5000"))
    debug = os.environ.get("FLASK_DEBUG", "").lower() in ("1", "true", "yes")
    app.run(host="0.0.0.0", port=port, debug=debug)
