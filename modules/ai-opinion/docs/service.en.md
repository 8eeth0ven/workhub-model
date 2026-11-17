# Local AI news service

The module runs independently. It builds the saved dashboard on startup; collection and model analysis start only when explicitly requested. It creates no schedule.

Run `python3 bin/server.py --host 127.0.0.1 --port 0` from the module directory and open the loopback port printed in the initial JSON line. Use `--data-dir`, `--site-dir`, and `--config-dir` to select storage and a private Workhub-format model configuration. By default the service reads the same local model configuration as Workhub. Without Workhub, create a mode-0600 `llm.json` with `provider`, `model`, `base_url` and `api_keys` fields as needed; keep credentials out of version control.

The transport reuses Workhub's configuration and API/CLI provider implementation. GLM, OpenAI-compatible, Anthropic, Ollama, and Workhub-compatible JSON CLI wrappers are supported. A wrapper hard-coded to the project-review output schema may not support news analysis. Polling never invokes a model.

An explicit analysis sends at most 80 current snapshot headlines, source names, timestamps, temporary IDs, coverage state and truncation counts to the selected provider; article bodies, URLs and the local database are not sent. Untrusted headlines are data, not instructions; the prompt asks the model to disregard instructions and the service validates output source IDs. This is not a guarantee against prompt injection or a substitute for fact checking. Known keys are redacted from source text; links containing known keys or sensitive query parameters are omitted. Results remain local and are bound to the source run; a later run marks them stale.

The loopback server validates Host and requires matching Origin, `X-Workhub-Request: 1`, JSON content type and an empty object for each collection/analysis POST. GET state is read-only. An optional trusted `--parent-origin` allows Workhub embedding. A held flock prevents duplicate services for a data directory; a leftover lock file alone is not evidence of a running process.
