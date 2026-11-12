"""
Placement Eligibility Checker
-----------------------------
Reads jobs.csv and students.csv, asks an LLM for each post's criteria
(the LLM sees ONLY the post), checks the reply in Python, matches students,
and writes four draft output files for the placement officer to review.
"""

import csv
import json
import os
import re

# ---------- Settings ----------
JOBS_FILE = "jobs.csv"
STUDENTS_FILE = "students.csv"
PROMPT_FILE = "system_prompt.txt"
OUTPUT_DIR = "output"

ALLOWED_BRANCHES = ["CSE", "IT", "AIDS", "ECE", "EEE", "MECH", "CIVIL"]
FIELDS = ["branches", "min_cgpa", "max_backlogs", "batch", "summary"]

# How each branch can be written in a post (used by the fact check)
BRANCH_PATTERNS = {
    "CSE": r"\bcse\b|computer science",
    "AIDS": r"\bai\s*&\s*ds\b|\bai\s*(and)?\s*ds\b|\baids\b|ai\s*(&|and)\s*data science|artificial intelligence",
    "ECE": r"\bece\b|electronics and communication",
    "EEE": r"\beee\b|electrical",
    "MECH": r"\bmech\b|mechanical",
    "CIVIL": r"\bcivil\b",
}
# "IT" is checked separately and case-sensitively, because "it" is also a normal word.
IT_PATTERN = r"\bIT\b|information technology"


# ---------- 1. Load functions ----------
def load_jobs(path):
    """Read jobs.csv into a list of dictionaries."""
    jobs = []
    try:
        with open(path, newline="", encoding="utf-8") as f:
            for row in csv.DictReader(f):
                jobs.append({"id": row["id"].strip(),
                             "company": row["company"].strip(),
                             "post": row["post"].strip()})
    except FileNotFoundError:
        print(f"ERROR: {path} not found.")
    return jobs


def load_students(path):
    """Read students.csv. CGPA is converted with float(), never kept as text."""
    students = []
    try:
        with open(path, newline="", encoding="utf-8") as f:
            for row in csv.DictReader(f):
                try:
                    students.append({
                        "roll": row["roll"].strip(),
                        "name": row["name"].strip(),
                        "branch": row["branch"].strip().upper(),
                        "cgpa": float(row["cgpa"]),
                        "backlogs": int(row["backlogs"]),
                        "batch": int(row["batch"]),
                    })
                except (ValueError, KeyError):
                    print(f"WARNING: skipped bad student row: {row}")
    except FileNotFoundError:
        print(f"ERROR: {path} not found.")
    return students


# ---------- 2. LLM call ----------
def load_system_prompt(path):
    with open(path, encoding="utf-8") as f:
        return f.read()


def call_llm(system_prompt, post):
    """Send ONE post to the LLM and return its raw text reply.
    The API key is read from the environment (.env file), never written in code."""
    from openai import OpenAI
    client = OpenAI(
        base_url="https://openrouter.ai/api/v1",
        api_key=os.environ["OPENROUTER_API_KEY"],
    )
    response = client.chat.completions.create(
        model=os.environ.get("LLM_MODEL", "openrouter/free"),
        max_tokens=1500,
        temperature=0,
        messages=[
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": f"<post>{post}</post>"},
        ],
    )
    return response.choices[0].message.content or ""


def parse_json(text):
    """Turn the LLM's text into a dictionary. Returns None if it is not JSON."""
    text = text.strip()
    text = re.sub(r"^```(?:json)?|```$", "", text, flags=re.MULTILINE).strip()
    # If the model added words around the JSON, keep only the part from { to }
    if "{" in text and "}" in text:
        text = text[text.index("{"): text.rindex("}") + 1]
    try:
        data = json.loads(text)
    except json.JSONDecodeError:
        # Some models add extra words around the JSON. Try the part between { and }.
        first, last = text.find("{"), text.rfind("}")
        if first == -1 or last <= first:
            return None
        try:
            data = json.loads(text[first:last + 1])
        except json.JSONDecodeError:
            return None
    return data if isinstance(data, dict) else None


# ---------- 3. Validation ----------
def is_number(x):
    return isinstance(x, (int, float)) and not isinstance(x, bool)


