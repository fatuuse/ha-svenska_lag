"""Constants for the Svenskalag integration."""

from datetime import timedelta

DOMAIN = "svenskalag"

# Person key (API) auth
CONF_TOKEN = "token"

# Username/password (web login) auth
CONF_DOMAIN = "domain"
CONF_TEAM_SLUG = "team_slug"
CONF_USERNAME = "username"
CONF_PASSWORD = "password"

# Options
CONF_UPDATE_HOURS = "update_hours"
DEFAULT_UPDATE_HOURS = 12  # twice a day

# Faster polling around activities
ACTIVE_INTERVAL = timedelta(minutes=5)
ACTIVE_BEFORE = timedelta(minutes=60)
ACTIVE_AFTER = timedelta(minutes=30)

API_BASE_URL = "https://api.svenskalag.se"

# How far ahead to fetch activities (API path).
DAYS_AHEAD = 60
