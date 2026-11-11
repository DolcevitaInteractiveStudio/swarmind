# Third-party licenses

SwarMind is licensed under the GNU Affero General Public License v3.0 (see `LICENSE` and `NOTICE`).
It includes, downloads or runs the third-party components below, each under its own license.
All of them are compatible with distributing SwarMind under AGPL-3.0; the notes at the end list the
points worth knowing.

## 1. Assets bundled in the frontend build

| Component | Version | License | Notes |
|---|---|---|---|
| IBM Plex Sans (variable), via `@fontsource-variable/ibm-plex-sans` | 5.3.0 | SIL Open Font License 1.1 | Font files are copied into the built SPA. Copyright 2019 IBM Corp. Full text: [`licenses/OFL-1.1-IBM-Plex-Sans.txt`](licenses/OFL-1.1-IBM-Plex-Sans.txt) |
| d3 and its modules | 7.9.0 | ISC (d3-ease: BSD-3-Clause; robust-predicates: Unlicense) | Knowledge-graph view |
| DOMPurify | 3.4.11 | MPL-2.0 OR Apache-2.0 (used under Apache-2.0) | Sanitises the report HTML |
| Vue, Vue Router, Pinia, vue-i18n, VueUse, axios, socket.io-client | see table 4 | MIT | |

The SwarMind logo mark (`frontend/public/favicon.svg`) and the screenshot fixtures in
`frontend/scripts/ui-check/fixtures/` are original works of the SwarMind authors, under AGPL-3.0.

## 2. Models downloaded at run time

Not stored in this repository: downloaded on first use into Docker volumes.

| Model | Source | License | Used for |
|---|---|---|---|
| `intfloat/multilingual-e5-small`, int8 ONNX, revision `614241f` | Hugging Face | MIT | Knowledge-base embedding (`backend/app/memory/kb_embedding.py`); volume `hf_cache`. Disabled with `KB_EMBEDDING=default` |
| `all-MiniLM-L6-v2` (ONNX), Chroma's default embedding function | downloaded by the Chroma client | Apache-2.0 | Agent memories, echo-chamber metric, KB fallback; volume `chroma_onnx_cache` |

Text generation uses external LLM APIs chosen by each user (OpenRouter, Groq, OpenAI, Anthropic):
no model weights are distributed. Their terms of service apply to what you send them.

## 3. Container images used by `docker-compose.yml`

Pulled from their registries, not redistributed with SwarMind.

| Image | License |
|---|---|
| `postgres:16-alpine` | PostgreSQL License |
| `redis:7-alpine` | Redis 7.4 and later: RSALv2 / SSPLv1 dual license (source-available, not OSI). Redis up to 7.2: BSD-3-Clause. See note (a) |
| `chromadb/chroma:1.0.21` | Apache-2.0 |
| `nginx:alpine` (frontend) | BSD-2-Clause |
| `python:3.11-slim` (backend, worker, Flower) | PSF-2.0, plus the Debian packages it contains |
| `node:20-alpine` (frontend build stage only) | MIT, plus the Alpine packages it contains |

## 4. npm packages in the frontend build (production dependencies and their dependencies)

