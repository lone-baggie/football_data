"""Sensor platform for Football Data integration."""
from __future__ import annotations

import logging
from typing import Any
from datetime import datetime, timezone, timedelta
import aiohttp

from homeassistant.components.sensor import SensorEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.restore_state import RestoreEntity
from homeassistant.helpers.update_coordinator import CoordinatorEntity, DataUpdateCoordinator

from .const import DOMAIN, UPDATE_INTERVAL_DAILY, API_BASE_URL

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up Football Data sensors based on a config entry."""
    data = hass.data[DOMAIN][entry.entry_id]
    teams_coordinators = data["teams_coordinators"]
    standings_coordinators = data["standings_coordinators"]
    matches_coordinators = data["matches_coordinators"]
    api_key = data["api_key"]

    first_teams_coord = next(iter(teams_coordinators.values()))

    entities: list[SensorEntity] = [
        FootballDataTeamsLookupSensor(first_teams_coord, teams_coordinators)
    ]

    for league_code, s_coord in standings_coordinators.items():
        standings_sensor = FootballDataStandingsSensor(s_coord, league_code)
        entities.append(standings_sensor)
        data["entities"][f"standings_{league_code.lower()}"] = standings_sensor

    next_five_games_sensor = FootballDataNextFiveGamesSensor(hass, api_key, matches_coordinators)
    last_match_sensor = FootballDataLastMatchSensor(hass, api_key, matches_coordinators)

    entities.append(next_five_games_sensor)
    entities.append(last_match_sensor)

    data["entities"]["football_data_next_five_games"] = next_five_games_sensor
    data["entities"]["football_data_last_match"] = last_match_sensor

    async_add_entities(entities, update_before_add=True)


class FootballDataTeamsLookupSensor(CoordinatorEntity, SensorEntity):
    """Global lookup sensor storing mapped team names and team IDs."""

    def __init__(self, coordinator: DataUpdateCoordinator, teams_coordinators: dict) -> None:
        """Initialize the team lookup sensor."""
        super().__init__(coordinator)
        self._teams_coordinators = teams_coordinators
        self._attr_name = "Football Data Teams Lookup"
        self._attr_unique_id = "football_data_teams_lookup"
        self.entity_id = "sensor.football_data_teams_lookup"
        self._attr_icon = "mdi:soccer"

    @callback
    def _handle_coordinator_update(self) -> None:
        """Handle updated data from coordinator."""
        self.async_write_ha_state()

    @property
    def native_value(self) -> int:
        """Return total unique teams indexed in cache."""
        teams_map = self.extra_state_attributes.get("teams_by_name", {})
        return len(teams_map)

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Return dictionary mapping team names to team IDs across loaded leagues."""
        teams_by_name: dict[str, int] = {}

        for coord in self._teams_coordinators.values():
            if not coord.data:
                continue

            teams = coord.data.get("teams", [])
            for team in teams:
                team_id = team.get("id")
                name = team.get("name")
                short_name = team.get("shortName")
                tla = team.get("tla")

                if name and team_id:
                    teams_by_name[name] = team_id
                if short_name and team_id:
                    teams_by_name[short_name] = team_id
                if tla and team_id:
                    teams_by_name[tla] = team_id

        return {
            "teams_by_name": teams_by_name,
            "description": "Look up a team's official ID using its name from the local cached team lookup sensor.",
        }


