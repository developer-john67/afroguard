# AgroGuard
![alt text](agroguard\image.png)

> **Hackathon prototype** — AgroGuard is a working prototype that brings crop photo diagnosis by help of locally run Qwen-2.1 and trained model for disease identification  and agro-input cryptographincproduct verification into one mobile-friendly web app. It is a demonstration project, not a production agronomy or regulatory service.
>
> **▶ YouTube project showcase:** [Watch the AgroGuard prototype walkthrough](YOUTUBE_VIDEO_URL_GOES_HERE)  
> Replace `YOUTUBE_VIDEO_URL_GOES_HERE` with the published video URL before sharing this README publicly.

## About the prototype

AgroGuard explores two practical tools for growers:

- **Crop health check:** upload or take a photo of a leaf. Local image classifiers identify supported crops and classify supported maize and tomato leaf conditions. Results include a confidence/status, possible conditions, and reference guidance where available.
- **Product verification:** scan a QR code or enter its value to check its Ed25519 signature and registry information. The demo can issue a signed sample QR code when demo mode is enabled.
- **Label review:** submit a package-label photo for information extraction and comparison with the local product registry. This feature requires a configured vision-language model provider. A label review by itself cannot prove that a product is authentic.
- **Accessible interface:** mobile-first browser UI with English, Kiswahili, French, and Hindi strings, camera and image upload options, and spoken result support.

This prototype does **not** include drone telemetry, live field sensors, a farm management platform, or a commercial product registry. Demo product/manufacturer records are fictional. Diagnosis results can be wrong; use them as informational guidance and consult a local agricultural extension professional before making treatment decisions.

## Prototype walkthrough

1. Open the app in a phone-sized browser or on a phone.
2. Choose **Check my crop**, take/upload a leaf photo, and view the diagnosis result.
3. Return home and choose **Check a product**. In demo mode, generate a sample QR code, then verify it.
4. Optionally photograph a product label to see the registry comparison (requires a vision provider).

Use the YouTube showcase linked above for the recorded walkthrough. The running application itself is the interactive prototype.

## Run locally

### Requirements

- Python 3.11
- Dependencies in `requirements.txt`
- The model weights included in this repository
- An OpenAI-compatible vision-language provider and API credentials for label-photo analysis; diagnosis can use the local classifiers without this provider

### Setup

From the `agroguard` directory:

```bash
python -m venv .venv
```

Activate the environment, then install dependencies:

```bash
# macOS / Linux
source .venv/bin/activate
pip install -r requirements.txt

# Windows PowerShell
.venv\Scripts\Activate.ps1
pip install -r requirements.txt
```

Copy `.env.example` to `.env` and configure the values you need. At minimum, set `HOST` to the URL where the app will be reached (use `http://localhost:8000` for local development). To use vision-language features, fill in a provider's API key, base URL, and model name. Keep `.env` private; it contains secrets and is excluded from Git.

Start the prototype:

```bash
python -m server.main
```

Then open [http://localhost:8000](http://localhost:8000). The API health endpoint is [http://localhost:8000/health](http://localhost:8000/health), and the interactive API docs are available at [http://localhost:8000/docs](http://localhost:8000/docs).

### Product-verification demo mode

To enable the in-app **Generate demo QR** option, set `DEMO_MODE=1` in `.env`, then start the app. The demo startup script resets the configured database and seeds/reissues demo data on each start, so do not use demo mode with data you need to keep. Set `DEMO_MODE=0` for a normal local run.

## Run with Docker

From the `agroguard` directory, create/configure `.env`, then run:

```bash
docker build -t agroguard .
docker run --rm -p 8000:8000 --env-file .env agroguard
```

Open [http://localhost:8000](http://localhost:8000). Add `-e DEMO_MODE=1` to the `docker run` command to enable the demo QR issuer; demo mode resets its database at startup.

## Project layout

```text
agroguard/
├── server/       FastAPI routes, image analysis, product verification, database
├── web/          Mobile-first frontend, styles, icons, translations
├── models/       Crop classifier weights and class lists
├── kb/           Curated disease and product reference data
├── tools/        Demo reset and signed product-code issuer
├── tests/        Automated tests
├── .env.example  Configuration template (no real credentials)
└── requirements.txt
```

## Prototype limitations

- Crop recognition and disease classification are model-based and can produce uncertain or incorrect results. Current disease classification is focused on maize and tomato; other recognized crops may be reported as unsupported.
- Label extraction and generated explanations depend on an external compatible vision-language provider and network access.
- The local SQLite registry and demo products are for demonstration. This is not an official certification or regulatory database.
- Product authenticity is checked against registered public keys and signed QR payloads. A photo of packaging or a label alone does not establish authenticity.
- The prototype has no user accounts or production access controls. Do not deploy it with sensitive data or treat the demo configuration as production-ready.

## Development

Run the test suite from the `agroguard` directory:

```bash
python -m pytest tests/ -v
```

## Hackathon project

AgroGuard was built as a hackathon prototype to demonstrate how computer vision and signed product provenance can support growers. The project showcase video is linked at the top; use the local or deployed application to explore the interactive prototype.