def is_valid(d):
    """Check the shape and allowed values of the LLM's reply."""
    if not isinstance(d, dict) or any(k not in d for k in FIELDS):
        return False

    b = d["branches"]
    if not isinstance(b, list) or not all(isinstance(x, str) for x in b):
        return False
    if b == ["ALL"]:
        pass
    elif "ALL" in b or any(x not in ALLOWED_BRANCHES for x in b):
        return False

    if d["min_cgpa"] is not None and not (is_number(d["min_cgpa"]) and 0 <= d["min_cgpa"] <= 10):
        return False
    if d["max_backlogs"] is not None and not (isinstance(d["max_backlogs"], int)
                                              and not isinstance(d["max_backlogs"], bool)
                                              and d["max_backlogs"] >= 0):
        return False
    if d["batch"] is not None and not (isinstance(d["batch"], int)
                                       and not isinstance(d["batch"], bool)
                                       and 2000 <= d["batch"] <= 2100):
        return False
    if not isinstance(d["summary"], str) or len(d["summary"].split()) > 12:
        return False
    return True


def read_criteria(system_prompt, post):
    """Ask the LLM, validate the reply, retry once. Returns a clean dict or None."""
    for attempt in (1, 2):
        try:
            reply = call_llm(system_prompt, post)
        except Exception as e:  # network error, bad key, rate limit...
            print(f"   LLM call failed (attempt {attempt}): {e}")
            continue
        data = parse_json(reply)
        if not is_valid(data):
            print("   RAW REPLY:", repr(reply[:300]))
        if is_valid(data):
            return {k: data[k] for k in FIELDS}  # copy ONLY the five fields
        print(f"   Invalid reply (attempt {attempt}), retrying..." if attempt == 1
              else "   Invalid reply again, falling back.")
    return None  # fallback: caller marks the post needs_review


# ---------- 4. Fact check (Python does not trust the LLM) ----------
def number_in_post(value, post):
    """True if this number is written in the post and is not a percentage."""
    candidates = {f"{value:g}", f"{value:.1f}", f"{value:.2f}"}
    for c in candidates:
        pattern = r"(?<![\d.])" + re.escape(c) + r"(?!\d|\.\d)(\s*(%|percent|per cent))?"
        for m in re.finditer(pattern, post, flags=re.IGNORECASE):
            if not m.group(2):  # followed by % or "percent" -> not a CGPA
                return True
    return False


def check_facts(post, criteria):
    """Remove anything the post does not actually say.
    Returns (cleaned_criteria, list_of_notes)."""
    c = dict(criteria)
    notes = []

    # Branches
    if c["branches"] == ["ALL"]:
        if not re.search(r"any branch|all branches|all branch|any department|all departments",
                         post, flags=re.IGNORECASE):
            c["branches"] = []
            notes.append("LLM said ALL branches but post does not say so")
    else:
        kept = []
        for b in c["branches"]:
            if b == "IT":
                found = re.search(IT_PATTERN, post)
            else:
                found = re.search(BRANCH_PATTERNS[b], post, flags=re.IGNORECASE)
            if found:
                kept.append(b)
            else:
                notes.append(f"branch {b} not named in post (removed)")
        c["branches"] = kept

    # CGPA
    if c["min_cgpa"] is not None:
        c["min_cgpa"] = float(c["min_cgpa"])
        if not number_in_post(c["min_cgpa"], post):
            notes.append(f"CGPA {c['min_cgpa']} not written in post (removed)")
            c["min_cgpa"] = None

    # Batch
    if c["batch"] is not None and str(c["batch"]) not in post:
        notes.append(f"batch {c['batch']} not written in post (removed)")
        c["batch"] = None

    # Backlogs (my extra safety check): post must mention backlog/arrear at all
    if c["max_backlogs"] is not None and not re.search(r"backlog|arrear", post, flags=re.IGNORECASE):
        notes.append("backlog limit given but post never mentions backlogs (removed)")
        c["max_backlogs"] = None

    return c, notes


# ---------- 5. Job status ----------
def job_status(criteria):
    """needs_review if no branches or no CGPA after the fact check."""
    reasons = []
    if not criteria["branches"]:
        reasons.append("no branch named in post")
    if criteria["min_cgpa"] is None:
        reasons.append("no CGPA cut-off written in post (percentage or vague cut-off?)")
    return ("needs_review", reasons) if reasons else ("matched", [])


