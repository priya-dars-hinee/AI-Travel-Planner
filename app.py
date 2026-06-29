import streamlit as st
import pydeck as pdk
import pandas as pd
import requests
import json
import os
import time
from datetime import datetime
from dotenv import load_dotenv
from google import genai
from collections import defaultdict

# ---- CONFIG ----
st.set_page_config(page_title="AI Travel Planner", layout="wide")
load_dotenv()
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")
client = genai.Client(api_key=GEMINI_API_KEY)
USER_AGENT = "trip-planner-capstone/1.0"

# ---- FEEDBACK SYSTEM ----
FEEDBACK_FILE = "feedback.json"

def load_feedback():
    if os.path.exists(FEEDBACK_FILE):
        with open(FEEDBACK_FILE, "r") as f:
            return json.load(f)
    return {}

def save_feedback(feedback_data):
    with open(FEEDBACK_FILE, "w") as f:
        json.dump(feedback_data, f, indent=2)

def calculate_boost(city, poi_name, feedback_data):
    city_data = feedback_data.get(city, {})
    poi_data = city_data.get(poi_name, {"upvotes": 0, "downvotes": 0})
    return (poi_data["upvotes"] * 0.25) + (poi_data["downvotes"] * -0.35)

# ---- OSM FUNCTIONS WITH RETRY ----
@st.cache_data(ttl=3600)
def get_coordinates(city_name):
    url = "https://nominatim.openstreetmap.org/search"
    params = {"q": city_name, "format": "json", "limit": 1}
    headers = {"User-Agent": USER_AGENT}
    try:
        response = requests.get(url, params=params, headers=headers, timeout=10)
        data = response.json()
        if data:
            return float(data[0]['lat']), float(data[0]['lon'])
    except:
        return None, None
    return None, None

@st.cache_data(ttl=3600)
def search_pois(city_name, interests):
    lat, lon = get_coordinates(city_name)
    if not lat:
        return []

    overpass_url = "https://overpass-api.de/api/interpreter"
    interest_tags = {
        "Beaches": '["natural"="beach"]', "Heritage": '["historic"]',
        "Food": '["amenity"="restaurant"]', "Nightlife": '["amenity"="bar"]',
        "Shopping": '["shop"]', "Parks": '["leisure"="park"]'
    }
    query_parts = []
    for interest in interests:
        if interest in interest_tags:
            query_parts.append(f'node{interest_tags[interest]}(around:15000,{lat},{lon});')
    if not query_parts:
        query_parts = [f'node["tourism"="attraction"](around:15000,{lat},{lon});']

    overpass_query = f"[out:json][timeout:25];({''.join(query_parts)});out body;"
    try:
        headers = {"User-Agent": USER_AGENT}
        response = requests.post(overpass_url, data=overpass_query, headers=headers, timeout=30)
        data = response.json()
    except:
        return []

    feedback_data = load_feedback()
    pois = []
    for element in data.get('elements', []):
        if 'tags' in element and 'name' in element['tags']:
            name = element['tags']['name']
            boost = calculate_boost(city_name, name, feedback_data)
            pois.append({
                'name': name, 'lat': element['lat'], 'lon': element['lon'],
                'category': element['tags'].get('tourism', 'Place'),
                'boost': boost
            })
    pois.sort(key=lambda x: x['boost'], reverse=True)
    return pois[:15]

def search_pois_with_retry(city_name, interests, max_retries=3):
    for attempt in range(max_retries):
        try:
            return search_pois(city_name, interests)
        except requests.exceptions.RequestException:
            if attempt == max_retries - 1:
                st.warning(f"OSM API failed after {max_retries} attempts. Using fallback.")
                return []
            time.sleep(2 ** attempt)
    return []

# ---- WIKIVOYAGE RAG ----
@st.cache_data(ttl=86400)
def get_wikivoyage_context(city_name):
    url = f"https://en.wikivoyage.org/w/api.php"
    params = {"action": "query", "format": "json", "titles": city_name, "prop": "extracts", "exintro": True, "explaintext": True}
    try:
        response = requests.get(url, params=params, timeout=10)
        data = response.json()
        pages = data['query']['pages']
        page_id = list(pages.keys())[0]
        if page_id!= "-1":
            return pages[page_id].get('extract', '')[:2000]
    except:
        pass
    return f"{city_name} is a popular destination."

# ---- SIDEBAR UI ----
st.sidebar.header("Trip Planner")
destination = st.sidebar.text_input("Destination", "Goa")
days = st.sidebar.slider("Trip Length (Days)", 1, 7, 2)
interests = st.sidebar.multiselect("Interests", ["Beaches", "Heritage", "Food", "Nightlife", "Shopping", "Parks"], default=["Beaches", "Heritage"])

# NEW: Fast Mode Toggle
fast_mode = st.sidebar.toggle("⚡ Fast Mode", help="Skip Wikivoyage + limit POIs for 2x speed")