| Package | Version | License |
|---|---|---|
| @babel/parser | 7.29.7 | MIT |
| @fontsource-variable/ibm-plex-sans | 5.3.0 | OFL-1.1 |
| @intlify/core-base | 11.4.18 | MIT |
| @intlify/devtools-types | 11.4.18 | MIT |
| @intlify/message-compiler | 11.4.18 | MIT |
| @intlify/shared | 11.4.18 | MIT |
| @jridgewell/sourcemap-codec | 1.5.5 | MIT |
| @socket.io/component-emitter | 3.1.2 | MIT |
| @types/trusted-types | 2.0.7 | MIT |
| @types/web-bluetooth | 0.0.20 | MIT |
| @vue/compiler-core | 3.5.38 | MIT |
| @vue/compiler-dom | 3.5.38 | MIT |
| @vue/compiler-sfc | 3.5.38 | MIT |
| @vue/compiler-ssr | 3.5.38 | MIT |
| @vue/devtools-api | 6.6.4 | MIT |
| @vue/reactivity | 3.5.38 | MIT |
| @vue/runtime-core | 3.5.38 | MIT |
| @vue/runtime-dom | 3.5.38 | MIT |
| @vue/server-renderer | 3.5.38 | MIT |
| @vue/shared | 3.5.38 | MIT |
| @vueuse/core | 10.11.1 | MIT |
| @vueuse/metadata | 10.11.1 | MIT |
| @vueuse/shared | 10.11.1 | MIT |
| agent-base | 6.0.2 | MIT |
| asynckit | 0.4.0 | MIT |
| axios | 1.18.0 | MIT |
| call-bind-apply-helpers | 1.0.2 | MIT |
| combined-stream | 1.0.8 | MIT |
| commander | 7.2.0 | MIT |
| csstype | 3.2.3 | MIT |
| d3 | 7.9.0 | ISC |
| d3-array | 3.2.4 | ISC |
| d3-axis | 3.0.0 | ISC |
| d3-brush | 3.0.0 | ISC |
| d3-chord | 3.0.1 | ISC |
| d3-color | 3.1.0 | ISC |
| d3-contour | 4.0.2 | ISC |
| d3-delaunay | 6.0.4 | ISC |
| d3-dispatch | 3.0.1 | ISC |
| d3-drag | 3.0.0 | ISC |
| d3-dsv | 3.0.1 | ISC |
| d3-ease | 3.0.1 | BSD-3-Clause |
| d3-fetch | 3.0.1 | ISC |
| d3-force | 3.0.0 | ISC |
| d3-format | 3.1.2 | ISC |
| d3-geo | 3.1.1 | ISC |
| d3-hierarchy | 3.1.2 | ISC |
| d3-interpolate | 3.0.1 | ISC |
| d3-path | 3.1.0 | ISC |
| d3-polygon | 3.0.1 | ISC |
| d3-quadtree | 3.0.1 | ISC |
| d3-random | 3.0.1 | ISC |
| d3-scale | 4.0.2 | ISC |
| d3-scale-chromatic | 3.1.0 | ISC |
| d3-selection | 3.0.0 | ISC |
| d3-shape | 3.2.0 | ISC |
| d3-time | 3.1.0 | ISC |
| d3-time-format | 4.1.0 | ISC |
| d3-timer | 3.0.1 | ISC |
| d3-transition | 3.0.1 | ISC |
| d3-zoom | 3.0.0 | ISC |
| debug | 4.4.3 | MIT |
| delaunator | 5.1.0 | ISC |
| delayed-stream | 1.0.0 | MIT |
| dompurify | 3.4.11 | (MPL-2.0 OR Apache-2.0) |
| dunder-proto | 1.0.1 | MIT |
| engine.io-client | 6.6.6 | MIT |
| engine.io-parser | 5.2.3 | MIT |
| entities | 7.0.1 | BSD-2-Clause |
| es-define-property | 1.0.1 | MIT |
| es-errors | 1.3.0 | MIT |
| es-object-atoms | 1.1.2 | MIT |
| es-set-tostringtag | 2.1.0 | MIT |
| estree-walker | 2.0.2 | MIT |
| follow-redirects | 1.16.0 | MIT |
| form-data | 4.0.6 | MIT |
| function-bind | 1.1.2 | MIT |
| get-intrinsic | 1.3.0 | MIT |
| get-proto | 1.0.1 | MIT |
| gopd | 1.2.0 | MIT |
| has-symbols | 1.1.0 | MIT |
| has-tostringtag | 1.0.2 | MIT |
| hasown | 2.0.4 | MIT |
| https-proxy-agent | 5.0.1 | MIT |
| iconv-lite | 0.6.3 | MIT |
| internmap | 2.0.3 | ISC |
| magic-string | 0.30.21 | MIT |
| math-intrinsics | 1.1.0 | MIT |
| mime-db | 1.52.0 | MIT |
| mime-types | 2.1.35 | MIT |
| nanoid | 3.3.15 | MIT |
| picocolors | 1.1.1 | ISC |
| pinia | 2.3.1 | MIT |
| postcss | 8.5.15 | MIT |
| proxy-from-env | 2.1.0 | MIT |
| robust-predicates | 3.0.3 | Unlicense |
| rw | 1.3.3 | BSD-3-Clause |
| safer-buffer | 2.1.2 | MIT |
| socket.io-client | 4.8.3 | MIT |
| socket.io-parser | 4.2.6 | MIT |
| source-map-js | 1.2.1 | BSD-3-Clause |
| typescript | 6.0.3 | Apache-2.0 |
| vue | 3.5.38 | MIT |
| vue-demi | 0.14.10 | MIT |
| vue-i18n | 11.4.18 | MIT |
| vue-router | 4.6.4 | MIT |
| ws | 8.21.0 | MIT |
| xmlhttprequest-ssl | 2.1.2 | MIT |

## 5. Python packages in the backend image (direct and transitive)

