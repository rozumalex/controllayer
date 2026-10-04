# Run Portcullis locally

No API keys needed. Without them:

- **Chat model:** the agent uses a mock model that repeats each prompt back.
- **Injection guard:** the LLM classifier is off. The other guards still run: the injection heuristic, PII and secret redaction, attack signatures and lockouts.
- **Sign-in:** codes go to a local Mailpit inbox, and the demo buttons skip sign-in.

To have the agent call tools as a real model would, run a free local model through Ollama ([step 3](#3-optional-a-real-local-model-still-no-key)).

You need Docker Desktop and git.

## 1. Start it

```sh
git clone https://github.com/rozumalex/controllayer.git
cd controllayer
./dev up      # builds and starts Postgres, the API, the frontend and Mailpit
./dev seed    # loads the Golden Socks demo bank
```

The first build takes a few minutes. `./dev ps` shows whether every service is running.

## 2. Open it

| What                        | URL                             |
| --------------------------- | ------------------------------- |
| App                         | http://localhost:3000           |
| API docs                    | http://localhost:8000/api/docs  |
| Email inbox (sign-in codes) | http://localhost:8025           |

On the sign-in page, click **Watch a live attack** or **Look inside**. Each one opens your own copy of the bank, with no email or password.

- **Challenge** (`/challenge`): pick the stolen employee account, run the attacks one by one, and see which ones Portcullis blocks. Turn protection off to compare.
- **Admin** (`/admin`): every request and verdict, the MCP servers, the policy of each role, and the user directory.

## 3. Optional: a real local model, still no key

With the mock model, the guards still check every prompt, but the agent never calls a tool. So attacks that depend on tool calls don't play out. Every demo role may use `qwen2.5:7b`, a free model that runs on your machine. On a Mac:

```sh
brew install ollama
ollama serve &                 # or open the Ollama app
ollama pull qwen2.5:7b         # about 4.7 GB
echo "OLLAMA_URL=http://host.docker.internal:11434/v1" > .env
./dev restart api
```

`./dev ollama pull qwen2.5:7b` runs Ollama inside Docker instead. That also works, but Docker on a Mac has no GPU, so it's slow.

## 4. Optional: the attack benchmark

```sh
./dev attacks --heuristic
```

This runs the bundled attack corpus through the guards that need no model, and reports how many attacks they block.

## Troubleshooting

- **A port is taken:** set `APP_PORT`, `API_PORT` or `DB_PORT` in `.env`, then run `./dev up` again.
- **Start fresh:** `./dev destroy -y && ./dev up && ./dev seed`.
- **Stop:** `./dev down`.
- **Logs:** `./dev logs api` or `./dev logs app`.
