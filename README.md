# ⚽ Football Data Integration for Home Assistant

A custom Home Assistant integration powered by the [Football-Data.org API](https://www.football-data.org/). Effortlessly track live scores, league standings, squad info, and upcoming fixtures. Designed with native support for **Voice Assistants**, **Jinja2 templating**, and **dynamic entity state restoration**.

---

## 🌟 Key Features

* 📊 **Live League Tables & Standings:** Dynamic sensors caching entire league tables directly inside state attributes.
* 🏟️ **Team Fixtures & Results:** Dedicated sensors for **the next 5 Games** and **last played match** that update automatically per club.
* 🎙️ **Voice Assistant Ready:** Includes sentence-matching actions so assist pipelines can match fuzzy team names directly from natural speech.
* ⚡ **Smart Rate Limiting:** Dynamic polling logic accelerates update intervals during live matches and dials back during off-hours to respect API limits.
* 💾 **State Restoration:** Target teams persist across Home Assistant reboots without requiring automation re-initialisation.

---

## 📁 Repository Structure

```text
football_data/
├── hacs.json                          # HACS configuration file
├── README.md                          # Documentation
├── LICENSE                            # License file
└── custom_components/
    └── football_data/
        ├── __init__.py                # Integration setup, API coordinators, and action handlers
        ├── config_flow.py             # UI configuration flow for API key and league selection
        ├── const.py                   # Constants, API endpoints, and update intervals
        ├── manifest.json              # Integration metadata, requirements, and branding
        ├── sensor.py                  # Sensor platform definitions (Standings, Next 5, Last Match, Lookup)
        ├── services.yaml              # Action definitions for Developer Tools and Assist UI
        └── images/                    # Integration branding assets
            ├── icon.png
            └── logo.png
```

---

## ⚙️ Installation

### Option 1: HACS (Recommended)
1. Open HACS in your Home Assistant instance.
2. Click the three dots in the top right corner and select **Custom repositories**.
3. Paste the GitHub repository [URL](https://github.com/lone-baggie/football_data), select **Integration** as the category, and click **Add**.
4. Search for *Football Data*, click **Download**, and restart Home Assistant.

### Option 2: Manual Installation
1. Download the latest release zip/tarball from this repository.
2. Copy the `custom_components/football_data` directory into your Home Assistant `/config/custom_components/` folder.
3. Restart Home Assistant.

---

## 🚀 Configuration

1. Obtain a free API key from [Football-Data.org](https://www.football-data.org/).
2. In Home Assistant, navigate to **Settings** → **Devices & Services** → **Add Integration**.
3. Search for *Football Data*.
4. Enter your API Key and select the leagues you want to track (e.g., Premier League PL, Championship ELC, La Liga PD).

---

## 🛠️ Actions (Services)

This integration exposes several custom actions under the `football_data` domain:

| Action Name | Description | Key Parameters |
| :--- | :--- | :--- |
| `football_data.update_last_match` | Updates `sensor.football_data_last_match` to fetch the last finished game for a given team. | `team_id` (Required) |
| `football_data.update_next_games` | Updates `sensor.football_data_next_five_games` with upcoming fixtures for a team. | `team_id` (Required) |
| `football_data.get_league_position` | Fetches standing stats for a team across all loaded leagues. | `team_id` (Required) |
| `football_data.match_team_from_sentence` | Parses natural language sentences to extract a target team ID. | `sentence`, `favorite_club_id` |
| `football_data.get_team_id` | Looks up a numerical `team_id` from a team name string. | `team_name` (Required) |
| `football_data.get_scores_and_fixtures` | Gets past games or fixtures filtered by league, team, or matchday. | `league`, `team_id`, `matchday_number` (Optional) |
| `football_data.get_player_by_id` | Gets player information via a specific person ID. | `person_id` |
| `football_data.get_squad_by_team_id` | Gets the current team squad using a team ID. | `team_id` |
| `football_data.get_match` | Returns the last match ID for a team or a match from a specific matchday. | `team_id`, `matchday_number` (Optional) |
| `football_data.get_match_details` | Gets detailed information for a specific match. | `match_id` |
| `football_data.refresh_data` | Triggers a manual refresh of all API coordinators. | `league` (Optional) |

---

## 💡 Jinja2 Dashboard Examples

### 1. Show Last Match Scorecard
Place this inside a Markdown Card on your dashboard to display details for the last played match:

```yaml
type: markdown
title: "Last Match Result"
content: >
  {% set match = state_attr('sensor.football_data_last_match', 'homeTeam') %}
  {% if match %}
    **{{ states('sensor.football_data_last_match') }}**
    
    * **Competition:** {{ state_attr('sensor.football_data_last_match', 'competition').name }}
    * **Venue:** {{ state_attr('sensor.football_data_last_match', 'venue') }}
    * **Half Time:** {{ state_attr('sensor.football_data_last_match', 'score').halfTime.home }} - {{ state_attr('sensor.football_data_last_match', 'score').halfTime.away }}
  {% else %}
    No match data loaded.
  {% endif %}
```

### 2. Next 5 Upcoming Fixtures
Format upcoming games neatly into an itemized list:

```yaml
type: markdown
title: "Upcoming Fixtures"
content: >
  {% set matches = state_attr('sensor.football_data_next_five_games', 'matches') %}
  {% if matches %}
    {% for m in matches %}
      * **{{ m.homeTeam.shortName }}** vs **{{ m.awayTeam.shortName }}** — {{ as_timestamp(m.utcDate) | timestamp_custom('%a %b %d @ %H:%M') }}
    {% endfor %}
  {% else %}
    No upcoming fixtures found.
  {% endif %}
```
### 3. Dashboard
Use following dashboard [example](https://github.com/lone-baggie/football_data/blob/main/dashboard/dashboard.yml) by pasting over an existing blank dashboard, using the raw configuration editor (use the three dots menu top right)
![Dashboard image](https://github.com/lone-baggie/football_data/blob/main/images/dashboard.png)



---

## 🤖 Voice Assistant / Automation Example

Here is an example automation that automatically updates your last match sensor when an Assist voice command is spoken:

```yaml
alias: "Voice: Get Last Match"
trigger:
  - platform: conversation
    command:
      - "How did [the] {team} do in their last game"
      - "What was the result for {team}"
action:
  - action: football_data.match_team_from_sentence
    data:
      sentence: "{{ trigger.sentence }}"
      favorite_club_id: 57
    response_variable: team_match
  - action: football_data.update_last_match
    data:
      team_id: "{{ team_match.team_id }}"
```

---

## 📄 License

Distributed under the MIT License. See `LICENSE` for more information.