# PyPDF External Document Extraction Service

An OpenWebUI-compatible **External Content Extraction Engine** that runs
LangChain's `PyPDFLoader` in **`single` mode** as a standalone microservice.
Designed to be deployed on **OpenShift** (or any OCI-compliant Kubernetes cluster).

---

## How it works

```
OpenWebUI                         pypdf-extractor
   │                                    │
   │  PUT /process                      │
   │  (multipart: file=<bytes>)  ──────▶│
   │                                    │  PyPDFLoader(mode="single")
   │                                    │  ── reads temp file
   │  {"documents": [...]}       ◀──────│
```

OpenWebUI's **External** engine setting sends a `PUT /process` multipart
request; this service extracts text and returns a JSON document list that
OpenWebUI feeds into its chunking/embedding pipeline.

---

## File layout

```
pypdf-extractor/
├── app.py                 # FastAPI service
├── requirements.txt       # Python dependencies
├── Dockerfile             # OpenShift-compatible image
└── openshift/
    ├── deployment.yaml    # Deployment
    ├── service.yaml       # ClusterIP Service (port 80 → 8080)
    └── route.yaml         # (Optional) TLS Route for external access
```

---

## Build & push the image

```bash
# Build
podman build -t your-registry.example.com/pypdf-extractor:1.0.0 .

# Push
podman push your-registry.example.com/pypdf-extractor:1.0.0
```

Update the `image:` field in `openshift/deployment.yaml` to match.

---

## Deploy to OpenShift

```bash
# Target the right namespace
oc project <your-namespace>

# Apply all manifests
oc apply -f openshift/deployment.yaml
oc apply -f openshift/service.yaml
oc apply -f openshift/route.yaml   # optional – only if you need external access

# Watch rollout
oc rollout status deployment/pypdf-extractor
```

### (Optional) API-key secret

If you want to secure the endpoint with a bearer token:

```bash
oc create secret generic pypdf-extractor-secret \
  --from-literal=api-key=<your-secret-token>
```

Then uncomment the `API_KEY` env-var block in `deployment.yaml`.

---

## Configure OpenWebUI

In **Admin → Settings → Documents**:

| Field | Value |
|---|---|
| Content Extraction Engine | `External` |
| Extraction Engine URL | `http://pypdf-extractor.<namespace>.svc.cluster.local` |
| Extraction Engine API Key | *(leave blank, or set if you enabled API_KEY)* |

> If OpenWebUI runs **outside** the cluster, use the Route hostname instead:
> `https://pypdf-extractor.<apps.cluster.example.com>`

---

## Environment variables

| Variable | Default | Description |
|---|---|---|
| `PYPDF_MODE` | `single` | `single` = whole PDF as one document; `page` = one document per page |
| `PAGES_DELIMITER` | `\n` | String inserted between pages in `single` mode |
| `EXTRACT_IMAGES` | `false` | Enable image OCR (`true` requires `rapidocr-onnxruntime`) |
| `API_KEY` | *(empty)* | Bearer token for auth; leave empty to disable auth |
| `PORT` | `8080` | Listening port |
| `HOST` | `0.0.0.0` | Bind address |
| `WORKERS` | `2` | Uvicorn worker count |

---

## API reference

### `GET /health`
Liveness/readiness probe. Returns `{"status": "ok"}`.

### `PUT /process`
**Request** — `multipart/form-data`

| Field | Type | Description |
|---|---|---|
| `file` | binary | The document to extract (PDF recommended; other formats passed through) |

**Headers** (set automatically by OpenWebUI when `ENABLE_FORWARD_USER_INFO_HEADERS=true`):
`X-User-Id`, `X-User-Email`, `X-User-Name`, `X-User-Role`

**Response** — `200 OK`
```json
{
  "documents": [
    {
      "page_content": "full extracted text of the document ...",
      "metadata": {
        "source": "myfile.pdf",
        "total_pages": 10,
        "producer": "...",
        "creator": "...",
        "creationdate": "..."
      }
    }
  ]
}
```

In `single` mode there is always exactly **one** document object.
In `page` mode there is one object per page (with `page` and `page_label` keys in metadata).

---

## Local testing

```bash
# Install deps
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt

# Run
uvicorn app:app --reload --port 8080

# Test with curl
curl -X PUT http://localhost:8080/process \
     -F "file=@/path/to/sample.pdf" | python -m json.tool
```


Build

```
docker buildx build --platform linux/amd64 -t  hatchet8513/pypdf-extractor:1.0.1 --push .
```