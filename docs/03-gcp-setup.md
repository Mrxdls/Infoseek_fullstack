# 03 — GCP Setup

This guide walks through every GCP resource the project needs. All steps are done through the GCP web console.

---

## Step 1 — Create or Select a GCP Project

1. Go to [console.cloud.google.com](https://console.cloud.google.com)
2. Click the project dropdown at the top → **New Project**
3. Name it (e.g., `studyrag-dev`) — GCP auto-generates a project ID like `studyrag-dev-123456`
4. Note your **Project ID** (not the name) — you'll put this in `.env` as `GCP_PROJECT_ID`

> Your project ID appears in the top bar and in the URL when you're in the console.

---

## Step 2 — Enable Required APIs

Navigate to **APIs & Services → Library** in the console. Search for and enable each of these:

| API Name | What it's for |
|----------|-------------|
| **Vertex AI API** | Gemini text generation + embeddings |
| **Cloud Storage API** | Storing uploaded PDFs in GCS |
| **Cloud Vision API** | OCR on scanned/image PDFs |

For each:
1. Click the API name
2. Click **Enable**
3. Wait ~30 seconds

You can also enable them via command line if you have `gcloud` installed:
```bash
gcloud services enable aiplatform.googleapis.com
gcloud services enable storage.googleapis.com
gcloud services enable vision.googleapis.com
```

---

## Step 3 — Create a GCS Bucket

Google Cloud Storage buckets are like folders in the cloud. Uploaded PDFs will be stored here.

1. Go to **Cloud Storage → Buckets** → **Create**
2. Choose a **globally unique bucket name** (e.g., `studyrag-documents-yourname`) — note this for `.env` as `GCS_BUCKET_NAME`
3. **Location type:** Region
4. **Region:** `us-central1` (or the same region you'll use for Vertex AI — keep them the same to avoid egress costs)
5. **Storage class:** Standard
6. **Access control:** Uniform
7. Leave other settings default → **Create**

> **Important:** Bucket names are globally unique across all GCP users. If `studyrag-documents` is taken, try `studyrag-docs-abc123`.

---

## Step 4 — Create a Service Account

A service account is like a "robot user" with specific permissions. Your application uses it to authenticate with GCP services without storing your personal credentials.

1. Go to **IAM & Admin → Service Accounts** → **Create Service Account**
2. Name: `studyrag-backend` (the display name and ID can be the same)
3. Click **Create and Continue**
4. Add these roles:
   - **Vertex AI User** — allows calling Gemini models
   - **Storage Object Admin** — allows reading/writing GCS files
   - **Cloud Vision AI Service Agent** — allows calling Vision API
5. Click **Done**

### Download the JSON Key

1. Click on the service account you just created
2. Go to the **Keys** tab
3. **Add Key → Create new key → JSON**
4. A `.json` file downloads — keep it safe, **do not commit it to git**
5. Move it to a permanent location, e.g., `/home/yourname/keys/studyrag-key.json`
6. Note the full path — you'll put it in `.env` as `GOOGLE_APPLICATION_CREDENTIALS`

> **Security note:** Anyone with this JSON file can use your GCP account and incur costs. Treat it like a password. Add the path to `.gitignore`.

---

## Step 5 — Note Your Vertex AI Region

Gemini models are available in specific regions. The project uses `us-central1` by default.

To check available regions:
- [Vertex AI Locations](https://cloud.google.com/vertex-ai/docs/general/locations)

The region goes in `.env` as `GCP_LOCATION`. Keep it the same as your GCS bucket region.

---

## Step 6 — Verify Everything Works

Run this quick test from the command line (after setting up the Python environment in the next guide):

```python
import os
os.environ["GOOGLE_APPLICATION_CREDENTIALS"] = "/path/to/your-key.json"

from google import genai
client = genai.Client(
    vertexai=True,
    project="your-project-id",
    location="us-central1"
)

response = client.models.generate_content(
    model="gemini-2.5-flash",
    contents="Say hello in one sentence."
)
print(response.text)
```

If it prints a greeting, your GCP setup is working.

---

## Summary of Values You Need

After completing this guide, you should have:

| Variable | Example Value | Where to Get It |
|----------|--------------|-----------------|
| `GCP_PROJECT_ID` | `studyrag-dev-123456` | GCP console top bar |
| `GCP_LOCATION` | `us-central1` | Your chosen region |
| `GCS_BUCKET_NAME` | `studyrag-documents-abc` | Bucket you created |
| `GOOGLE_APPLICATION_CREDENTIALS` | `/home/user/keys/key.json` | Path to downloaded JSON |

These all go into the `.env` file (covered in [05 — Backend Setup](./05-backend-setup.md)).

---

## Troubleshooting

**"API not enabled" error:**
Go to APIs & Services → Library and confirm the API shows as "Enabled".

**"Permission denied" on GCS:**
Make sure the service account has "Storage Object Admin" role, not just "Storage Viewer".

**"Model not found" error:**
Check that `GCP_LOCATION` matches a region where Gemini models are available. `us-central1` works for all models used.
