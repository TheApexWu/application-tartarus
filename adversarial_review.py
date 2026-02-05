#!/usr/bin/env python3
"""
Adversarial Resume Review (Tartarus Layer 3)
=============================================

Persona: Senior recruiter / hiring manager at the target company.
Reviews resume content through the lens of someone doing a 30-second scan.

Checks:
  1. Action verb repetition & weakness
  2. Missing quantified impact
  3. Keyword alignment with JD
  4. Dead weight bullets
  5. Skills mismatch for role type
  6. Pharma/industry-specific gaps (if applicable)

Usage:
  python adversarial_review.py output/company/alex-wu_CV.yaml [jd_text_or_path]
  python adversarial_review.py output/company/alex-wu_CV.yaml --role "Data Scientist" --company "BMS"
"""
from __future__ import annotations

import re
import sys
import yaml
from collections import Counter
from pathlib import Path


# ── Verb Analysis ────────────────────────────────────────────────

WEAK_VERBS = {
    "helped", "assisted", "worked on", "was responsible for",
    "participated", "contributed", "involved in", "handled",
    "utilized", "leveraged",  # corporate fluff
}

STRONG_VERBS = {
    "designed", "implemented", "optimized", "automated", "reduced",
    "accelerated", "validated", "evaluated", "architected", "shipped",
    "discovered", "identified", "quantified", "transformed", "scaled",
    "pioneered", "streamlined", "delivered", "orchestrated",
}

OVERUSED_THRESHOLD = 2  # same verb > 2x = flag


# ── Industry Keyword Banks ───────────────────────────────────────

INDUSTRY_KEYWORDS = {
    "pharma_ds": {
        "must_have": ["python", "sql", "machine learning", "statistical"],
        "should_have": ["r", "clinical", "experiment", "hypothesis", "regression",
                       "validation", "cross-validation", "feature engineering",
                       "pandas", "numpy", "matplotlib", "tableau", "powerbi"],
        "nice_to_have": ["sas", "gxp", "fda", "real-world data", "rwe",
                        "survival analysis", "bayesian", "causal inference",
                        "clinical trial", "biostatistics"],
        "red_flags": ["tailwind", "css", "react", "next.js", "frontend",
                     "ui components", "html"],
    },
    "tech_ds": {
        "must_have": ["python", "sql", "machine learning", "a/b test"],
        "should_have": ["experimentation", "metrics", "pipeline", "production",
                       "spark", "airflow", "dbt", "etl"],
        "nice_to_have": ["causal", "bayesian", "distributed", "real-time"],
        "red_flags": [],
    },
    "ml_eng": {
        "must_have": ["python", "pytorch", "tensorflow", "ml", "deploy"],
        "should_have": ["docker", "kubernetes", "mlops", "gpu", "inference",
                       "training", "fine-tune", "distributed"],
        "nice_to_have": ["cuda", "onnx", "triton", "ray"],
        "red_flags": [],
    },
}


def extract_bullets(data: dict) -> list[tuple[str, str]]:
    """Extract all bullets with their section context."""
    bullets = []
    sections = data.get("cv", {}).get("sections", {})
    
    for section_name, entries in sections.items():
        if not isinstance(entries, list):
            continue
        for entry in entries:
            if not isinstance(entry, dict):
                continue
            context = entry.get("company") or entry.get("name") or entry.get("institution") or ""
            for h in entry.get("highlights", []):
                if h:
                    bullets.append((section_name, context, h))
    
    return bullets


def analyze_verbs(bullets: list[tuple[str, str, str]]) -> dict:
    """Check for weak, overused, and missing strong verbs."""
    first_words = []
    issues = []
    
    for section, context, bullet in bullets:
        # Get first meaningful word (skip articles)
        words = bullet.split()
        first = words[0].lower().rstrip("ed,s") if words else ""
        first_full = words[0] if words else ""
        first_words.append(first_full)
        
        # Check for weak verbs
        bullet_lower = bullet.lower()
        for weak in WEAK_VERBS:
            if bullet_lower.startswith(weak):
                issues.append(f"  ⚠️  [{context[:20]}] Weak opener: \"{first_full}...\" → try a stronger verb")
                break
    
    # Check overuse
    counts = Counter(first_words)
    for verb, count in counts.most_common():
        if count > OVERUSED_THRESHOLD:
            issues.append(f"  🔄 \"{verb}\" used {count}x — vary your verbs")
    
    return {"first_words": counts, "issues": issues}


