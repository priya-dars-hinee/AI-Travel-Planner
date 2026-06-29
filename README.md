# AI Travel Planner Agent 🗺️

Multi-API RAG system using Gemini + OpenStreetMap + Wikivoyage for personalized travel itineraries.

## Features
- **AI Planning**: Gemini 2.5 Flash generates day-wise itineraries with reasoning
- **Real POI Data**: OpenStreetMap Overpass API for live locations
- **RAG Context**: Wikivoyage summaries for destination knowledge  
- **Interactive Map**: PyDeck PathLayer + ScatterplotLayer with tooltips
- **Feedback Loop**: Upvote/Downvote POIs → Boost scores persist in JSON
- **Fast Mode**: Toggle for 2x speed by skipping RAG + limiting POIs
- **Agent Trace**: Step-by-step execution timings in sidebar
- **Error Handling**: Graceful fallbacks + exponential backoff retry

## Tech Stack
`Streamlit` `Google Gemini` `OpenStreetMap` `PyDeck` `Wikivoyage API`

## Setup
1. Clone repo: `git clone <your-repo>`
2. Install: `pip install -r requirements.txt`
3. Add `.env` file: `GEMINI_API_KEY=your_key_here`
4. Run: `streamlit run app.py`

## API Requirements & Rate Limits
| API | Key Required | Rate Limit | Retry Logic |
| --- | --- | --- | --- |
| Google Gemini | Yes, Free | 60 req/min | Fallback to raw POIs |
| OSM Nominatim | No | 1 req/sec | 3 retries + backoff |
| OSM Overpass | No | Heavy queries timeout | 30s timeout |
| Wikivoyage | No | 200 req/sec | 10s timeout |

## Screenshots
[Add your screenshots here - Map view, Feedback UI, Agent Trace]

## Architecture