if st.sidebar.button("Generate Itinerary", type="primary"):
    # Input validation
    if not destination.strip():
        st.error("Destination cannot be empty")
        st.stop()
    if len(interests) == 0:
        st.error("Select at least 1 interest")
        st.stop()
    if not GEMINI_API_KEY:
        st.error("GEMINI_API_KEY not found in.env file")
        st.stop()

    # NEW: Agent Trace with Timings
    st.session_state['trace_log'] = []
    total_start = time.time()

    with st.spinner("Step 1: Geocoding + POI Search..."):
        step_start = time.time()
        raw_pois = search_pois_with_retry(destination, interests)
        if fast_mode:
            raw_pois = raw_pois[:8] # Fast mode: limit POIs
        st.session_state['trace_log'].append(f"1. POI Search: {time.time()-step_start:.2f}s | Found {len(raw_pois)}")

    if not raw_pois:
        st.warning("No POIs found. Try different interests.")
        st.stop()

    with st.spinner("Step 2: Wikivoyage RAG..."):
        step_start = time.time()
        if fast_mode:
            wiki_context = "Fast Mode: Using basic destination info"
            st.session_state['trace_log'].append(f"2. RAG: {time.time()-step_start:.2f}s | Skipped")
        else:
            wiki_context = get_wikivoyage_context(destination)
            st.session_state['trace_log'].append(f"2. RAG: {time.time()-step_start:.2f}s | {len(wiki_context)} chars")

    with st.spinner("Step 3: Gemini AI Planning..."):
        step_start = time.time()
        prompt = f"""
        Create a {days}-day trip to {destination} for interests: {interests}.
        Context: {wiki_context}
        Use ONLY these POIs, prefer higher boost scores: {json.dumps(raw_pois)}.
        Return ONLY valid JSON: [{{"name": "POI", "lat": 15.5, "lon": 73.8, "category": "Beach", "day": "Day 1", "reason": "Why"}}]
        """
        try:
            response = client.models.generate_content(model='gemini-2.5-flash', contents=prompt)
            clean_json = response.text.strip().replace("```json", "").replace("```", "").strip()
            st.session_state['all_pois'] = json.loads(clean_json)
            st.session_state['trace_log'].append(f"3. Gemini: {time.time()-step_start:.2f}s")
        except Exception as e:
            st.error(f"Gemini failed: {e}")
            st.session_state['all_pois'] = raw_pois[:days*2] # Fallback
            st.session_state['trace_log'].append(f"3. Gemini: Failed, used fallback")

    st.session_state['trace_log'].append(f"✅ Total Time: {time.time()-total_start:.2f}s | Mode: {'Fast' if fast_mode else 'Normal'}")

# NEW: Agent Trace Viewer
if 'trace_log' in st.session_state:
    with st.sidebar.expander("⚡ Agent Trace & Timings", expanded=True):
        for log in st.session_state['trace_log']:
            st.text(log)

# ---- MAIN UI ----
all_pois = st.session_state.get('all_pois', [])
if all_pois:
    st.subheader("📍 Interactive Itinerary Map")

    df = pd.DataFrame(all_pois)
    center_lat, center_lon = df['lat'].mean(), df['lon'].mean()

    # PathLayer for daily routes
    day_wise_coords = defaultdict(list)
    for poi in all_pois:
        day_wise_coords[poi['day']].append([poi['lon'], poi['lat']])

    path_data = [{"path": coords, "name": day, "color": [255,140,0]} for day, coords in day_wise_coords.items() if len(coords) > 1]

    # Optimized map rendering
    layers = [
        pdk.Layer(
            "ScatterplotLayer",
            all_pois,
            get_position=["lon", "lat"],
            get_color=[255,140,0],
            get_radius=200,
            radius_min_pixels=5, # Optimization: consistent dot size
            radius_max_pixels=20,
            pickable=True
        ),
        pdk.Layer("PathLayer", path_data, get_color="color", width_scale=20, get_path="path")
    ]

    st.pydeck_chart(pdk.Deck(
        map_style="mapbox://styles/mapbox/dark-v10",
        initial_view_state=pdk.ViewState(latitude=center_lat, longitude=center_lon, zoom=11, pitch=45),
        layers=layers,
        tooltip={"html": "<b>{name}</b><br/>Day: {day}<br/>Why: {reason}", "style": {"color": "white"}}
    ))

    # ---- POI-LEVEL FEEDBACK UI ----
    st.subheader("📝 Itinerary + Feedback")
    feedback_data = load_feedback()

    for day in sorted(set([p['day'] for p in all_pois])):
        with st.expander(f"{day}", expanded=True):
            day_pois = [p for p in all_pois if p['day'] == day]
            for idx, poi in enumerate(day_pois):
                col1, col2, col3 = st.columns([3, 1, 1])
                with col1:
                    st.markdown(f"**{poi['name']}** - *{poi['category']}*")
                    st.caption(poi.get('reason', 'Must visit'))
                with col2:
                    if st.button("👍", key=f"up_{destination}_{poi['name']}_{idx}"):
                        if destination not in feedback_data: feedback_data[destination] = {}
                        if poi['name'] not in feedback_data[destination]:
                            feedback_data[destination][poi['name']] = {"upvotes": 0, "downvotes": 0}
                        feedback_data[destination][poi['name']]["upvotes"] += 1
                        feedback_data[destination][poi['name']]["timestamp"] = datetime.now().isoformat()
                        save_feedback(feedback_data)
                        st.toast(f"Upvoted {poi['name']}")
                        st.rerun()
                with col3:
                    if st.button("👎", key=f"down_{destination}_{poi['name']}_{idx}"):
                        if destination not in feedback_data: feedback_data[destination] = {}
                        if poi['name'] not in feedback_data[destination]:
                            feedback_data[destination][poi['name']] = {"upvotes": 0, "downvotes": 0}
                        feedback_data[destination][poi['name']]["downvotes"] += 1
                        feedback_data[destination][poi['name']]["timestamp"] = datetime.now().isoformat()
                        save_feedback(feedback_data)
                        st.toast(f"Downvoted {poi['name']}")
                        st.rerun()

    # ---- FEEDBACK STATS ----
    with st.sidebar.expander("📊 Feedback Stats"):
        feedback_data = load_feedback()
        if destination in feedback_data:
            for poi, stats in feedback_data[destination].items():
                boost = (stats["upvotes"] * 0.25) + (stats["downvotes"] * -0.35)
                st.write(f"{poi}: 👍{stats['upvotes']} 👎{stats['downvotes']} | Boost: {boost:.2f}")
else:
    st.info("👈 Generate Itinerary to start")