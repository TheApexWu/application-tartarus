"""
Screening question answer engine.
Priority: lookup table > pattern matching > AI fallback.
"""

import os
import re
import json
from .config import load_answers


# Common question patterns mapped to answer keys
QUESTION_PATTERNS = [
    # Work authorization
    (r"authorized.*work.*(?:us|united states)", "work_auth"),
    (r"legally.*authorized", "work_auth"),
    (r"eligib(?:le|ility).*work.*(?:us|united states)", "work_auth"),
    (r"right to work", "work_auth"),
    # Sponsorship
    (r"sponsor", "sponsorship"),
    (r"visa", "sponsorship"),
    (r"require.*immigration", "sponsorship"),
    # Start date / availability
    (r"(?:when|earliest|start date|available to start)", "start_date"),
    (r"notice period", "start_date"),
    # Location / relocation
    (r"(?:willing|open).*relocat", "relocation"),
    (r"(?:preferred|current|where).*locat", "location"),
    (r"work.*(?:on-?site|remote|hybrid|office)", "work_mode"),
    # Salary
    (r"salary.*(?:expect|require|range|desire)", "salary"),
    (r"compensation.*(?:expect|require)", "salary"),
    (r"pay.*(?:expect|range)", "salary"),
    # Years of experience
    (r"(?:years?|how long|how much).*experience.*python", "years_python"),
    (r"(?:years?|how long|how much).*experience.*javascript", "years_javascript"),
    (r"(?:years?|how long|how much).*experience.*(?:ml|machine learning)", "years_ml"),
    (r"(?:years?|how long|how much).*experience.*sql", "years_sql"),
    (r"(?:years?|how long|how much).*experience.*react", "years_react"),
    (r"(?:years?|how long|how much).*experience", "years_general"),
    # Education
    (r"(?:highest|level).*(?:education|degree)", "education_level"),
    (r"(?:gpa|grade point)", "gpa"),
    # Demographics (optional, skip if possible)
    (r"gender", "gender"),
    (r"race|ethnicity", "ethnicity"),
    (r"veteran", "veteran"),
    (r"disability|disabled", "disability"),
    (r"pronouns", "pronouns"),
    # LinkedIn
    (r"linkedin", "linkedin_url"),
    (r"github", "github_url"),
    (r"portfolio|website|personal.*(?:site|page)", "website_url"),
    # Cover letter / why
    (r"(?:why|what).*(?:interest|excit|attract|compan|role|position|apply)", "why_interested"),
    (r"cover letter", "cover_letter"),
    (r"tell.*(?:us|me).*(?:about|yourself)", "about_me"),
    # Age / legal
    (r"(?:18|age|legal age|at least 18)", "over_18"),
    (r"background.*check", "background_check"),
    (r"drug.*(?:test|screen)", "drug_test"),
]


def match_question(question: str) -> str:
    """Match a screening question to an answer key via pattern matching."""
    q_lower = question.lower().strip()
    for pattern, key in QUESTION_PATTERNS:
        if re.search(pattern, q_lower):
            return key
    return None


def get_answer(question: str, company: str = None, role: str = None, jd_text: str = None) -> dict:
    """
    Get answer for a screening question.
    Returns {"answer": str, "source": "lookup"|"ai"|"skip", "confidence": float}
    """
    answers = load_answers()

    # 1. Pattern match to lookup table
    key = match_question(question)
    if key and key in answers:
        val = answers[key]
        # Handle dict answers (have both value and display text)
        if isinstance(val, dict):
            return {"answer": val.get("value", str(val)), "source": "lookup", "confidence": 1.0}
        return {"answer": str(val), "source": "lookup", "confidence": 1.0}

    # 2. Check for exact match in custom_answers
    custom = answers.get("custom_answers", {})
    q_lower = question.lower().strip()
    for q, a in custom.items():
        if q.lower() in q_lower or q_lower in q.lower():
            return {"answer": str(a), "source": "lookup", "confidence": 0.9}

    # 3. AI fallback for free-text questions
    if _is_freetext_question(question):
        ai_answer = _ai_generate_answer(question, company, role, jd_text, answers)
        if ai_answer:
            return {"answer": ai_answer, "source": "ai", "confidence": 0.7}

    # 4. Skip - can't answer
    return {"answer": None, "source": "skip", "confidence": 0.0}


def _is_freetext_question(question: str) -> bool:
    """Detect if a question expects a free-text response (not a dropdown/checkbox)."""
    freetext_signals = [
        "why", "what", "how", "describe", "tell us", "explain",
        "share", "elaborate", "additional", "anything else",
    ]
    q_lower = question.lower()
    return any(signal in q_lower for signal in freetext_signals)


def _ai_generate_answer(question: str, company: str, role: str, jd_text: str, answers: dict) -> str:
    """Use Claude to generate a short answer to a free-text screening question."""
    api_key = os.environ.get("ANTHROPIC_API_KEY")
    if not api_key:
        # Try .env
        from .config import BASE_DIR
        env_file = BASE_DIR / "resume" / ".env"
        if env_file.exists():
            for line in env_file.read_text().splitlines():
                if line.startswith("ANTHROPIC_API_KEY="):
                    api_key = line.split("=", 1)[1].strip().strip('"').strip("'")
                    break
    if not api_key:
        return None

    try:
        import httpx
    except ImportError:
        return None

    about = answers.get("about_me", "Recent NYU CS + Data Science grad. I build things and ship them.")
    prompt = f"""You are filling out a job application for {company or 'a company'}, role: {role or 'Software Engineer'}.

Applicant background: {about}

Answer this screening question in 2-3 sentences max. Be direct, no fluff, no corporate speak. Sound like a real person, not a chatbot.

Question: {question}

Rules:
- Keep under 500 characters
- No made-up claims
- Don't mention other companies
- Be honest and straightforward
- If the question is about salary, say "open to discussion" or use the range from context

Answer:"""

    try:
        resp = httpx.post(
            "https://api.anthropic.com/v1/messages",
            headers={
                "x-api-key": api_key,
                "anthropic-version": "2023-06-01",
                "content-type": "application/json",
            },
            json={
                "model": "claude-haiku-4-5-20251001",
                "max_tokens": 300,
                "messages": [{"role": "user", "content": prompt}],
            },
            timeout=30,
        )
        resp.raise_for_status()
        result = resp.json()
        return result["content"][0]["text"].strip()
    except Exception:
        return None
