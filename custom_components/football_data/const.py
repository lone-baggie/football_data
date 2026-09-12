"""Constants for the Football Data integration."""

DOMAIN = "football_data"
CONF_API_KEY = "api_key"
CONF_LEAGUES = "leagues"

UPDATE_INTERVAL_DAILY = 86400
UPDATE_INTERVAL_STANDINGS = 3600      # Check standings hourly by default
UPDATE_INTERVAL_LIVE = 180           # Check every 3 mins during live matches
API_BASE_URL = "https://api.football-data.org/v4"

AVAILABLE_LEAGUES = {
    "PL": "Premier League (England)",
    "ELC": "Championship (England)",
    "CL": "UEFA Champions League",
    "PD": "La Liga (Spain)",
    "BL1": "Bundesliga (Germany)",
    "SA": "Serie A (Italy)",
    "FL1": "Ligue 1 (France)",
    "DED": "Eredivisie (Netherlands)",
    "PPL": "Primeira Liga (Portugal)",
    "WC": "FIFA World Cup",
}

DEFAULT_LEAGUES = ["PL", "ELC"]