def analyze_impact(bullets: list[tuple[str, str, str]]) -> list[str]:
    """Check for missing quantified impact."""
    issues = []
    
    for section, context, bullet in bullets:
        has_number = bool(re.search(r'\d+', bullet))
        has_impact = any(w in bullet.lower() for w in [
            "improved", "reduced", "increased", "saved", "accelerated",
            "accuracy", "precision", "recall", "auc", "f1",
            "%", "percent", "hours", "minutes",
        ])
        
        # Experience bullets without numbers are the worst offenders
        if section == "experience" and not has_number:
            issues.append(f"  📊 [{context[:20]}] No numbers: \"{bullet[:60]}...\"")
        elif section == "experience" and has_number and not has_impact:
            issues.append(f"  📊 [{context[:20]}] Has numbers but no impact verb: \"{bullet[:60]}...\"")
    
    return issues


def analyze_keywords(data: dict, industry: str = "pharma_ds") -> list[str]:
    """Check keyword alignment with industry expectations."""
    issues = []
    bank = INDUSTRY_KEYWORDS.get(industry)
    if not bank:
        return issues
    
    # Flatten all text
    full_text = yaml.dump(data.get("cv", {}).get("sections", {})).lower()
    
    # Check must-haves
    missing_must = [k for k in bank["must_have"] if k not in full_text]
    if missing_must:
        issues.append(f"  🚨 MISSING must-have keywords: {', '.join(missing_must)}")
    
    # Check should-haves
    missing_should = [k for k in bank["should_have"] if k not in full_text]
    if missing_should:
        issues.append(f"  ⚠️  Missing recommended keywords: {', '.join(missing_should[:6])}")
    
    # Check red flags
    found_flags = [k for k in bank.get("red_flags", []) if k in full_text]
    if found_flags:
        issues.append(f"  🔴 Red flags for this role type: {', '.join(found_flags)} (consider removing)")
    
    return issues


def analyze_dead_weight(bullets: list[tuple[str, str, str]]) -> list[str]:
    """Flag bullets that don't add value for a DS role."""
    issues = []
    filler_signals = [
        "collaborated in agile", "documentation and version control",
        "troubleshooting hardware", "print server", "servicenow",
        "endpoint imaging", "help desk",
    ]
    
    for section, context, bullet in bullets:
        bullet_lower = bullet.lower()
        for signal in filler_signals:
            if signal in bullet_lower:
                issues.append(f"  🗑️  [{context[:20]}] Likely dead weight for DS: \"{bullet[:60]}...\"")
                break
    
    return issues


def llm_review(data: dict, industry: str, jd_text: str = "") -> str:
    """Run LLM-backed adversarial review as a senior recruiter persona."""
    import os
    import json
    
    # Try to load API keys
    env = {}
    env_path = Path(__file__).parent / ".env"
    if env_path.exists():
        for line in env_path.read_text().splitlines():
            if "=" in line and not line.startswith("#"):
                k, v = line.split("=", 1)
                env[k.strip()] = v.strip().strip("\"'")
    
    # Build resume text
    sections = data.get("cv", {}).get("sections", {})
    resume_text = yaml.dump(sections, default_flow_style=False, allow_unicode=True)
    
    industry_context = {
        "pharma_ds": "pharmaceutical/biotech company (like BMS, J&J, Pfizer). They care about: statistical rigor, clinical data experience, experiment design, regulatory awareness, R/SAS, and cross-functional collaboration with scientists.",
        "tech_ds": "tech company. They care about: A/B testing, metrics, production ML, scale, experimentation platforms, SQL mastery, and business impact.",
        "ml_eng": "ML engineering role. They care about: model training/serving, MLOps, GPU optimization, distributed systems, production deployment, and latency/throughput.",
    }.get(industry, "data science role")
    
    prompt = f"""You are a SENIOR RECRUITER with 15 years of experience hiring for a {industry_context}

You are doing a 30-second resume scan. Be brutally honest. You see 200 resumes a day.

RESUME:
{resume_text}

{"JOB DESCRIPTION:" + chr(10) + jd_text if jd_text else ""}

Give your assessment in this exact format:

FIRST IMPRESSION (what you think in 6 seconds):
[one paragraph]

STRENGTHS (what makes you keep reading):
- [bullet]

WEAKNESSES (what makes you hesitate):  
- [bullet]

SPECIFIC BULLET REWRITES (give exact before → after for the worst 5 bullets):
1. BEFORE: "[exact bullet text]"
   AFTER: "[improved version]"

MISSING KEYWORDS for this role type:
- [keyword]: why it matters

VERDICT: [PHONE SCREEN / MAYBE / PASS] and why in one sentence.

Be harsh. Be specific. No fluff."""

    # Try Gemini first, then Anthropic
    gemini_key = os.environ.get("GEMINI_API_KEY") or env.get("GEMINI_API_KEY")
    anthropic_key = os.environ.get("ANTHROPIC_API_KEY") or env.get("ANTHROPIC_API_KEY")
    
    if gemini_key:
        try:
            import httpx
            resp = httpx.post(
                f"https://generativelanguage.googleapis.com/v1beta/models/gemini-2.0-flash:generateContent?key={gemini_key}",
                json={"contents": [{"parts": [{"text": prompt}]}]},
                timeout=30,
            )
            if resp.status_code == 200:
                return resp.json()["candidates"][0]["content"]["parts"][0]["text"]
            else:
                print(f"  Gemini error: {resp.status_code}")
        except Exception as e:
            print(f"  Gemini failed: {e}")
    
    if anthropic_key:
        try:
            import httpx
            resp = httpx.post(
                "https://api.anthropic.com/v1/messages",
                headers={"x-api-key": anthropic_key, "anthropic-version": "2023-06-01", "content-type": "application/json"},
                json={"model": "claude-sonnet-4-20250514", "max_tokens": 2000,
                      "messages": [{"role": "user", "content": prompt}]},
                timeout=30,
            )
            if resp.status_code == 200:
                return resp.json()["content"][0]["text"]
        except Exception as e:
            print(f"  Anthropic failed: {e}")
    
    return "(No LLM API key available — showing rule-based review only)"


