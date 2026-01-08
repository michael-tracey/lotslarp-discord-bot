# LotsLarp Discord Bot

A powerful, AI-integrated Discord bot designed for **LotsLarp** communities. It handles roleplay tracking, generates AI-powered conversation summaries, manages game schedules, and provides robust administration tools for Storytellers.

## 🚀 Key Features

*   **AI Summarization**: Uses Google Gemini Pro to generate concise executive summaries of roleplay channels.
*   **RAG (Retrieval-Augmented Generation)**: Contextualizes AI summaries using a "Lore Glossary" stored in Firestore.
*   **PDF Digests**: Automatically compiles roleplay logs into formatted PDF reports for staff.
*   **Voice Analytics**: Tracks and reports on voice channel usage statistics.
*   **Game Cycle Reporting**: Automates monthly reporting based on your specific game schedule (e.g., "1st Saturday").
*   **Infrastructure-as-Code**: Fully automated deployment to Google Cloud or AWS.

---

## 🎮 Commands

### 🌍 Public Commands
*   **/lotslarp help**: Displays the list of available commands.
*   **/lotslarp hello**: Greets the user.
*   **/throw <object>**: Randomly throws an item or plays rock-paper-scissors.
*   **/huh <query>**: Queries the "Lore Glossary" database for rules or setting information.

### 🛡️ Storyteller (Admin) Commands
All admin commands are prefixed with `/lotslarp`.

#### Reporting & Summaries
*   **report digest [day|week|month|now]**: Generates a PDF digest of recent messages.
    *   `now`: Forces a digest of all unsent messages immediately.
*   **report month**: Generates a comprehensive summary from the **last scheduled game** until now.
*   **report voice [days]**: Provides statistics on voice channel activity over the specified period.
*   **summarize <channel_id>**: Generates an immediate AI summary for a specific channel.
*   **stale [days]**: Scans for roleplay channels with significant activity that haven't been summarized recently.

#### Channel Management
*   **archive <channel_id>**: Moves a channel to the archive category and syncs permissions.
*   **unarchive <channel_id>**: Restores a channel from the archive.
*   **purge-archives**: Manually triggers the cleanup task for old archived channels.

#### System
*   **status**: Displays detailed health metrics for the bot, database (Firestore), and AI (Gemini).
*   **instructions**: detailed guide on using the Storyteller features.

---

## 🛠️ Configuration

The bot is configured via environment variables. Copy `.env.example` to `.env` to get started.

### Core Credentials
| Variable | Description |
| :--- | :--- |
| `LOTSLARP_DISCORD_BOT_DISCORD_TOKEN` | Your Discord Bot Token. |
| `LOTSLARP_DISCORD_BOT_GEMINI_API_KEY` | Google Gemini API Key for AI features. |
| `GCP_PROJECT_ID` | Google Cloud Project ID (for Firestore/Deployment). |

### Game Schedule
| Variable | Description |
| :--- | :--- |
| `LOTSLARP_GAME_WEEK_ORDINAL` | Which occurrence of the day (e.g., `1` for 1st, `2` for 2nd). |
| `LOTSLARP_GAME_WEEKDAY` | Day of the week (0=Monday ... 6=Sunday). |

### Bot Behavior
| Variable | Description |
| :--- | :--- |
| `LOTSLARP_DISCORD_BOT_SUMMARY_ROLE_NAME` | Role name to track for summaries (e.g., `@summary`). |
| `LOTSLARP_DISCORD_BOT_DIGEST_CHANNEL_ID` | Channel ID where PDF digests are sent. |
| `LOTSLARP_DISCORD_BOT_GEMINI_MODEL` | Gemini model to use (default: `gemini-1.5-pro`). |

---

## ☁️ Deployment

The project supports automated deployment to **Google Cloud Platform (GCE or Cloud Run)** and **AWS**.

### 1. Google Compute Engine (Recommended)
Deploys a VM instance using **OpenTofu (Terraform)** and configures it with **Ansible**. This method is cost-effective (often free-tier eligible).

**Prerequisites:** `gcloud`, `tofu` (or `terraform`), `ansible`.

```bash
# 1. Configure secrets in .env
cp .env.example .env

# 2. Deploy
./deploy-gce.sh
```

*   **Logs**: `./logs-gce.sh`
*   **SSH**: `./ssh-gce.sh`
*   **Teardown**: `./undeploy-gce.sh`

### 2. Google Cloud Run
Deploys as a serverless container. Handles secrets securely via Google Secret Manager.

**Prerequisites:** `gcloud`.

```bash
# 1. Configure secrets
cp .env.example .env

# 2. Deploy
./deploy-cloudrun.sh
```

*   **Teardown**: `./undeploy-cloudrun.sh`

### 3. AWS Fargate
Deploys to ECS Fargate.

**Prerequisites:** `aws-cli`, `docker`, `jq`.

```bash
# 1. Configure AWS-specific secrets
cp .env.aws.example .env.aws

# 2. Deploy
./deploy-aws.sh
```

---

## 🧰 Utility & Maintenance

The project includes several helper scripts in the root directory:

*   **`./status.sh`**: Runs a comprehensive system report. Checks VM health (if on GCE), estimates current cloud costs, and verifies database connectivity.
*   **`python upload_glossary.py`**: Uploads/Updates the Lore Glossary in Firestore from a `glossary.csv` file.
*   **`python list_models.py`**: Lists available Google Gemini models for your API key.