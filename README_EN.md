# 🐢 Turtle Soup AI Workshop

[中文](./README.md) | **English**

A self-hosted **AI generator for "Turtle Soup" (lateral thinking puzzles / situation puzzles)**. It turns a battle-tested puzzle-writing methodology into a program: **craft the truth (soup base) first → derive the surface story → automatic AI quality review (auto-revise on failure) → optional spoiler-free illustration**.

## ✨ Features

- **One-click puzzle generation**: pick theme / honkaku-vs-hengaku (realistic vs supernatural) / clear-red-black taste / difficulty / batch count (1–5) / purpose (party hosting or social-media copy), and get a complete hosting pack: surface story, truth, key clues, 3-level progressive hints, a 8–12 entry Q&A cheat sheet, and hosting tips
- **Automatic quality review**: every puzzle is judged against 6 criteria (detail mapping, multi-solution elimination, spoiler check, genre compliance, difficulty match, hosting consistency); hard failures trigger automatic revision (up to 2 rounds)
- **Optional illustrations**: supports Volcano Engine Doubao Seedream (best Chinese text rendering), SiliconFlow Kolors (free), and Pollinations (no registration). Images are derived **only from the surface story — never spoilers**
- **AI host mode**: let the AI host a session — it only answers "Yes / No / Irrelevant", gives progressive hints on demand, and reveals the truth when you crack the case
- **Live streaming chain-of-thought**: watch the AI's reasoning and output in real time while a puzzle is generated; peek into the AI host's mind while playing. Both are collapsed by default **and** blurred (double spoiler protection) until you explicitly reveal them
- **History library**: everything is stored locally; view / export Markdown / reuse for a new game anytime
- **Broad compatibility**: DeepSeek, SiliconFlow, Kimi, Zhipu, Alibaba Qwen, OpenRouter, local Ollama, plus any OpenAI-compatible endpoint — just paste an API key

---

# 1. Quickest start: run it locally (no purchases needed)

1. Install [Python 3.10+](https://www.python.org/downloads/) (check **"Add Python to PATH"** during setup; skip if already installed)
2. Double-click **`run.bat`** on Windows. First run installs dependencies automatically
3. Open `http://127.0.0.1:8000` in your browser

> Mac / Linux:
> ```bash
> python3 -m venv .venv && source .venv/bin/activate
> pip install -r requirements.txt
> python -m uvicorn app.main:app --host 127.0.0.1 --port 8000
> ```

# 2. API keys (required for real generation)

On the **Settings** page, pick a provider and paste its key. Use the **"🔄 Fetch model list"** button to pull all available models from the platform and click one to select it — no more mistyped model names.

| Provider | Sign-up | Notes |
|---|---|---|
| **DeepSeek** (recommended) | https://platform.deepseek.com | Free credits on sign-up, `deepseek-chat` is cheap and good |
| **SiliconFlow** (recommended) | https://cloud.siliconflow.cn | Hundreds of models (DeepSeek/Qwen/GLM…) behind one key, plus free image generation |
| Kimi / Zhipu / Qwen / OpenRouter | their own sites | Presets included |
| Ollama (local models) | http://127.0.0.1:11434 | Completely free, no key needed |

### Image-generation keys (optional)

- **Pollinations**: no account, no key, zero cost
- **SiliconFlow Kolors**: free credits on sign-up; shares the same key as chat if you use SiliconFlow
- **Doubao / Volcano Engine** (best Chinese text rendering):
  1. Open https://console.volcengine.com/ark (Volcano Ark console)
  2. Verify your identity, then "API Key Management" → create a key
  3. Enable the `Doubao-Seedream` models in "Service Management" (trial quota for new models)
  4. In Settings pick "Doubao / Volcano Engine", paste the key, keep the default model `doubao-seedream-4-0-250828`

# 3. Deploy to a cloud server (access from any device)

## 3.1 Buy a server (~$10–15/year)

1. Any lightweight server from Tencent Cloud / Alibaba Cloud, 2 vCPU + 2 GB is plenty
2. Image: **Ubuntu 24.04** (or 22.04)
3. In the console's **firewall / security group**, allow inbound **TCP port 8000**

## 3.2 Deploy (copy-paste only)

**Step 1**: Log in via the provider's web terminal.

**Step 2**: Install Docker (one time):

```bash
curl -fsSL https://get.docker.com | bash
```

**Step 3**: Get the code onto the server:

- **Option A (recommended, GUI)**: install the BT Panel
  ```bash
  wget -O install.sh https://download.bt.cn/install/install_lts.sh && bash install.sh ed8484bec
  ```
  Log into the panel → "Files" → upload the project **zip** → extract.
- **Option B (Git)**: push to a private GitHub/Gitee repo and `git clone` on the server.

**Step 4**: Start it:

```bash
cd /root/turtle-soup-server      # your actual extracted directory
bash deploy.sh
```

Visit `http://YOUR_SERVER_IP:8000`.

**Step 5 (important!)**: Open the site → **Settings** → set an **access password**, so strangers can't burn your API quota.

## 3.3 Maintenance

| Task | Command / Method |
|---|---|
| Redeploy after updates | run `bash deploy.sh` again |
| Logs | `docker logs -f turtle-soup` |
| Restart | `docker restart turtle-soup` |
| Backup everything | copy the `data/` folder (history, config, images, database) |
| Forgot your password | edit `data/config.json` on the server, set `access_password` to `""`, restart |

# 4. FAQ

| Problem | Fix |
|---|---|
| "API key invalid (401)" | Key copied incompletely, or the key doesn't belong to the selected provider |
| "Rate limited (429)" | Retry in a few seconds; if it persists, your quota is exhausted |
| "Model output could not be parsed" | Switch to a different chat model, or lower the creativity temperature |
| Site unreachable | Check the firewall rule for port 8000; `docker ps` to see if the container runs |
| Image generation fails | Use "Test image connection" for the Chinese error message; free providers occasionally time out — retry |
| Doubao returns 404 | Enable the exact model in Volcano Ark's "Service Management"; model name must match |

# 5. Generation quality

The pipeline follows a proven puzzle-writing methodology:

1. **Truth first**: write the complete story before the surface, so every surface detail is grounded
2. **New-information method**: almost everything is on the surface; exactly one key new piece of information is hidden in the truth, and players dig it out with yes/no questions
3. **Zero-lies rule**: every word of the surface is a true subset of the truth; misdirection comes only from omission and habitual thinking patterns
4. **Six-point review**: detail mapping / multi-solution elimination / spoiler check / genre & taste compliance / difficulty match / hosting consistency, with automatic revision on hard failures

Even so, we recommend playing a round with the built-in **AI host mode** yourself before hosting, to confirm there is no multi-solution leak.

# 6. Project structure

```
turtle-soup-server/
├── app/
│   ├── main.py        # FastAPI entry + access password
│   ├── pipeline.py    # generation pipeline (truth → surface → review-revise loop)
│   ├── prompts.py     # methodology → system prompts
│   ├── llm.py         # OpenAI-compatible client (works with every provider)
│   ├── imagegen.py    # image provider abstraction (Doubao/SiliconFlow/Pollinations/custom)
│   ├── host.py        # AI host
│   ├── config.py      # provider presets & configuration
│   ├── db.py          # SQLite history
│   └── web/           # web UI
├── data/              # runtime data (config.json / app.db / output images) — back up this folder
├── run.bat            # one-click local start on Windows
├── deploy.sh          # one-click server deploy/update
├── Dockerfile / docker-compose.yml
└── README.md
```
