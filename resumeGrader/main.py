import os
import re
import json
import tempfile
import logging
from dotenv import load_dotenv
from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.ext import (
    Application,
    CommandHandler,
    MessageHandler,
    ContextTypes,
    filters,
    CallbackQueryHandler,
)
from telegram.constants import ParseMode
import requests
from bs4 import BeautifulSoup
import PyPDF2
import openai

# ---------- CONFIG ----------
load_dotenv()
BOT_TOKEN = os.getenv("BOT_TOKEN")
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
openai.api_key = OPENAI_API_KEY

# ---------- LOGGING ----------
logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s", level=logging.INFO
)
logger = logging.getLogger(__name__)

# ---------- HELPERS ----------
def extract_text_from_pdf(path: str) -> str:
    """Extract text from a PDF using PyPDF2 (simple, works for many PDFs)."""
    text = []
    try:
        with open(path, "rb") as f:
            reader = PyPDF2.PdfReader(f)
            for page in reader.pages:
                page_text = page.extract_text()
                if page_text:
                    text.append(page_text)
    except Exception as e:
        logger.exception("Failed to extract PDF text: %s", e)
    return "\n".join(text).strip()

def is_url(text: str) -> bool:
    return bool(re.match(r"https?://", text.strip()))

def fetch_job_description_from_url(url: str) -> str:
    """Fetch the page and try to extract main text from <article> or <p> tags."""
    try:
        headers = {"User-Agent": "Mozilla/5.0 (compatible; ResumeScoreBot/1.0)"}
        resp = requests.get(url, headers=headers, timeout=10)
        resp.raise_for_status()
        soup = BeautifulSoup(resp.text, "html.parser")

        # Try common article containers first
        article = soup.find("article")
        if article:
            paragraphs = [p.get_text(separator=" ", strip=True) for p in article.find_all("p")]
            if paragraphs:
                return "\n\n".join(paragraphs)

        # Fallback: collect visible <p> text
        paragraphs = [p.get_text(separator=" ", strip=True) for p in soup.find_all("p")]
        if paragraphs:
            return "\n\n".join(paragraphs)

        # As a last resort, return raw text
        return soup.get_text(separator="\n", strip=True)
    except Exception as e:
        logger.exception("Failed to fetch job description from URL: %s", e)
        return ""

def make_prompt_for_ats(resume_text: str, job_desc: str) -> str:
    """
    Create a strict instruction prompt asking the model to return JSON:
    {
      "score": int,         # 0-100
      "matched_keywords": ["x","y"],
      "missing_keywords": ["a","b"],
      "suggestions": ["short suggestion 1", ...],
      "short_summary": "one-line summary"
    }
    """
    # Keep the prompt focused and instruct JSON-only output
    prompt = f"""
You are an ATS/Recruiter assistant. Compare the resume to the job description below and produce a JSON object ONLY (no extra commentary).
Requirements:
- "score": integer between 0 and 100 (higher means better match). Use factors like keyword match, relevant experience, role fit.
- "matched_keywords": list of important keywords found on the resume (strings).
- "missing_keywords": list of important keywords found in job description but not in resume.
- "suggestions": short actionable suggestions (1-2 sentences each) to improve the resume for this job.
- "short_summary": one sentence summary of overall fit.

If something is missing or you can't compute, return sensible defaults (e.g., empty arrays).
Return strictly valid JSON and nothing else.

Resume:
\"\"\"{resume_text[:30000]}\"\"\"

Job description:
\"\"\"{job_desc[:30000]}\"\"\"
"""
    return prompt

def call_openai_chat(prompt: str) -> str:
    """
    Use OpenAI chat completion. Returns the assistant text (expected JSON).
    """
    try:
        # Using chat completion as a generic call.
        # If your OpenAI client differs, replace this with your SDK's call.
        response = openai.ChatCompletion.create(
            model="gpt-4o-mini",
            messages=[{"role": "user", "content": prompt}],
            temperature=0.0,
            max_tokens=1000,
        )
        # The returned text:
        return response["choices"][0]["message"]["content"].strip()
    except Exception as e:
        logger.exception("OpenAI request failed: %s", e)
        raise