| Package | Version | License |
|---|---|---|
| alembic | 1.13.2 | MIT License |
| amqp | 5.3.1 | BSD License |
| annotated-doc | 0.0.4 | MIT |
| annotated-types | 0.7.0 | MIT License |
| anthropic | 0.28.0 | MIT |
| anyio | 4.13.0 | MIT |
| attrs | 26.1.0 | MIT |
| backoff | 2.2.1 | MIT License |
| bcrypt | 5.0.0 | Apache Software License |
| bidict | 0.23.1 | Mozilla Public License 2.0 (MPL 2.0) |
| billiard | 4.2.4 | BSD License |
| blinker | 1.9.0 | MIT License |
| build | 1.4.3 | MIT |
| celery | 5.4.0 | BSD License |
| certifi | 2026.2.25 | Mozilla Public License 2.0 (MPL 2.0) |
| cffi | 2.0.0 | MIT |
| charset-normalizer | 3.4.7 | MIT |
| chromadb | 1.0.21 | Apache Software License |
| click | 8.3.2 | BSD-3-Clause |
| click-didyoumean | 0.3.1 | MIT License |
| click-plugins | 1.1.1.2 | BSD License |
| click-repl | 0.3.0 | MIT |
| cryptography | 42.0.8 | Apache Software License; BSD License |
| distro | 1.9.0 | Apache Software License |
| durationpy | 0.10 | MIT |
| filelock | 3.29.0 | MIT |
| Flask | 3.0.3 | BSD License |
| Flask-Cors | 4.0.1 | MIT License |
| Flask-Migrate | 4.0.7 | MIT License |
| Flask-SocketIO | 5.3.6 | MIT License |
| Flask-SQLAlchemy | 3.1.1 | BSD License |
| flatbuffers | 25.12.19 | Apache Software License |
| flower | 2.0.1 | BSD License |
| fsspec | 2026.3.0 | BSD-3-Clause |
| gevent | 24.2.1 | MIT License |
| gevent-websocket | 0.10.1 | Apache-2.0 |
| googleapis-common-protos | 1.74.0 | Apache Software License |
| greenlet | 3.4.0 | MIT AND PSF-2.0 |
| groq | 0.9.0 | Apache-2.0 |
| grpcio | 1.80.0 | Apache-2.0 |
| gunicorn | 22.0.0 | MIT License |
| h11 | 0.16.0 | MIT License |
| hf-xet | 1.4.3 | Apache-2.0 |
| httpcore | 1.0.9 | BSD-3-Clause |
| httptools | 0.7.1 | MIT |
| httpx | 0.27.0 | BSD-3-Clause |
| huggingface_hub | 0.36.2 | Apache Software License |
| humanize | 4.15.0 | MIT |
| idna | 3.11 | BSD-3-Clause |
| importlib_metadata | 8.7.1 | Apache-2.0 |
| importlib_resources | 7.1.0 | Apache-2.0 |
| itsdangerous | 2.2.0 | BSD License |
| Jinja2 | 3.1.6 | BSD License |
| jiter | 0.14.0 | MIT |
| jsonschema | 4.26.0 | MIT |
| jsonschema-specifications | 2025.9.1 | MIT |
| kombu | 5.6.2 | BSD-3-Clause |
| kubernetes | 35.0.0 | Apache Software License |
| lxml | 6.1.0 | BSD-3-Clause |
| Mako | 1.3.11 | MIT License |
| Markdown | 3.6 | BSD License |
| markdown-it-py | 4.0.0 | MIT License |
| MarkupSafe | 3.0.3 | BSD-3-Clause |
| mdurl | 0.1.2 | MIT License |
| mmh3 | 5.2.1 | MIT License |
| mpmath | 1.3.0 | BSD License |
| networkx | 3.3 | BSD License |
| numpy | 1.26.4 | BSD License |
| oauthlib | 3.3.1 | BSD-3-Clause |
| onnxruntime | 1.24.4 | MIT License |
| openai | 1.35.0 | Apache-2.0 |
| opentelemetry-api | 1.41.0 | Apache-2.0 |
| opentelemetry-exporter-otlp-proto-common | 1.41.0 | Apache-2.0 |
| opentelemetry-exporter-otlp-proto-grpc | 1.41.0 | Apache-2.0 |
| opentelemetry-proto | 1.41.0 | Apache-2.0 |
| opentelemetry-sdk | 1.41.0 | Apache-2.0 |
| opentelemetry-semantic-conventions | 0.62b0 | Apache-2.0 |
| orjson | 3.11.8 | MPL-2.0 AND (Apache-2.0 OR MIT) |
| overrides | 7.7.0 | Apache License, Version 2.0 |
| packaging | 26.1 | Apache-2.0 OR BSD-2-Clause |
| pillow | 12.2.0 | MIT-CMU |
| posthog | 5.4.0 | MIT License |
| prometheus_client | 0.25.0 | Apache-2.0 AND BSD-2-Clause |
| prompt_toolkit | 3.0.52 | BSD License |
| protobuf | 6.33.6 | 3-Clause BSD License |
| psycopg2-binary | 2.9.9 | GNU Library or Lesser General Public License (LGPL) |
| pybase64 | 1.4.3 | BSD License |
| pycparser | 3.0 | BSD-3-Clause |
| pydantic | 2.7.4 | MIT |
| pydantic_core | 2.18.4 | MIT License |
| Pygments | 2.20.0 | BSD-2-Clause |
| PyJWT | 2.8.0 | MIT License |
| PyPDF2 | 3.0.1 | BSD License |
| PyPika | 0.51.1 | Apache Software License |
| pyproject_hooks | 1.2.0 | MIT License |
| python-dateutil | 2.9.0.post0 | Apache Software License; BSD License |
| python-docx | 1.1.2 | MIT License |
| python-dotenv | 1.0.1 | BSD License |
| python-engineio | 4.13.1 | MIT |
| python-socketio | 5.16.1 | MIT |
| pytz | 2026.1.post1 | MIT License |
| PyYAML | 6.0.3 | MIT License |
| redis | 5.0.8 | MIT License |
| referencing | 0.37.0 | MIT |
| reportlab | 4.4.10 | BSD License |
| requests | 2.33.1 | Apache Software License |
| requests-oauthlib | 2.0.0 | BSD License |
| rich | 15.0.0 | MIT License |
| rpds-py | 0.30.0 | MIT |
| shellingham | 1.5.4 | ISC License (ISCL) |
| shortuuid | 1.0.13 | BSD License |
| simple-websocket | 1.1.0 | MIT License |
| six | 1.17.0 | MIT License |
| sniffio | 1.3.1 | Apache Software License; MIT License |
| SQLAlchemy | 2.0.31 | MIT License |
| stripe | 10.1.0 | MIT License |
| structlog | 24.2.0 | MIT OR Apache-2.0 |
| sympy | 1.14.0 | BSD License |
| tenacity | 8.3.0 | Apache Software License |
| tokenizers | 0.22.2 | Apache Software License |
| tornado | 6.5.5 | Apache Software License |
| tqdm | 4.67.3 | MPL-2.0 AND MIT |
| typer | 0.24.1 | MIT |
| typing_extensions | 4.15.0 | PSF-2.0 |
| tzdata | 2026.1 | Apache-2.0 |
| urllib3 | 2.6.3 | MIT |
| uvicorn | 0.44.0 | BSD-3-Clause |
| uvloop | 0.22.1 | Apache Software License; MIT License |
| vine | 5.1.0 | BSD License |
| watchfiles | 1.1.1 | MIT License |
| websocket-client | 1.9.0 | Apache Software License |
| websockets | 16.0 | BSD-3-Clause |
| Werkzeug | 3.0.3 | BSD License |
| wsproto | 1.3.2 | MIT |
| zipp | 3.23.1 | MIT |
| zope.event | 6.1 | ZPL-2.1 |
| zope.interface | 8.3 | ZPL-2.1 |