def run_review(yaml_path: str, industry: str = "pharma_ds", jd_text: str = "", llm: bool = True):
    """Run full adversarial review (rule-based + LLM)."""
    data = yaml.safe_load(open(yaml_path))
    bullets = extract_bullets(data)
    
    print(f"\n{'='*60}")
    print(f"  ADVERSARIAL RESUME REVIEW")
    print(f"  File: {yaml_path}")
    print(f"  Industry: {industry}")
    print(f"  Bullets analyzed: {len(bullets)}")
    print(f"{'='*60}\n")
    
    # 1. Verb analysis
    verb_result = analyze_verbs(bullets)
    if verb_result["issues"]:
        print("ACTION VERBS:")
        for issue in verb_result["issues"]:
            print(issue)
        print()
    
    # 2. Impact analysis
    impact_issues = analyze_impact(bullets)
    if impact_issues:
        print("QUANTIFIED IMPACT:")
        for issue in impact_issues:
            print(issue)
        print()
    
    # 3. Keyword analysis
    keyword_issues = analyze_keywords(data, industry)
    if keyword_issues:
        print("KEYWORD ALIGNMENT:")
        for issue in keyword_issues:
            print(issue)
        print()
    
    # 4. Dead weight
    dead_issues = analyze_dead_weight(bullets)
    if dead_issues:
        print("DEAD WEIGHT:")
        for issue in dead_issues:
            print(issue)
        print()
    
    # Summary
    total_issues = (len(verb_result["issues"]) + len(impact_issues) 
                   + len(keyword_issues) + len(dead_issues))
    print(f"{'='*60}")
    print(f"  Rule-based issues: {total_issues}")
    if total_issues == 0:
        print("  ✅ Clean resume!")
    elif total_issues <= 5:
        print("  🟡 Minor tweaks needed")
    elif total_issues <= 10:
        print("  🟠 Solid revisions recommended")
    else:
        print("  🔴 Significant rework needed before sending")
    print(f"{'='*60}\n")
    
    # 5. LLM adversarial review
    if llm:
        print("🤖 LLM RECRUITER REVIEW:")
        print("-" * 60)
        result = llm_review(data, industry, jd_text)
        print(result)
        print("-" * 60)


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="Adversarial resume review")
    parser.add_argument("yaml_path", help="Path to resume YAML")
    parser.add_argument("--industry", default="pharma_ds", 
                       choices=["pharma_ds", "tech_ds", "ml_eng"],
                       help="Industry context for review")
    parser.add_argument("--jd", default="", help="JD text or path to JD file")
    parser.add_argument("--no-llm", action="store_true", help="Skip LLM review")
    args = parser.parse_args()
    
    jd_text = ""
    if args.jd:
        jd_path = Path(args.jd)
        if jd_path.exists():
            jd_text = jd_path.read_text()
        else:
            jd_text = args.jd
    
    run_review(args.yaml_path, args.industry, jd_text, llm=not args.no_llm)
