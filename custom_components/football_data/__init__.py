"""The Football Data Integration."""
import logging
import re
import aiohttp
from datetime import datetime, timezone, timedelta

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, ServiceCall, SupportsResponse
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from .const import (
    DOMAIN,
    CONF_API_KEY,
    CONF_LEAGUES,
    API_BASE_URL,
    DEFAULT_LEAGUES,
    UPDATE_INTERVAL_STANDINGS,
    UPDATE_INTERVAL_LIVE,
)

_LOGGER = logging.getLogger(__name__)

PLATFORMS = ["sensor"]


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Set up Football Data from a config entry."""
    api_key = entry.data[CONF_API_KEY]
    
    selected_leagues = entry.options.get(
        CONF_LEAGUES, entry.data.get(CONF_LEAGUES, DEFAULT_LEAGUES)
    )

    standings_coordinators = {}
    teams_coordinators = {}
    matches_coordinators = {}

    for league in selected_leagues:
        s_coord = FootballDataCoordinator(
            hass,
            api_key,
            f"{API_BASE_URL}/competitions/{league}/standings",
            f"Standings {league}",
            update_interval_seconds=UPDATE_INTERVAL_STANDINGS,
        )
        t_coord = FootballDataCoordinator(
            hass,
            api_key,
            f"{API_BASE_URL}/competitions/{league}/teams",
            f"Teams {league}",
            update_interval_seconds=UPDATE_INTERVAL_STANDINGS,
        )
        m_coord = FootballDataCoordinator(
            hass,
            api_key,
            f"{API_BASE_URL}/competitions/{league}/matches",
            f"Matches {league}",
            update_interval_seconds=UPDATE_INTERVAL_STANDINGS,
        )

        await s_coord.async_config_entry_first_refresh()
        await t_coord.async_config_entry_first_refresh()
        await m_coord.async_config_entry_first_refresh()

        standings_coordinators[league] = s_coord
        teams_coordinators[league] = t_coord
        matches_coordinators[league] = m_coord

    hass.data.setdefault(DOMAIN, {})
    hass.data[DOMAIN][entry.entry_id] = {
        "api_key": api_key,
        "selected_leagues": selected_leagues,
        "standings_coordinators": standings_coordinators,
        "teams_coordinators": teams_coordinators,
        "matches_coordinators": matches_coordinators,
        "entities": {},
    }

    entry.async_on_unload(entry.add_update_listener(update_listener))

    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)

    async def fetch_live_api(endpoint: str):
        url = f"{API_BASE_URL}{endpoint}"
        headers = {"X-Auth-Token": api_key}
        try:
            async with aiohttp.ClientSession() as session:
                async with session.get(url, headers=headers) as response:
                    if response.status != 200:
                        return {"error": f"HTTP Error {response.status}"}
                    return await response.json()
        except Exception as err:
            return {"error": f"Network fetch failed: {err}"}

    # -------------------------------------------------------------------------
    # ACTION: Match Team From Sentence
    # -------------------------------------------------------------------------
    async def handle_match_team_from_sentence(call: ServiceCall):
        """Parse sentence for partial team match starting at name prefix."""
        sentence = call.data.get("sentence", "").strip().lower()
        fav_team_id = call.data.get("favorite_club_id", 57)

        if not sentence:
            return {
                "matched": False,
                "team_id": fav_team_id,
                "team_name": "Default Favorite",
                "match_type": "fallback",
            }

        lookup_state = hass.states.get("sensor.football_data_teams_lookup")
        if not lookup_state or "teams_by_name" not in lookup_state.attributes:
            return {
                "matched": False,
                "team_id": fav_team_id,
                "team_name": "Default Favorite",
                "match_type": "fallback_sensor_unavailable",
            }

        teams_by_name = lookup_state.attributes["teams_by_name"]

        cleaned_sentence = re.sub(
            r"\b(what|whats|what's|where|how|who|whos|who's|why|when|did|will|can|is|are|the|score|result|match|fixture|game|versus|vs|playing|table|standings|next|last|football)\b",
            " ",
            sentence,
        )
        words = [w.strip() for w in cleaned_sentence.split() if len(w.strip()) > 2]

        candidates = []
        for length in range(min(4, len(words)), 0, -1):
            for i in range(len(words) - length + 1):
                candidates.append(" ".join(words[i : i + length]))

        for candidate in candidates:
            if candidate in ["united", "city", "town", "county", "fc", "real", "athletic"]:
                continue

            for full_name, t_id in teams_by_name.items():
                name_clean = full_name.lower()
                words_in_name = name_clean.split()
                if name_clean.startswith(candidate) or any(w.startswith(candidate) for w in words_in_name if len(candidate) >= 4):
                    return {
                        "matched": True,
                        "team_id": t_id,
                        "team_name": full_name,
                        "query_used": candidate,
                        "match_type": "prefix",
                    }

        return {
            "matched": False,
            "team_id": fav_team_id,
            "team_name": "Default Favorite",
            "match_type": "fallback",
        }

    # -------------------------------------------------------------------------
    # ACTION 1: Get Scores & Fixtures
    # -------------------------------------------------------------------------
    async def handle_get_scores_and_fixtures(call: ServiceCall):
        league = call.data.get("league")
        team_id = call.data.get("team_id")
        matchday = call.data.get("matchday")
        limit_last = call.data.get("limit_last")
        limit_next = call.data.get("limit_next")

        all_matches = []
        
        if league and league in matches_coordinators:
            coord_data = matches_coordinators[league].data or {}
            all_matches = coord_data.get("matches", [])
        else:
            for coord in matches_coordinators.values():
                if coord.data:
                    all_matches.extend(coord.data.get("matches", []))

        if team_id is not None and isinstance(team_id, int):
            all_matches = [
                m for m in all_matches
                if m.get("homeTeam", {}).get("id") == team_id
                or m.get("awayTeam", {}).get("id") == team_id
            ]

        if matchday is not None and isinstance(matchday, int):
            all_matches = [
                m for m in all_matches if m.get("matchday") == matchday
            ]

        if limit_last and isinstance(limit_last, int) and limit_last > 0:
            finished = [m for m in all_matches if m.get("status") == "FINISHED"]
            all_matches = finished[-limit_last:]

        elif limit_next and isinstance(limit_next, int) and limit_next > 0:
            upcoming = [
                m for m in all_matches if m.get("status") in ["SCHEDULED", "TIMED"]
            ]
            all_matches = upcoming[:limit_next]

        return {
            "team_id": team_id,
            "count": len(all_matches),
            "matches": all_matches,
        }

    # -------------------------------------------------------------------------
    # ACTION 2: Get League Position / Team Info
    # -------------------------------------------------------------------------
    async def handle_get_league_position(call: ServiceCall):
        team_id = call.data.get("team_id")

        for league_code in selected_leagues:
            sensor_entity_id = f"sensor.football_data_standings_{league_code.lower()}"
            sensor_state = hass.states.get(sensor_entity_id)

            if sensor_state and "table" in sensor_state.attributes:
                for entry_row in sensor_state.attributes["table"]:
                    if entry_row.get("team_id") == team_id:
                        return {
                            "league": league_code,
                            "position": entry_row.get("position"),
                            "team": {
                                "id": entry_row.get("team_id"),
                                "name": entry_row.get("team_name"),
                                "shortName": entry_row.get("short_name"),
                                "tla": entry_row.get("tla"),
                            },
                            "playedGames": entry_row.get("playedGames"),
                            "won": entry_row.get("won"),
                            "draw": entry_row.get("draw"),
                            "lost": entry_row.get("lost"),
                            "points": entry_row.get("points"),
                            "goalsFor": entry_row.get("goalsFor"),
                            "goalsAgainst": entry_row.get("goalsAgainst"),
                            "goalDifference": entry_row.get("goalDifference"),
                        }

        for league_code, s_coord in standings_coordinators.items():
            if not s_coord.data:
                continue
            
            standings = s_coord.data.get("standings", [])
            for table_group in standings:
                for entry_row in table_group.get("table", []):
                    if entry_row.get("team", {}).get("id") == team_id:
                        return {
                            "league": league_code,
                            "position": entry_row.get("position"),
                            "team": entry_row.get("team"),
                            "playedGames": entry_row.get("playedGames"),
                            "won": entry_row.get("won"),
                            "draw": entry_row.get("draw"),
                            "lost": entry_row.get("lost"),
                            "points": entry_row.get("points"),
                            "goalsFor": entry_row.get("goalsFor"),
                            "goalsAgainst": entry_row.get("goalsAgainst"),
                            "goalDifference": entry_row.get("goalDifference"),
                        }

        return {"error": f"Team ID {team_id} not found in loaded standings"}

    # -------------------------------------------------------------------------
    # ACTION 3: Get Team ID from Master Sensor Cache
    # -------------------------------------------------------------------------
    async def handle_get_team_id(call: ServiceCall):
        query_name = call.data.get("team_name", "").strip().lower()

        if not query_name:
            return {"error": "No team_name provided"}

        lookup_state = hass.states.get("sensor.football_data_teams_lookup")
        
        if not lookup_state or "teams_by_name" not in lookup_state.attributes:
            return {"error": "sensor.football_data_teams_lookup is unavailable"}

        teams_by_name = lookup_state.attributes["teams_by_name"]

        for full_name, t_id in teams_by_name.items():
            if full_name.lower() == query_name:
                return {
                    "team_name": full_name,
                    "team_id": t_id,
                    "match_type": "exact",
                }

        matches = []
        for full_name, t_id in teams_by_name.items():
            if query_name in full_name.lower():
                matches.append({"team_name": full_name, "team_id": t_id})

        if len(matches) == 1:
            return {
                "team_name": matches[0]["team_name"],
                "team_id": matches[0]["team_id"],
                "match_type": "partial",
            }
        elif len(matches) > 1:
            return {
                "error": "Multiple matches found",
                "query": query_name,
                "matches": matches,
            }

        return {
            "error": "Team not found in loaded leagues",
            "query": query_name,
        }

    # -------------------------------------------------------------------------
    # ACTION 4: Refresh Data On-Demand
    # -------------------------------------------------------------------------
    async def handle_refresh_data(call: ServiceCall):
        _LOGGER.info("Manual refresh triggered for Football Data coordinators")
        target_league = call.data.get("league")
        refreshed_count = 0
        
        for league_code in selected_leagues:
            if target_league and target_league.upper() != league_code:
                continue

            if league_code in standings_coordinators:
                await standings_coordinators[league_code].async_request_refresh()
                refreshed_count += 1

            if league_code in teams_coordinators:
                await teams_coordinators[league_code].async_request_refresh()
                refreshed_count += 1

            if league_code in matches_coordinators:
                await matches_coordinators[league_code].async_request_refresh()
                refreshed_count += 1

        entities = hass.data[DOMAIN][entry.entry_id].get("entities", {})
        for entity in entities.values():
            if hasattr(entity, "async_write_ha_state"):
                entity.async_write_ha_state()

        return {
            "status": "success",
            "coordinators_refreshed": refreshed_count,
            "target_league": target_league or "all",
        }

    # -------------------------------------------------------------------------
    # ACTION 5: Get Squad by Team ID
    # -------------------------------------------------------------------------
    async def handle_get_squad_by_team_id(call: ServiceCall):
        team_id = call.data.get("team_id")
        if not team_id:
            return {"error": "team_id is required"}

        data = await fetch_live_api(f"/teams/{team_id}")
        if "error" in data:
            return data

        squad = data.get("squad", [])
        parsed_squad = []

        for person in squad:
            parsed_squad.append({
                "id": person.get("id"),
                "name": person.get("name"),
                "position": person.get("position", "N/A"),
                "nationality": person.get("nationality"),
                "dateOfBirth": person.get("dateOfBirth"),
            })

        return {
            "team_id": team_id,
            "team_name": data.get("name"),
            "squad_count": len(parsed_squad),
            "squad": parsed_squad,
        }

    # -------------------------------------------------------------------------
    # ACTION 6: Get Person/Player by Person ID
    # -------------------------------------------------------------------------
    async def handle_get_player_by_id(call: ServiceCall):
        person_id = call.data.get("person_id")
        team_id = call.data.get("team_id")

        if not person_id:
            return {"error": "person_id is required"}

        if team_id:
            team_data = await fetch_live_api(f"/teams/{team_id}")
            if "error" in team_data:
                return team_data

            for person in team_data.get("squad", []):
                if person.get("id") == person_id:
                    return {
                        "id": person.get("id"),
                        "name": person.get("name"),
                        "position": person.get("position", "N/A"),
                        "nationality": person.get("nationality"),
                        "dateOfBirth": person.get("dateOfBirth"),
                        "team_id": team_id,
                        "team_name": team_data.get("name"),
                    }
            return {"error": f"Person ID {person_id} not found in squad for team {team_id}"}

        person_data = await fetch_live_api(f"/persons/{person_id}")
        if "error" not in person_data:
            current_team = person_data.get("currentTeam", {})
            return {
                "id": person_data.get("id"),
                "name": person_data.get("name"),
                "position": person_data.get("position", "N/A"),
                "nationality": person_data.get("nationality"),
                "dateOfBirth": person_data.get("dateOfBirth"),
                "team_id": current_team.get("id"),
                "team_name": current_team.get("name"),
            }

        return {"error": f"Person ID {person_id} could not be retrieved"}

    # -------------------------------------------------------------------------
    # ACTION 7: Get Match Details by Match ID
    # -------------------------------------------------------------------------
    async def handle_get_match_details(call: ServiceCall):
        match_id = call.data.get("match_id")

        if not match_id:
            return {"error": "match_id is required"}

        match_data = await fetch_live_api(f"/matches/{match_id}")

        if "error" in match_data:
            return match_data

        home_team = match_data.get("homeTeam", {})
        away_team = match_data.get("awayTeam", {})
        score = match_data.get("score", {})
        competition = match_data.get("competition", {})
        
        officials = [
            {"name": o.get("name"), "role": o.get("role")}
            for o in match_data.get("officials", [])
        ]

        return {
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

    # -------------------------------------------------------------------------
    # ACTION 8: Get Team Details by Team ID
    # -------------------------------------------------------------------------
    async def handle_get_team_details(call: ServiceCall):
        team_id = call.data.get("team_id")

        if not team_id:
            return {"error": "team_id is required"}

        data = await fetch_live_api(f"/teams/{team_id}")

        if "error" in data:
            return data

        squad = []
        for person in data.get("squad", []):
            squad.append({
                "id": person.get("id"),
                "name": person.get("name"),
                "position": person.get("position", "N/A"),
                "nationality": person.get("nationality"),
                "dateOfBirth": person.get("dateOfBirth"),
            })

        competitions = []
        for comp in data.get("runningCompetitions", []):
            competitions.append({
                "id": comp.get("id"),
                "name": comp.get("name"),
                "code": comp.get("code"),
                "type": comp.get("type"),
            })

        coach = data.get("coach", {})

        return {
            "id": data.get("id"),
            "name": data.get("name"),
            "shortName": data.get("shortName"),
            "tla": data.get("tla"),
            "crest": data.get("crest"),
            "address": data.get("address"),
            "website": data.get("website"),
            "founded": data.get("founded"),
            "clubColors": data.get("clubColors"),
            "venue": data.get("venue", "N/A"),
            "area": {
                "id": data.get("area", {}).get("id"),
                "name": data.get("area", {}).get("name"),
                "code": data.get("area", {}).get("code"),
                "flag": data.get("area", {}).get("flag"),
            },
            "coach": {
                "id": coach.get("id"),
                "name": coach.get("name"),
                "nationality": coach.get("nationality"),
                "dateOfBirth": coach.get("dateOfBirth"),
            },
            "runningCompetitions": competitions,
            "squad_count": len(squad),
            "squad": squad,
        }

    # -------------------------------------------------------------------------
    # ACTION 9: Update Next Games
    # -------------------------------------------------------------------------
    async def handle_update_next_games(call: ServiceCall):
        team_id = call.data.get("team_id")
        if not team_id:
            return {"error": "team_id is required"}

        entities = hass.data[DOMAIN][entry.entry_id].get("entities", {})
        sensor = entities.get("football_data_next_five_games")

        if sensor:
            await sensor.async_update_team_id(team_id)
            return {"status": "success", "team_id": team_id}

        return {"error": "football_data_next_five_games sensor not initialized yet"}

    # -------------------------------------------------------------------------
    # ACTION 10: Update Last Match (Now accepts team_id)
    # -------------------------------------------------------------------------
    async def handle_update_last_match(call: ServiceCall):
        team_id = call.data.get("team_id")
        if not team_id:
            return {"error": "team_id is required"}

        entities = hass.data[DOMAIN][entry.entry_id].get("entities", {})
        sensor = entities.get("football_data_last_match")

        if sensor:
            await sensor.async_update_team_id(team_id)
            return {"status": "success", "team_id": team_id}

        return {"error": "football_data_last_match sensor not initialized yet"}

    # -------------------------------------------------------------------------
    # ACTION 11: Get Match
    # -------------------------------------------------------------------------
    async def handle_get_match(call: ServiceCall):
        team_id = call.data.get("team_id")
        matchday = call.data.get("matchday")

        if not team_id:
            return {"error": "team_id is required"}

        all_matches = []
        for coord in matches_coordinators.values():
            if coord.data:
                all_matches.extend(coord.data.get("matches", []))

        team_matches = [
            m for m in all_matches
            if m.get("homeTeam", {}).get("id") == team_id
            or m.get("awayTeam", {}).get("id") == team_id
        ]

        if matchday is not None:
            for m in team_matches:
                if m.get("matchday") == matchday:
                    return {"match_id": m.get("id"), "team_id": team_id, "matchday": matchday}
            return {"error": f"No match found for team {team_id} on matchday {matchday}"}

        now_utc = datetime.now(timezone.utc)
        played_matches = []

        for m in team_matches:
            utc_str = m.get("utcDate")
            if utc_str:
                try:
                    m_date = datetime.fromisoformat(utc_str.replace("Z", "+00:00"))
                    if m_date <= now_utc:
                        played_matches.append((m_date, m.get("id")))
                except ValueError:
                    continue

        if played_matches:
            played_matches.sort(key=lambda x: x[0])
            last_match_id = played_matches[-1][1]
            return {"match_id": last_match_id, "team_id": team_id, "type": "last_played"}

        return {"error": f"No played matches found for team {team_id}"}

    # Register services
    hass.services.async_register(
        DOMAIN,
        "match_team_from_sentence",
        handle_match_team_from_sentence,
        supports_response=SupportsResponse.OPTIONAL,
    )
    hass.services.async_register(
        DOMAIN,
        "get_scores_and_fixtures",
        handle_get_scores_and_fixtures,
        supports_response=SupportsResponse.OPTIONAL,
    )
    hass.services.async_register(
        DOMAIN,
        "get_league_position",
        handle_get_league_position,
        supports_response=SupportsResponse.OPTIONAL,
    )
    hass.services.async_register(
        DOMAIN,
        "get_team_id",
        handle_get_team_id,
        supports_response=SupportsResponse.OPTIONAL,
    )
    hass.services.async_register(
        DOMAIN,
        "refresh_data",
        handle_refresh_data,
        supports_response=SupportsResponse.OPTIONAL,
    )
    hass.services.async_register(
        DOMAIN,
        "get_squad_by_team_id",
        handle_get_squad_by_team_id,
        supports_response=SupportsResponse.OPTIONAL,
    )
    hass.services.async_register(
        DOMAIN,
        "get_player_by_id",
        handle_get_player_by_id,
        supports_response=SupportsResponse.OPTIONAL,
    )
    hass.services.async_register(
        DOMAIN,
        "get_match_details",
        handle_get_match_details,
        supports_response=SupportsResponse.OPTIONAL,
    )
    hass.services.async_register(
        DOMAIN,
        "get_team_details",
        handle_get_team_details,
        supports_response=SupportsResponse.OPTIONAL,
    )
    hass.services.async_register(
        DOMAIN,
        "update_next_games",
        handle_update_next_games,
        supports_response=SupportsResponse.OPTIONAL,
    )
    hass.services.async_register(
        DOMAIN,
        "update_last_match",
        handle_update_last_match,
        supports_response=SupportsResponse.OPTIONAL,
    )
    hass.services.async_register(
        DOMAIN,
        "get_match",
        handle_get_match,
        supports_response=SupportsResponse.OPTIONAL,
    )

    return True


async def update_listener(hass: HomeAssistant, entry: ConfigEntry):
    """Reload integration when options change."""
    await hass.config_entries.async_reload(entry.entry_id)


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Unload a config entry."""
    unload_ok = await hass.config_entries.async_forward_entry_unload(entry, "sensor")
    if unload_ok:
        hass.data[DOMAIN].pop(entry.entry_id)

    return unload_ok


