# Portcullis

The control layer for your AI agents. Portcullis sits between an agent, its model and its tools, and runs every prompt, tool call and tool result through a pipeline of guards: role policies, model and budget limits, PII and secret redaction, an injection heuristic, an LLM injection classifier, attack signatures and lockouts. Every request lands in a trace that admins can read.

Live at [controllayer.net](https://controllayer.net).

## The demo

The demo runs at Golden Socks, a made-up investment bank, with a full bank behind it: clients, accounts, trades, payments and research, served to the agent as an MCP server.

- **Challenge** (`/challenge`): you have stolen a bank employee's account. Pick it, run the attack scenarios one by one, and watch which ones Portcullis stops. Turn the protection off to see what the same attacks get without it.
- **Admin** (`/admin`): the dashboard of every request and verdict, the MCP servers, the policy of each role, and the directory synced from the identity provider.

"Watch a live attack" and "Look inside" on the sign-in page give each visitor a sandbox of their own: a copy of the bank that no one else sees.

On the bundled attack corpus, 1,057 cases including encoded, translated and reworded variants, the guards block 98.9% of the attacks with 0.7% false alarms.

## Run it

You need Docker. An OpenAI key is optional: without it, the model calls and the injection classifier are off.

```sh
echo "OPENAI_API_KEY=sk-..." > .env   # optional
./dev up                              # build and start everything
./dev seed                            # load the Golden Socks bank
```

Then open http://localhost:3000. The API is at http://localhost:8000/api, with its docs at `/api/docs`. Sign-in codes go to Mailpit at http://localhost:8025.

The containers run the code from `src/` and reload on every change. Rebuild with `./dev up` only after you change the dependencies.

## Settings

Every setting has a default, so the stack runs without any. Set them in `.env` next to `docker-compose.yml`; `src/backend/app/core/config.py` lists them all.

| Variable                          | What it sets                                                          |
| --------------------------------- | --------------------------------------------------------------------- |
| `OPENAI_API_KEY`                  | The OpenAI models, for the agent and the injection classifier         |
| `OLLAMA_URL`                      | A local Ollama server, such as `http://host.docker.internal:11434/v1` |
| `GOOGLE_CLIENT_ID`                | Sign in with Google                                                   |
| `RESEND_API_KEY`                  | Sends the sign-in codes through Resend, in place of Mailpit           |
| `NGROK_AUTHTOKEN`                 | `./dev ngrok`, to share the app on a public URL                       |
| `APP_PORT`, `API_PORT`, `DB_PORT` | Host ports, `3000`, `8000` and `5432` by default                      |

## Commands

| Command                          | What it does                                                             |
| -------------------------------- | ------------------------------------------------------------------------ |
| `./dev up [service...]`          | Build and start the stack, or only the given services                    |
| `./dev down`                     | Stop the stack; the database data stays                                  |
| `./dev restart [service...]`     | Rebuild and restart the stack, or only the given services                |
| `./dev logs [service...]`        | Follow the logs                                                          |
| `./dev ps`                       | Show the status of every service                                         |
| `./dev destroy [-y]`             | Stop the stack and delete the database data and built images             |
| `./dev shell [service]`          | Open a bash shell in a service, `api` by default                         |
| `./dev python`                   | Open a Python shell in the backend; `await` works at the prompt          |
| `./dev ngrok`                    | Share the app on a public HTTPS URL through ngrok                        |
| `./dev ollama [args...]`         | Start the local Ollama service and run `ollama` in it                    |
| `./dev psql`                     | Open psql in the database                                                |
| `./dev migrate [revision]`       | Apply the migrations, up to `head` by default                            |
| `./dev makemigrations <message>` | Create a migration from the model changes                                |
| `./dev checkmigrations`          | Check that the migrations apply and cover every model change             |
| `./dev seed [--url URL] [-y]`    | Load the Golden Socks bank data                                          |
| `./dev lint [hook]`              | Run every pre-commit hook on the host, or only the given one             |
| `./dev test [pytest args...]`    | Run the backend tests; paths are relative to `src/backend`               |
| `./dev attacks [args...]`        | Run the attack corpus through the control layer and report the pass rate |

`./dev lint` needs pre-commit: `uv tool install pre-commit && pre-commit install`.

## Layout

- `src/backend`: the API, in FastAPI with Postgres. The guards are in `app/control`, the bank MCP server in `app/servers/bank.py`, the demo data and policies in `scripts`.
- `src/frontend`: the app, in React with Vite, Tailwind and shadcn/ui.
- `AGENTS.md`: how to work in the repo, for people and coding agents alike.
