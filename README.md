# LotsLarp Discord Bot

A powerful Discord bot designed for LARP (Live Action Role Playing) communities, providing roleplay message tracking, AI-powered summaries, and game-cycle reporting.

## Features & Commands

### 🌍 Public Commands
*   **/lotslarp help**: Displays a list of available commands.
*   **/lotslarp hello**: Greets the user.
*   **/throw <object>**: Randomly throws an item or plays rock-paper-scissors.
*   **/huh <question>**: Searches the game's content database for lore or rules info.

### 🛡️ Storyteller (Admin) Commands
*   **/lotslarp summarize <channel_id>**: Generates an AI summary of a specific channel from the last summary mention to the present.
*   **/lotslarp report month**: Generates a summary from the **last scheduled game** until now. This uses your LARP's specific game schedule (e.g., "1st Saturday").
*   **/lotslarp report digest [day|week|month|now]**: Generates a PDF digest of messages. Defaults to "month". Use "now" to force the scheduled digest (unsent messages).
*   **/lotslarp report voice [days]**: Provides statistics on voice channel activity over the specified period.
*   **/lotslarp stale**: Scans for roleplay channels that have significant activity but no recent summary.
*   **/lotslarp status**: Displays health metrics for the bot, database, and AI systems.
*   **/lotslarp instructions**: View detailed guides for Storyteller features.

## Summary & RAG System

The bot features an advanced summarization engine:
*   **Role Mentions**: Any message that mentions the `@summary` (configurable) role is cached for the next digest.
*   **RAG (Retrieval-Augmented Generation)**: The AI automatically cross-references roleplay messages with a "Lore Glossary" in Firestore to ensure summaries are contextually accurate.
*   **Monthly Cycle**: The bot can be configured to automatically trigger reports based on your game schedule, looking back to the previous game and providing context from previous monthly summaries to track long-running plots.

## Configuration

The bot is highly configurable via environment variables (see `.env.example`):
*   `LOTSLARP_GAME_WEEK_ORDINAL`: Sets which week the game happens (e.g., 1st, 2nd).
*   `LOTSLARP_GAME_WEEKDAY`: Sets the day of the week for the game (0=Monday, 6=Sunday).
*   `LOTSLARP_MONTHLY_SUMMARY_CONTEXT_MONTHS`: Number of previous summaries to include as AI context.

## Deployment

This application is designed to run in a Docker container and can be deployed to **Google Cloud Platform** (Cloud Run or GCE).

### Quick Deploy (GCE)
1.  Copy `.env.example` to `.env` and fill in your secrets.
2.  Run `./deploy-gce.sh`.

This will provision a free-tier eligible `e2-micro` instance and set up the bot automatically.