## Notes on compatibility with AGPL-3.0

a. **Redis** runs as a separate service and is not part of SwarMind; the AGPL does not extend to it,
   and SwarMind only talks to it over the network. `redis:7-alpine` currently resolves to Redis 7.4,
   which is source-available (RSALv2/SSPLv1). If you need an OSI-licensed stack, use Redis 8
   (which adds AGPLv3 as a license option) or Valkey, after checking data-file compatibility.
b. **psycopg2-binary** is LGPL-3.0 (with linking exceptions); LGPL-3.0 is compatible with AGPL-3.0.
   The binary wheel bundles libpq (PostgreSQL License) and OpenSSL (Apache-2.0).
c. **MPL-2.0** packages (certifi, bidict, parts of orjson and tqdm; DOMPurify optionally) are
   file-level copyleft and compatible with the (A)GPL through MPL-2.0 section 3.3.
d. **Apache-2.0** components are compatible with GPLv3/AGPLv3 (one way: AGPL code may include them).
e. **ZPL-2.1** (zope.event, zope.interface), **PSF-2.0** (typing_extensions), **MIT-CMU/HPND**
   (Pillow), ISC, BSD and MIT are permissive and GPL-compatible.
f. `stripe` is installed but not used by the code (no payment integration).

No dependency is under a license incompatible with AGPL-3.0 (no GPL-2.0-only, no proprietary or
"non-commercial" terms).

## How these tables were produced

- Python: `pip-licenses --format=csv --with-urls` inside the backend image
  (`pip install -r requirements.txt -c constraints.txt`).
- npm: the production dependency tree of `frontend/package.json` (`npm ls --omit=dev --all`),
  reading each package's `license` field.