class FootballDataStandingsSensor(CoordinatorEntity, SensorEntity):
    """Sensor storing the entire league table inside its state attributes."""

    def __init__(self, coordinator: DataUpdateCoordinator, league_code: str) -> None:
        """Initialize the standings sensor."""
        super().__init__(coordinator)
        self._league_code = league_code
        self._attr_name = f"Football Data Standings {league_code}"
        self._attr_unique_id = f"football_data_standings_{league_code.lower()}"
        self.entity_id = f"sensor.football_data_standings_{league_code.lower()}"
        self._attr_icon = "mdi:format-list-numbered"

    @callback
    def _handle_coordinator_update(self) -> None:
        """Handle updated data from coordinator."""
        self.async_write_ha_state()

    @property
    def native_value(self) -> str:
        """Return the current 1st place leader as state."""
        if not self.coordinator.data:
            return "Unavailable"

        standings = self.coordinator.data.get("standings", [])
        if standings and "table" in standings[0] and len(standings[0]["table"]) > 0:
            leader_name = standings[0]["table"][0].get("team", {}).get("name", "Unknown")
            return f"1st: {leader_name}"

        return "Active"

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Return the full league table and standing details."""
        if not self.coordinator.data:
            return {"league": self._league_code, "table": []}

        standings = self.coordinator.data.get("standings", [])
        parsed_table = []

        if standings and "table" in standings[0]:
            for row in standings[0]["table"]:
                parsed_table.append({
                    "position": row.get("position"),
                    "team_id": row.get("team", {}).get("id"),
                    "team_name": row.get("team", {}).get("name"),
                    "short_name": row.get("team", {}).get("shortName"),
                    "tla": row.get("team", {}).get("tla"),
                    "playedGames": row.get("playedGames"),
                    "won": row.get("won"),
                    "draw": row.get("draw"),
                    "lost": row.get("lost"),
                    "points": row.get("points"),
                    "goalsFor": row.get("goalsFor"),
                    "goalsAgainst": row.get("goalsAgainst"),
                    "goalDifference": row.get("goalDifference"),
                })

        return {
            "league": self._league_code,
            "season": self.coordinator.data.get("season", {}),
            "table": parsed_table,
        }


class FootballDataNextFiveGamesSensor(CoordinatorEntity, SensorEntity, RestoreEntity):
    """Sensor to store next 5 games for configured team_id, persistent across restarts."""

    def __init__(self, hass: HomeAssistant, api_key: str, matches_coordinators: dict) -> None:
        """Initialize the next five games sensor."""
        self._api_key = api_key
        self._matches_coordinators = matches_coordinators
        self._team_id: int | None = None

        coordinator = DataUpdateCoordinator(
            hass,
            _LOGGER,
            name="Next Five Games Coordinator",
            update_method=self._async_fetch_next_games,
            update_interval=timedelta(seconds=UPDATE_INTERVAL_DAILY),
        )
        super().__init__(coordinator)
        self._attr_name = "Football Data Next Five Games"
        self._attr_unique_id = "football_data_next_five_games"
        self.entity_id = "sensor.football_data_next_five_games"
        self._attr_icon = "mdi:calendar-month"

    async def async_added_to_hass(self) -> None:
        """Restore state and persistent variables upon Home Assistant restart."""
        await super().async_added_to_hass()
        last_state = await self.async_get_last_state()
        if last_state and last_state.attributes:
            stored_team_id = last_state.attributes.get("team_id")
            if stored_team_id is not None:
                self._team_id = int(stored_team_id)
                _LOGGER.info("Restored Next Five Games target team_id: %s", self._team_id)
                await self.coordinator.async_refresh()

    @callback
    def _handle_coordinator_update(self) -> None:
        """Handle updated data from coordinator."""
        self.async_write_ha_state()

    async def _async_fetch_next_games(self) -> dict[str, Any]:
        """Fetch next 5 games directly from team matches endpoint."""
        if self._team_id is None:
            return {"team_id": None, "count": 0, "matches": []}

        today_str = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        url = f"{API_BASE_URL}/teams/{self._team_id}/matches?dateFrom={today_str}&status=SCHEDULED,TIMED,IN_PLAY,PAUSED"
        headers = {"X-Auth-Token": self._api_key}

        all_matches = []
        try:
            async with aiohttp.ClientSession() as session:
                async with session.get(url, headers=headers) as response:
                    if response.status == 200:
                        json_resp = await response.json()
                        all_matches = json_resp.get("matches", [])
                    else:
                        _LOGGER.warning("Direct team match fetch returned status %s", response.status)
        except Exception as err:
            _LOGGER.error("Failed to fetch team matches directly: %s", err)

        if not all_matches:
            for coord in self._matches_coordinators.values():
                if coord.data:
                    all_matches.extend(coord.data.get("matches", []))

            all_matches = [
                m for m in all_matches
                if m.get("homeTeam", {}).get("id") == self._team_id
                or m.get("awayTeam", {}).get("id") == self._team_id
            ]

        now_utc = datetime.now(timezone.utc)
        upcoming = []

        for m in all_matches:
            utc_str = m.get("utcDate")
            if utc_str:
                try:
                    m_date = datetime.fromisoformat(utc_str.replace("Z", "+00:00"))
                    if m_date >= (now_utc - timedelta(hours=3)):
                        upcoming.append((m_date, m))
                except ValueError:
                    upcoming.append((datetime.max.replace(tzinfo=timezone.utc), m))

        upcoming.sort(key=lambda x: x[0])
        next_matches = [item[1] for item in upcoming[:5]]

        return {
            "team_id": self._team_id,
            "count": len(next_matches),
            "matches": next_matches,
        }

    async def async_update_team_id(self, team_id: int) -> None:
        """Update active team_id and trigger immediate refresh."""
        self._team_id = team_id
        await self.coordinator.async_request_refresh()

    @property
    def native_value(self) -> str:
        """Return formatted string for the next upcoming match."""
        if self._team_id is None:
            return "No Team Selected"

        matches = self.extra_state_attributes.get("matches", [])
        if not matches:
            return "No Upcoming Fixtures"

        next_match = matches[0]

        home_team = (
            next_match.get("homeTeam", {}).get("shortName")
            or next_match.get("homeTeam", {}).get("name")
            or "Home"
        )
        away_team = (
            next_match.get("awayTeam", {}).get("shortName")
            or next_match.get("awayTeam", {}).get("name")
            or "Away"
        )

        utc_date_str = next_match.get("utcDate")
        formatted_date = ""

        if utc_date_str:
            try:
                clean_iso = utc_date_str.replace("Z", "+00:00")
                match_dt = datetime.fromisoformat(clean_iso)
                formatted_date = match_dt.strftime("%b %d")
            except ValueError:
                formatted_date = ""

        if formatted_date:
            return f"{home_team} v {away_team} {formatted_date}"
        
        return f"{home_team} v {away_team}"

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Return match details in exact get_scores_and_fixtures structure."""
        if self.coordinator.data:
            return self.coordinator.data
        return {"team_id": self._team_id, "count": 0, "matches": []}


