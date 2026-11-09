# UTH Thesis Finder

A local web app for students of the Department of Electrical and Computer Engineering, University of Thessaly. It fetches the diploma thesis topics from [applications.e-ce.uth.gr](https://applications.e-ce.uth.gr), connecting the university VPN by itself when needed. You can then search and filter the topics, and ask an AI assistant that knows every available topic and your interests.

Unofficial project, not affiliated with the University of Thessaly.

## Features

* **One click refetch.** Logs in with your UTH account and fetches the topics. If the site is not reachable, it first connects the UTH OpenVPN through NetworkManager, then disconnects when done. Shows what changed since the last fetch (new, removed, now available, changed).
* **Split tunnel VPN.** Only the applications site goes through the VPN. Your default route and DNS stay untouched.
* **Search and filters.** Accent insensitive search over titles, descriptions and supervisors, plus supervisor and availability filters.
* **AI assistant** (toggle with the Assistant button):
  * Sees every available topic and your profile, and recommends topics that fit you.
  * "Ask AI" on a card sends that topic's full description with your question.
  * Answers render as Markdown. Cited topics like `[123]` are clickable and scroll to the card.
  * With Ollama Cloud it can search the web and read pages. Each tool call shows live in the chat and can be expanded.
  * Chat history is saved locally, so you can go back to old chats.
* **Profile.** A short bio, professors you like or dislike, and study directions you like or dislike. The assistant uses it for recommendations.

## Requirements

* Linux with NetworkManager and its OpenVPN plugin (`networkmanager-openvpn` on Arch, `network-manager-openvpn` on Debian and Ubuntu)
* Python 3.10 or newer. Standard library only, nothing to install with pip.
* A UTH account
* An API key for the assistant: [Ollama Cloud](https://ollama.com) (has a free tier), OpenAI or Gemini

## Setup

```sh
git clone https://github.com/MANRAF04/uth_applications.git
cd uth_applications
cp .env.example .env
chmod 600 .env
```

Then fill in `.env`:

| Variable | Meaning |
| --- | --- |
| `UTH_USER`, `UTH_PASS` | Your UTH account. The same credentials log in to the site and the VPN. |
| `LLM_PROVIDER` | `ollama` (default), `openai` or `gemini` |
| `LLM_API_KEY` | API key for that provider |
| `LLM_MODEL` | Model name, for example `gpt-oss:120b` on Ollama |

## Run

```sh
python3 app.py
```

This opens http://127.0.0.1:8765. On the first run, press **Refetch** to load the topics. After editing `.env`, restart the app.

To fetch from the terminal only (prints the changes since the last run):

```sh
python3 fetch_theses.py
```

## How the VPN works

On the first fetch, the app imports `uth.ovpn` into NetworkManager as a connection named `uth`. Before each connect it sets:

* only a route to the applications site (no default route, no DNS changes)
* `password-flags=2`, so NetworkManager never stores your password

The password is read from `.env` and handed to `nmcli` through a temporary file only you can read, never on the command line. If the site is already reachable (on campus, or with the VPN already up), the app skips the VPN.

To remove the connection: `nmcli connection delete uth`

## Your data

| File | Contents | Committed |
| --- | --- | --- |
| `.env` | Credentials and API key | no |
| `theses.json` | The last fetched topics | no |
| `app.db` | Chats and profile (SQLite) | no |

## Security notes

* The server listens on 127.0.0.1 only. It rejects requests with a foreign `Host` header (DNS rebinding) and writes without the `X-UTH` header (cross site requests).
* Answers are rendered by a small built in Markdown renderer that creates page elements directly, never raw HTML. Only `http`, `https` and `mailto` links are kept.
* Thesis texts and web pages reach the model as data. The model's only tools are web search and page reading, so it cannot change anything.

## Tests

```sh
python3 test_fetch_theses.py
python3 test_app.py
```

## Project layout

| File | Role |
| --- | --- |
| `app.py` | Local web server, chat endpoint and the LLM tool loop |
| `fetch_theses.py` | Login, VPN, scraping and change detection |
| `store.py` | SQLite storage for chats and the profile |
| `viewer.html` | The whole web page (no build step, no external scripts) |
| `uth.ovpn` | UTH OpenVPN client config (public CA certificate only, no secrets) |

## Known limits

* Web search works only with Ollama, since each provider has its own search API.
* Answers arrive in one piece; only the tool steps are streamed.
* Pressing Ctrl+C during a refetch can leave the VPN up. It only routes the applications site; close it with `nmcli connection down uth`.
