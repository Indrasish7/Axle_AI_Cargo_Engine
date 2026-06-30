# Axle AI — B2B Cargo Matching & Fleet Operations Platform

Axle AI is a premium, high-density fleet logistics and cargo matching engine. It ingests conversational freight requests from shippers (via WhatsApp), parses cargo properties using Large Language Models, matches them geospatially with carrier vehicles, captures escrow payments, and tracks transit dynamically using an interactive dark-mode map.

---

## ✨ Features

*   **Conversational Order Ingestion**: Integrates with the official Meta WhatsApp Cloud API to receive unstructured text messages from shippers.
*   **LLM Parsing Engine**: Leverages Google's `Gemini 2.5 Flash` (via the Google GenAI SDK) to extract structured cargo metadata (items, weights, budgets) into validated Pydantic schemas.
*   **Geospatial Matcher**: Employs Haversine vector calculations to automatically match cargo requests to the closest compatible available vehicle within a 100km radius.
*   **Asynchronous Task Queue**: Uses Celery + Redis for out-of-band processing, responding to Meta webhooks under 50ms (HTTP 202 Accepted) to comply with carrier timeouts.
*   **Thread-Safe Eager Fallback**: Automatically falls back to a background `ThreadPoolExecutor` if the Redis server is unreachable, ensuring Uvicorn is never blocked.
*   **Real-time Driver Telemetry Simulator**: Tracks active bookings in `ESCROW_AUTHORIZED` state, generates linear route interpolation steps, calculates real-time compass bearings, and updates positions in-memory and in SQLite.
*   **Obsidian Control Room Dashboard**: A premiumSingle Page Application (SPA) dashboard featuring:
    *   Unified operations KPI stats.
    *   Neon status-glow active bookings ledger.
    *   Inverted dark-mode LeafletJS map tracking moving vehicles in real-time.
    *   Suggested action triggers to bypass WhatsApp sandbox clients for testing.

---

## 🛠️ Architecture & Flow

```text
Shipper Message (WhatsApp) 
      │
      ▼
Meta Graph API Webhook ──► ngrok Public Tunnel
                                │
                                ▼
                        FastAPI Server (/webhook) ──► Enqueue task (.delay())
                                │                                 │
                     (HTTP 202 Accepted, <50ms)                   ▼
                                                      Celery Worker (Eager Fallback)
                                                                  │
                                                        ┌─────────┴─────────┐
                                                        ▼                   ▼
                                                   Gemini 2.5        Geospatial Matcher
                                                  (LLM Parser)      (Haversine Proximity)
                                                        │                   │
                                                        └─────────┬─────────┘
                                                                  ▼
                                                          SQLite DB (WAL)
                                                                  │
                                                                  ▼
                                                      Operations Dashboard Map
                                                     (LeafletJS Inverted Tiles)
```

---

## 🚀 Getting Started

### 1. Prerequisites
Ensure you have Python 3.11+ installed.

### 2. Installation
1. Clone this repository:
   ```bash
   git clone https://github.com/Indrasish7/Axle_AI_Cargo_Engine.git
   cd Axle_AI_Cargo_Engine
   ```
2. Initialize virtual environment and install dependencies:
   ```bash
   python -m venv .venv
   .venv\Scripts\activate      # On Windows
   source .venv/bin/activate   # On macOS/Linux
   pip install -r requirements.txt
   ```

### 3. Environment Variables
Create a `.env` file in the root directory:
```env
GEMINI_API_KEY=your_gemini_api_key
META_ACCESS_TOKEN=your_meta_whatsapp_access_token
META_PHONE_NUMBER_ID=your_whatsapp_phone_number_id
META_VERIFY_TOKEN=axle_secret_2026
```

### 4. Running the Platform
For local development, run the services concurrently:

1.  **FastAPI Web API & Dashboard**:
    ```bash
    python main.py
    ```
2.  **Celery Worker**:
    ```bash
    celery -A src.workers worker --loglevel=info -P solo
    ```
3.  **Real-Time Telemetry Simulator**:
    ```bash
    python src/telemetry_simulator.py
    ```
4.  **ngrok Gateway exposure**:
    ```bash
    python src/gateway_launcher.py
    ```

Open your browser and navigate to **`http://localhost:8000/dashboard`** to access the Control Room.

---

## 🔒 Security & Concurrency Design
*   **Database Lock Guard**: SQLite transactions are forced using `BEGIN IMMEDIATE` write-locks to prevent database locks or race conditions during concurrent matching sessions.
*   **LLM Isolation**: External LLM network requests are processed outside transaction scopes to prevent database lock starvation.
*   **Secrets Shield**: Credentials are kept strictly in `.env` and excluded from version control using `.gitignore`.