class FootballDataLastMatchSensor(CoordinatorEntity, SensorEntity, RestoreEntity):
    """Sensor storing details for target team's most recent match, persistent across restarts."""

    def __init__(self, hass: HomeAssistant, api_key: str, matches_coordinators: dict) -> None:
        """Initialize the last match sensor."""
        self.hass = hass
        self._api_key = api_key
        self._matches_coordinators = matches_coordinators
        self._team_id: int | None = None

        coordinator = DataUpdateCoordinator(
            hass,
            _LOGGER,
            name="Last Match Coordinator",
            update_method=self._async_fetch_last_match,
            update_interval=timedelta(seconds=UPDATE_INTERVAL_DAILY),
        )
        super().__init__(coordinator)
        self._attr_name = "Football Data Last Match"
        self._attr_unique_id = "football_data_last_match"
        self.entity_id = "sensor.football_data_last_match"
        self._attr_icon = "mdi:soccer-field"

    async def async_added_to_hass(self) -> None:
        """Restore team_id and last match details upon HA reboot."""
        await super().async_added_to_hass()
        last_state = await self.async_get_last_state()
        if last_state and last_state.attributes:
            stored_team_id = last_state.attributes.get("team_id")
            if stored_team_id is not None:
                self._team_id = int(stored_team_id)
                _LOGGER.info("Restored Last Match target team_id: %s", self._team_id)
                await self.coordinator.async_refresh()

    @callback
    def _handle_coordinator_update(self) -> None:
        """Handle updated data from coordinator."""
        self.async_write_ha_state()

    async def _async_fetch_last_match(self) -> dict[str, Any]:
        """Fetch target team's finished matches and parse the latest one."""
        if self._team_id is None:
            return {"team_id": None}

        headers = {"X-Auth-Token": self._api_key}
        url = f"{API_BASE_URL}/teams/{self._team_id}/matches?status=FINISHED"

        latest_match_summary = None
        try:
            async with aiohttp.ClientSession() as session:
                async with session.get(url, headers=headers) as response:
                    if response.status == 200:
                        json_resp = await response.json()
                        matches = json_resp.get("matches", [])
                        if matches:
                            matches.sort(key=lambda x: x.get("utcDate", ""), reverse=True)
                            latest_match_summary = matches[0]
        except Exception as err:
            _LOGGER.error("Failed to fetch team's finished matches: %s", err)

        # Fallback to local coordinator cache if direct endpoint fails or yields no matches
        if not latest_match_summary:
            all_matches = []
            for coord in self._matches_coordinators.values():
                if coord.data:
                    all_matches.extend(coord.data.get("matches", []))

            finished = [
                m for m in all_matches
                if (m.get("homeTeam", {}).get("id") == self._team_id or m.get("awayTeam", {}).get("id") == self._team_id)
                and m.get("status") == "FINISHED"
            ]
            if finished:
                finished.sort(key=lambda x: x.get("utcDate", ""), reverse=True)
                latest_match_summary = finished[0]

        if not latest_match_summary:
            return {"team_id": self._team_id, "error": "No finished matches found"}

        match_id = latest_match_summary.get("id")
        detail_url = f"{API_BASE_URL}/matches/{match_id}"

        try:
            async with aiohttp.ClientSession() as session:
                async with session.get(detail_url, headers=headers) as response:
                    if response.status != 200:
                        return {"team_id": self._team_id, "error": f"HTTP Error {response.status}"}
                    match_data = await response.json()
        except Exception as err:
            return {"team_id": self._team_id, "error": f"Network fetch failed: {err}"}

        home_team = match_data.get("homeTeam", {})
        away_team = match_data.get("awayTeam", {})
        score = match_data.get("score", {})
        competition = match_data.get("competition", {})

        officials = [
            {"name": o.get("name"), "role": o.get("role")}
            for o in match_data.get("officials", [])
        ]

        return {
            "team_id": self._team_id,
            "match_id": match_data.get("id"),
            "utcDate": match_data.get("utcDate"),
            "status": match_data.get("status"),
            "matchday": match_data.get("matchday"),
            "stage": match_data.get("stage"),
            "venue": match_data.get("venue", "N/A"),
            "competition": {
                "id": competition.get("id"),
                "name": competition.get("name"),
                "code": competition.get("code"),
            },
            "homeTeam": {
                "id": home_team.get("id"),
                "name": home_team.get("name"),
                "shortName": home_team.get("shortName"),
                "tla": home_team.get("tla"),
                "crest": home_team.get("crest"),
                "formation": home_team.get("formation"),
                "lineup": home_team.get("lineup", []),
                "bench": home_team.get("bench", []),
            },
            "awayTeam": {
                "id": away_team.get("id"),
                "name": away_team.get("name"),
                "shortName": away_team.get("shortName"),
                "tla": away_team.get("tla"),
                "crest": away_team.get("crest"),
                "formation": away_team.get("formation"),
                "lineup": away_team.get("lineup", []),
                "bench": away_team.get("bench", []),
            },
            "score": {
                "winner": score.get("winner"),
                "duration": score.get("duration"),
                "fullTime": score.get("fullTime", {}),
                "halfTime": score.get("halfTime", {}),
            },
            "officials": officials,
        }

    async def async_update_team_id(self, team_id: int) -> None:
        """Set target team_id and trigger immediate match lookup refresh."""
        self._team_id = team_id
        await self.coordinator.async_request_refresh()

    @property
    def native_value(self) -> str:
        """Return match outcome score string (e.g., Arsenal 2 - 1 Chelsea)."""
        if self._team_id is None:
            return "No Team Selected"

        if not self.coordinator.data or "error" in self.coordinator.data:
            return "No Match Data"

        data = self.coordinator.data
        home = data.get("homeTeam", {}).get("shortName", "Home")
        away = data.get("awayTeam", {}).get("shortName", "Away")
        ft = data.get("score", {}).get("fullTime", {})
        h_goals = ft.get("home", 0)
        a_goals = ft.get("away", 0)

        return f"{home} {h_goals} - {a_goals} {away}"

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Return full match details in attributes, preserving team_id for persistence."""
        if self.coordinator.data:
            return self.coordinator.data
        return {"team_id": self._team_id}