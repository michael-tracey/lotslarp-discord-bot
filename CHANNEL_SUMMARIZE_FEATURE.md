# Channel Summarize Feature

## Overview
The `/summarize` command allows users to generate AI-powered summaries of Discord channel conversations. The bot reads messages from a specified channel and posts a comprehensive summary to a designated summary output channel.

## Usage

```
/summarize <channel_id>
```

### Parameters
- `channel_id`: The ID of the channel you want to summarize (can be a channel mention or numeric ID)

### Examples
```
/summarize 1234567890123456789
/summarize #general
```

## How It Works

1. **Message Collection**: The bot reads messages from the specified channel, going back until it finds:
   - A message that mentions the summary role (configured in `LOTSLARP_DISCORD_BOT_SUMMARY_ROLE_NAME`), OR
   - The beginning of the channel history (up to 500 messages)

2. **AI Processing**: The collected messages are sent to Google's Gemini AI for analysis and summarization

3. **Summary Output**: The generated summary is posted to the configured summary output channel (not the original channel)

4. **Visual Feedback**: The bot reacts to the command message with:
   - ⏳ while processing
   - ✅ when complete
   - ❌ if an error occurs

## Configuration

### Required Environment Variables

```bash
# The channel where summaries will be posted
LOTSLARP_BOT_SUMMARY_CHANNEL_ID="1234567890123456789"

# The role name that marks the end of a summary period
LOTSLARP_DISCORD_BOT_SUMMARY_ROLE_NAME="Summary"

# Gemini API configuration (already required for other features)
LOTSLARP_DISCORD_BOT_GEMINI_API_KEY="your-api-key"
LOTSLARP_DISCORD_BOT_GEMINI_MODEL="gemini-2.5-pro"
```

### Optional Environment Variables

```bash
# Custom prompt for channel summaries (optional)
LOTSLARP_DISCORD_BOT_CHANNEL_SUMMARY_PROMPT="Your custom prompt here..."
```

## Features

### Cross-Guild Support
- Works across all Discord servers (guilds) the bot has access to
- You can summarize channels from any server where the bot is present

### Smart Message Filtering
- Automatically skips bot messages
- Skips empty messages
- Replaces user and role mentions with readable names
- Stops at the last summary marker (role mention)

### Comprehensive Summary Output
The summary includes:
- Channel name and server
- Who requested the summary
- Number of messages analyzed
- Time range of messages
- Whether it's since the last summary or from history
- AI-generated summary with:
  - Main topics discussed
  - Key decisions or conclusions
  - Important questions raised
  - Action items or next steps

### Privacy & Security
- No messages are posted in the original channel
- Only reactions are added to the command message
- Summaries are posted only to the configured output channel
- Requires proper bot permissions (read message history)

## Permissions Required

The bot needs the following permissions:
- **Read Message History**: To fetch messages from the target channel
- **Add Reactions**: To provide visual feedback on the command
- **Send Messages**: In the summary output channel

## Example Output

```
📊 Channel Summary
Channel: #general (General Chat)
Server: My Discord Server
Requested by: @Username
Messages analyzed: 127 since last summary
Time range: 2025-12-17 10:00 to 2025-12-17 18:00 UTC

Summary:
• Main discussion focused on planning the upcoming event
• Decision made to schedule for next Saturday at 3 PM
• Key questions raised about venue capacity and catering options
• Action items:
  - @User1 to confirm venue booking
  - @User2 to get catering quotes
  - Team to finalize guest list by Friday
```

## Error Handling

The bot handles various error scenarios:
- Invalid channel ID
- Channel not found or bot doesn't have access
- Missing permissions
- Summary output channel not configured
- AI generation failures

All errors are reported with clear messages and appropriate reactions.

## Tips

1. **Regular Summaries**: Use the summary role mention feature to mark the end of discussion periods
2. **Channel IDs**: Right-click a channel and "Copy ID" (requires Developer Mode enabled in Discord)
3. **Testing**: Test with a small channel first to verify configuration
4. **Permissions**: Ensure the bot has access to both the source and output channels

## Troubleshooting

### "Could not find channel"
- Verify the bot is in the server with that channel
- Check that the channel ID is correct
- Ensure the bot has permission to view the channel

### "Summary output channel is not configured"
- Set the `LOTSLARP_BOT_SUMMARY_CHANNEL_ID` environment variable
- Redeploy the bot after configuration changes

### "Bot does not have permission"
- Grant the bot "Read Message History" permission in the target channel
- Grant "Send Messages" permission in the summary output channel

## Integration with Existing Features

This feature complements the existing digest system:
- **Digest**: Automatic scheduled summaries of tagged messages across all channels
- **Summarize**: On-demand summaries of specific channel conversations

Both use the same AI model and can share configuration for consistent output quality.