class FootballDataCoordinator(DataUpdateCoordinator):
    """Data coordinator handling scheduled polling per endpoint with dynamic interval support."""

    def __init__(self, hass, api_key, url, name, update_interval_seconds=UPDATE_INTERVAL_STANDINGS):
        super().__init__(
            hass,
            _LOGGER,
            name=name,
            update_interval=timedelta(seconds=update_interval_seconds),
        )
        self.api_key = api_key
        self.url = url
        self._default_interval = update_interval_seconds

    async def _async_update_data(self):
        headers = {"X-Auth-Token": self.api_key}
        try:
            async with aiohttp.ClientSession() as session:
                async with session.get(self.url, headers=headers) as response:
                    if response.status != 200:
                        raise UpdateFailed(f"HTTP Error {response.status}")
                    
                    data = await response.json()

                    if "matches" in data:
                        has_live = any(
                            m.get("status") in ["IN_PLAY", "PAUSED"]
                            for m in data.get("matches", [])
                        )
                        if has_live:
                            self.update_interval = timedelta(seconds=UPDATE_INTERVAL_LIVE)
                            _LOGGER.debug("%s has live matches. Accelerated polling to 3 minutes.", self.name)
                        else:
                            self.update_interval = timedelta(seconds=self._default_interval)

                    return data
        except Exception as err:
            raise UpdateFailed(f"Fetch failed: {err}") from err
