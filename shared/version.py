"""
UniCent version information.
"""

__version__ = "1.0.0"
__app_name__ = "UniCent"
__author__ = "JoshuaGoth Software"
__website__ = "https://joshuagoth.com"
__support_email__ = "support@joshuagoth.com"
__repo_url__ = "https://github.com/JoshuaMGoth/unicent"
__description__ = "Cross-platform mouse & keyboard sharing"

# ── Bug report server ─────────────────────────────────────────
# Endpoint URL for the Cloudflare Worker.
__report_endpoint__ = "https://bug-report-server.joshuagoth.workers.dev"

# Project-level API key — NOT a secret.  Shipped with the app
# so reports can be submitted without user configuration.
# Abuse is prevented by server-side IP rate limiting.
# Rotate via `wrangler secret put API_KEY` if compromised.
__report_api_key__ = "05ccf136101fb9b106608db13bc0c94ad15558010c7bb958f8a9aa894ead7f5f"
