## ResumeScoreBot – Telegram ATS Resume Checker

ResumeScoreBot helps users quickly evaluate how well their resume matches a job description. Upload a PDF resume, paste a job description (or a job URL), and get a concise, emoji-enhanced report with an ATS-style score, missing keywords, and improvement suggestions.

## 🎥 Demo

[![Watch the video](https://youtu.be/HzyJTzH7mRU/0.jpg)](https://youtu.be/HzyJTzH7mRU)  
*Click the thumbnail to watch the demo.*


### Features
- **PDF resume parsing**: Upload a PDF; text is extracted via `PyPDF2`.
- **Job description input**: Paste the text or a **URL**; the bot will fetch and extract content using `requests` + `BeautifulSoup`.
- **ATS comparison**: Uses OpenAI (`gpt-4o-mini`) to evaluate resume vs job description.
- **Formatted outputs**: Responses use **bold** text and emojis for skimmability (Markdown in Telegram).
- **Inline actions**:
  - **🔄 Re-run check**: Recompute the ATS analysis on the same resume and job description.
  - **❌ Missing skills**: Show prioritized missing keywords, matched keywords, and improvement suggestions.
  - **✍️ Tailored summary**: Generate a concise professional summary tailored to the job.
  - **🆕 New Job**: Clear the previous job description and prompt you to test the same resume against a different role.

### Requirements
- Python 3.10+
- A Telegram bot token (via BotFather)
- An OpenAI API key

### Project Structure
```
resumeGrader/
  ├─ main.py
  ├─ requirements.txt
  └─ README.md
```

### Setup
1. Clone the repository and enter the project folder.
2. Create and activate a virtual environment (recommended).
```bash
python3 -m venv .venv
source .venv/bin/activate
```
3. Install dependencies.
```bash
pip install -r requirements.txt
```
4. Create a `.env` file in the project root with your credentials:
```bash
cp .env.example .env  # if you create a template; otherwise create .env directly
```
Contents of `.env` (example):
```env
BOT_TOKEN=1234567890:AA...your_telegram_bot_token...
OPENAI_API_KEY=sk-...your_openai_api_key...
```

### Running the bot (polling)
```bash
python main.py
```
You should see a log line like “Bot starting...” and the bot will begin polling. Open Telegram and start a chat with your bot.

### Usage
1. Send `/start` to see brief instructions.
2. Upload your resume as a PDF.
3. Send the job description text or a URL to the job posting.
4. Receive:
   - A structured, Markdown-formatted analysis
   - An **ATS Score (0–100)** with a short explanation
   - Highlighted **missing keywords** and actionable suggestions
   - Inline buttons for quick next actions

Buttons available:
- **🔄 Re-run check**: Re-evaluates with the same inputs.
- **❌ Missing skills**: Focused list of missing vs. matched keywords + suggestions.
- **✍️ Tailored summary**: A polished summary section adapted to the role.
- **🆕 New Job**: Clears the previous job description and prompts you to paste a new one (no need to re-upload the resume).

### Configuration Notes
- The bot uses Markdown in messages. Content returned by the model is sent with `parse_mode=MARKDOWN`.
- URL job descriptions are fetched with a standard user-agent and 10s timeout; extraction prioritizes `<article>` and `<p>` content, then falls back to page text.
- Model used: `gpt-4o-mini` (adjust in `main.py` if desired).

### Environment & Dependencies
Install from `requirements.txt`. If your editor shows import warnings for `telegram` or `PyPDF2`, they should disappear once the virtual environment is active and dependencies are installed.

### Troubleshooting
- “BOT_TOKEN and OPENAI_API_KEY must be set in .env” — Ensure `.env` exists and values are correct.
- No response on button taps — Check the app logs. Make sure polling is running and there are no exceptions from OpenAI or Telegram.
- PDF text empty — Some PDFs are image-based. Try a different file or OCR the document first.

### Security & Privacy
- The bot processes resume text and job descriptions and sends them to OpenAI for analysis. Do not submit sensitive content you’re not comfortable sharing with third-party services.
- Consider access controls if deploying beyond personal use.

### License
This project is provided as-is, for personal or internal use. Add your preferred license here.