# ---------- 6. Eligibility ----------
def is_eligible(student, criteria):
    """branch in list (or ALL), cgpa >= cut-off, backlogs <= limit, batch matches."""
    if criteria["branches"] != ["ALL"] and student["branch"] not in criteria["branches"]:
        return False
    if student["cgpa"] < criteria["min_cgpa"]:
        return False
    if criteria["max_backlogs"] is not None and student["backlogs"] > criteria["max_backlogs"]:
        return False
    if criteria["batch"] is not None and student["batch"] != criteria["batch"]:
        return False
    return True


# ---------- 7. Output files ----------
def write_reports(results, students, outdir):
    os.makedirs(outdir, exist_ok=True)

    # job_summary.csv
    with open(os.path.join(outdir, "job_summary.csv"), "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["id", "company", "status", "branches", "min_cgpa", "max_backlogs",
                    "batch", "summary", "eligible_count"])
        for r in results:
            c = r["criteria"]
            if c is None:
                w.writerow([r["id"], r["company"], r["status"], "", "", "", "", "", "n/a"])
            else:
                w.writerow([r["id"], r["company"], r["status"], "|".join(c["branches"]),
                            "" if c["min_cgpa"] is None else c["min_cgpa"],
                            "" if c["max_backlogs"] is None else c["max_backlogs"],
                            "" if c["batch"] is None else c["batch"],
                            c["summary"],
                            len(r["eligible"]) if r["status"] == "matched" else "n/a"])

    # eligible.csv
    with open(os.path.join(outdir, "eligible.csv"), "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["job_id", "company", "roll", "name", "branch", "cgpa", "backlogs", "batch"])
        for r in results:
            for s in r["eligible"]:
                w.writerow([r["id"], r["company"], s["roll"], s["name"], s["branch"],
                            s["cgpa"], s["backlogs"], s["batch"]])

    # review.csv
    with open(os.path.join(outdir, "review.csv"), "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["id", "company", "post", "reason"])
        for r in results:
            if r["status"] == "needs_review":
                w.writerow([r["id"], r["company"], r["post"], "; ".join(r["reasons"])])

    # summary.txt
    eligible_rolls = {s["roll"] for r in results for s in r["eligible"]}
    with open(os.path.join(outdir, "summary.txt"), "w", encoding="utf-8") as f:
        f.write("DRAFT - the placement officer must check this before it is shared.\n\n")
        f.write("Eligible students per job\n")
        for r in results:
            if r["status"] == "matched":
                f.write(f"  {r['id']} {r['company']}: {len(r['eligible'])} eligible\n")
            else:
                f.write(f"  {r['id']} {r['company']}: NEEDS REVIEW (not matched)\n")
        f.write("\nStudents eligible for no job yet\n")
        none_yet = [s for s in students if s["roll"] not in eligible_rolls]
        if none_yet:
            for s in none_yet:
                f.write(f"  {s['roll']} {s['name']} ({s['branch']}, CGPA {s['cgpa']})\n")
        else:
            f.write("  (none)\n")


# ---------- Main ----------
def main():
    try:
        from dotenv import load_dotenv
        load_dotenv()  # loads ANTHROPIC_API_KEY from the .env file
    except ImportError:
        pass

    jobs = load_jobs(JOBS_FILE)
    students = load_students(STUDENTS_FILE)
    if not jobs or not students:
        print("Nothing to process. Check your input files.")
        return
    system_prompt = load_system_prompt(PROMPT_FILE)
    print(f"Loaded {len(jobs)} jobs and {len(students)} students.\n")

    results = []
    for job in jobs:
        print(f"{job['id']} {job['company']}")
        raw = read_criteria(system_prompt, job["post"])
        if raw is None:
            results.append({**job, "criteria": None, "status": "needs_review",
                            "reasons": ["LLM reply missing or invalid after retry"],
                            "eligible": []})
            print("   -> needs_review (LLM fallback)")
            continue

        criteria, notes = check_facts(job["post"], raw)
        status, reasons = job_status(criteria)
        reasons = notes + reasons if status == "needs_review" else []
        eligible = [s for s in students if is_eligible(s, criteria)] if status == "matched" else []
        results.append({**job, "criteria": criteria, "status": status,
                        "reasons": reasons, "eligible": eligible})
        print(f"   -> {status}, {len(eligible)} eligible" if status == "matched"
              else f"   -> needs_review ({'; '.join(reasons)})")

    write_reports(results, students, OUTPUT_DIR)
    print(f"\nDone. Draft files written to '{OUTPUT_DIR}/'. Placement officer must check them.")


if __name__ == "__main__":
    main()