def parse_model_json(output_text: str) -> dict:
    """
    Try to find a JSON object in the model output and parse it.
    """
    # Try to locate the first JSON object {...}
    try:
        # Find the first '{' and last '}' to try extract JSON blob
        start = output_text.find("{")
        end = output_text.rfind("}")
        if start != -1 and end != -1 and end > start:
            json_text = output_text[start:end+1]
            return json.loads(json_text)
        # Fallback attempt: try direct json loads
        return json.loads(output_text)
    except Exception as e:
        logger.exception("Failed to parse JSON from model output: %s", e)
        # Return a safe default structure
        return {
            "score": 0,
            "matched_keywords": [],
            "missing_keywords": [],
            "suggestions": ["Model output could not be parsed. Try re-running or adjust prompt."],
            "short_summary": "Unable to parse model response."
        }

# ---------- TELEGRAM HANDLERS ----------
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "Hello! I'm ResumeScoreBot 🤖\n\n"
        "*How it works:*\n"
        "1) 📄 Send your resume as a PDF.\n"
        "2) 🔗 Send the job description text or a link.\n\n"
        "I'll return an *ATS compatibility score (0–100)* and *actionable suggestions*.",
        parse_mode=ParseMode.MARKDOWN,
    )

async def handle_pdf(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        doc = update.message.document
        if not doc:
            await update.message.reply_text("⚠️ *Please upload a PDF file.*", parse_mode=ParseMode.MARKDOWN)
            return

        if not doc.file_name.lower().endswith(".pdf"):
            await update.message.reply_text("⚠️ *Please upload a PDF file (with .pdf extension).*", parse_mode=ParseMode.MARKDOWN)
            return

        # Download file properly
        tmp = tempfile.NamedTemporaryFile(delete=False, suffix=".pdf")
        file_path = tmp.name
        tmp.close()

        tg_file = await doc.get_file()   # <-- await here
        await tg_file.download_to_drive(file_path)

        resume_text = extract_text_from_pdf(file_path)
        if not resume_text:
            await update.message.reply_text("⚠️ *Could not extract text from the PDF.* Try a different file.", parse_mode=ParseMode.MARKDOWN)
            return

        context.user_data["resume_text"] = resume_text
        context.user_data["resume_file_path"] = file_path

        await update.message.reply_text(
            "✅ *Resume received and parsed!*\n"
            "Now send the *job description* text or a *link* to the job post.",
            parse_mode=ParseMode.MARKDOWN,
        )

    except Exception as e:
        logger.exception("Error handling PDF: %s", e)
        await update.message.reply_text("⚠️ *Something went wrong while processing the PDF.*", parse_mode=ParseMode.MARKDOWN)


async def handle_text(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_message = update.message.text.strip()

    # If the user didn’t upload a resume yet
    if "resume_text" not in context.user_data:
        await update.message.reply_text("⚠️ *Please upload your resume PDF first.* 📄", parse_mode=ParseMode.MARKDOWN)
        return

    resume_text = context.user_data["resume_text"]

    # 🆕 Save job description so buttons can reuse it
    context.user_data["last_job_desc"] = user_message

    # Use OpenAI to score the resume vs job description
    prompt = f"""
    You are an ATS (Applicant Tracking System) assistant.
    Compare the following resume to the job description.

    Your response must always follow this structured format with emojis:

    *📌 Job Description Keywords:*
    - keyword1
    - keyword2

    *📄 Resume Keywords:*
    - 🎓 **Education**: ...
    - 🛠️ **Technical Skills**: ...
    - 💡 **Projects**: ...
    - 🏆 **Achievements**: ...

    *❌ Missing Keywords from Resume:*
    - list missing keywords clearly OR say: ✅ No missing keywords 🎉

    *📊 ATS Score (out of 100):*
    - Final score here, with 1–2 sentences of explanation.

    Resume:
    {resume_text[:3000]}

    Job Description:
    {user_message}
    """

    try:
        response = openai.ChatCompletion.create(
            model="gpt-4o-mini",
            messages=[{"role": "user", "content": prompt}],
            temperature=0.0,
            max_tokens=800,
        )
        ats_result = response["choices"][0]["message"]["content"].strip()
        await update.message.reply_text(ats_result, parse_mode=ParseMode.MARKDOWN)

        # 🆕 Add inline buttons
        keyboard = [
            [
                InlineKeyboardButton("🔄 Re-run check", callback_data="rerun"),
                InlineKeyboardButton("❌ Missing skills", callback_data="missing"),
            ],
            [
                InlineKeyboardButton("✍️ Tailored summary", callback_data="summary"),
                InlineKeyboardButton("🆕 New Job", callback_data="new_job"),
            ]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)
        await update.message.reply_text("✨ *What would you like to do next?*", reply_markup=reply_markup, parse_mode=ParseMode.MARKDOWN)

    except Exception as e:
        await update.message.reply_text("⚠️ *Something went wrong while checking ATS score.*", parse_mode=ParseMode.MARKDOWN)
        print(f"OpenAI error: {e}")


async def button_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()  # Acknowledge the button click

    resume_text = context.user_data.get("resume_text")
    last_job_desc = context.user_data.get("last_job_desc")

    if not resume_text or not last_job_desc:
        await query.edit_message_text("Please upload a resume and job description first.")
        return

    if query.data == "rerun":
        await query.edit_message_text("🔄 *Re-running ATS check...*", parse_mode=ParseMode.MARKDOWN)
        # Reuse the same structured prompt as in handle_text
        prompt = f"""
        You are an ATS (Applicant Tracking System) assistant.
        Compare the following resume to the job description.

        Your response must always follow this structured format with emojis:

        *📌 Job Description Keywords:*
        - keyword1
        - keyword2

        *📄 Resume Keywords:*
        - 🎓 **Education**: ...
        - 🛠️ **Technical Skills**: ...
        - 💡 **Projects**: ...
        - 🏆 **Achievements**: ...

        *❌ Missing Keywords from Resume:*
        - list missing keywords clearly OR say: ✅ No missing keywords 🎉

        *📊 ATS Score (out of 100):*
        - Final score here, with 1–2 sentences of explanation.

        Resume:
        {resume_text[:3000]}

        Job Description:
        {last_job_desc}
        """
        try:
            response = openai.ChatCompletion.create(
                model="gpt-4o-mini",
                messages=[{"role": "user", "content": prompt}],
                temperature=0.0,
                max_tokens=800,
            )
            ats_result = response["choices"][0]["message"]["content"].strip()
            await query.edit_message_text(ats_result, parse_mode=ParseMode.MARKDOWN)

            # Send buttons again for further actions
            keyboard = [
                [
                    InlineKeyboardButton("🔄 Re-run check", callback_data="rerun"),
                    InlineKeyboardButton("❌ Missing skills", callback_data="missing"),
                ],
                [
                    InlineKeyboardButton("✍️ Tailored summary", callback_data="summary"),
                    InlineKeyboardButton("🆕 New Job", callback_data="new_job"),
                ]
            ]
            reply_markup = InlineKeyboardMarkup(keyboard)
            await query.message.reply_text("✨ *What would you like to do next?*", reply_markup=reply_markup, parse_mode=ParseMode.MARKDOWN)
        except Exception as e:
            await query.edit_message_text("⚠️ *Something went wrong while re-running the ATS check.*", parse_mode=ParseMode.MARKDOWN)
            logger.exception("OpenAI error on rerun: %s", e)

    elif query.data == "missing":
        prompt = f"""
        You are a helpful recruiter assistant. Extract the most important keywords and competencies from the job description, compare with the resume, and return a concise Markdown-only response with emojis.

        Follow this exact structure:

        *❌ Missing Keywords (prioritized):*
        - keyword – very short why it's important (if applicable)
        - keyword – ...

        *✅ Matched Keywords:*
        - keyword, keyword, keyword

        *🧭 Suggestions to Improve:*
        - short actionable suggestion 1
        - short actionable suggestion 2
        - short actionable suggestion 3

        If there are no missing keywords, write: ✅ No missing keywords 🎉
        Keep it brief and skimmable. Return only Markdown.

        Resume:
        {resume_text[:3000]}

        Job Description:
        {last_job_desc}
        """
        response = openai.ChatCompletion.create(
            model="gpt-4o-mini",
            messages=[{"role": "user", "content": prompt}],
            temperature=0.0,
            max_tokens=600,
        )
        result = response["choices"][0]["message"]["content"].strip()
        keyboard = [
            [
                InlineKeyboardButton("🔄 Re-run check", callback_data="rerun"),
                InlineKeyboardButton("❌ Missing skills", callback_data="missing"),
            ],
            [
                InlineKeyboardButton("✍️ Tailored summary", callback_data="summary"),
                InlineKeyboardButton("🆕 New Job", callback_data="new_job"),
            ]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)
        await query.edit_message_text(result, parse_mode=ParseMode.MARKDOWN, reply_markup=reply_markup)

    elif query.data == "summary":
        prompt = f"""
        Rewrite a concise, professional resume summary tailored to the job description. Use a confident, friendly tone. Return only Markdown, following this structure:

        *✍️ Tailored Professional Summary:*
        A 3–5 line paragraph highlighting the most relevant experience, skills, and impact for this role. Prefer bold for key role/skills, and keep it scannable.

        Resume:
        {resume_text[:3000]}

        Job Description:
        {last_job_desc}
        """
        response = openai.ChatCompletion.create(
            model="gpt-4o-mini",
            messages=[{"role": "user", "content": prompt}],
            temperature=0.3,
            max_tokens=600,
        )
        result = response["choices"][0]["message"]["content"].strip()
        keyboard = [
            [
                InlineKeyboardButton("🔄 Re-run check", callback_data="rerun"),
                InlineKeyboardButton("❌ Missing skills", callback_data="missing"),
            ],
            [
                InlineKeyboardButton("✍️ Tailored summary", callback_data="summary"),
                InlineKeyboardButton("🆕 New Job", callback_data="new_job"),
            ]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)
        await query.edit_message_text(result, parse_mode=ParseMode.MARKDOWN, reply_markup=reply_markup)

    elif query.data == "new_job":
        # Clear the last job description and prompt for a new one
        context.user_data.pop("last_job_desc", None)
        await query.edit_message_text(
            "🆕 *Ready for a new job!*\n\n" 
            "Send me the *job description* text or a *link* to the job posting.",
            parse_mode=ParseMode.MARKDOWN
        )


async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "*Flow*:\n"
        "1) ▶️ /start to see instructions\n"
        "2) 📄 Send your resume as a PDF\n"
        "3) 🔗 Send the job description text or job posting link\n\n"
        "*Commands*:\n"
        "• /start – start\n"
        "• /help – this message\n",
        parse_mode=ParseMode.MARKDOWN,
    )

def main():
    if not BOT_TOKEN or not OPENAI_API_KEY:
        logger.error("BOT_TOKEN and OPENAI_API_KEY must be set in .env")
        print("BOT_TOKEN and OPENAI_API_KEY must be set in .env")
        return

    app = Application.builder().token(BOT_TOKEN).build()

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("help", help_command))
    # PDF documents
    app.add_handler(MessageHandler(filters.Document.PDF, handle_pdf))
    # Text (job descriptions)
    app.add_handler(MessageHandler(filters.TEXT & (~filters.COMMAND), handle_text))
    app.add_handler(CallbackQueryHandler(button_handler))

    logger.info("Bot starting...")
    app.run_polling()

if __name__ == "__main__":
    main()
