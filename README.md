# YT Live Monitor — Thairath

Poll YouTube live concurrent viewers every 5 minutes and log to Google Sheets.

## Channels monitored

- **ThaiRath News** — `UCrFDdD-EE05N7gjwZho2wqw`
- **ThaiRath Variety** — `UCtc9-CS_FIZ7GGrm8--wsrQ`

## How it works

1. **RSS discovery** (0 quota) — fetches each channel's RSS feed for recent uploads
2. **videos.list** (1 unit/call) — batch checks up to 50 videos for `liveStreamingDetails.concurrentViewers`
3. **Google Sheets** — appends to `Raw` tab, writes daily summaries to `Daily_Summary`
4. **State file** (`/tmp/yt-live-daily-state.json`) — tracks peak viewers across polls
5. **no_agent=True cron** — runs as a shell script, zero LLM tokens

## Setup

```bash
# 1. Clone
git clone <repo-url>
cd yt-live-monitor

# 2. Set env vars
export YOUTUBE_API_KEY=your_key
export YT_SHEET_ID=your_sheet_id

# 3. Run once to test
python3 yt-live-daily.py

# 4. Deploy cron (every 5 min)
#    Uses the shell wrapper: yt-live-daily.sh
```

## Requirements

- Python 3 stdlib only (no pip install needed)
- External helper: `google_api.py` for Sheets writes (path in `GAPI_SCRIPT` env var)

## Cron (no_agent=True)

The Hermes cron job runs `yt-live-daily.sh` which sources env vars and calls the Python script.