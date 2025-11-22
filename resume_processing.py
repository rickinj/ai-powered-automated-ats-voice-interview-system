# resume_processing.py
import os
import uuid
import re
import json
import logging
import time
import random
from dotenv import load_dotenv
from google.cloud import storage, bigquery
from google import genai
from google.genai import types
import pandas as pd
import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

load_dotenv()

PROJECT_ID = os.getenv("GCP_PROJECT_ID")

BUCKET_NAME = os.getenv("GCS_BUCKET_NAME", "hr_ats_voicebot")
FOLDER_ALL = "resumes-all"
FOLDER_SHORT = "resumes-shortlisted"

BQ_DATASET_ID = os.getenv("BQ_DATASET_ID", "hr_resume_transcript")
BQ_TABLE_ID = os.getenv("BQ_TABLE_ID", "shortlisted_resume")
FULL_TABLE_ID = f"{PROJECT_ID}.{BQ_DATASET_ID}.{BQ_TABLE_ID}"

JD_FILE_PATH = "machine_learning_jd.txt"
ONLINE_INTERVIEW_LINK = os.getenv("ONLINE_INTERVIEW_LINK")
COMPANY_NAME = os.getenv("COMPANY_NAME", "{COMPANY}")
SENDER_EMAIL = os.getenv("SENDER_EMAIL")
SENDER_APP_PASSWORD = os.getenv("SENDER_APP_PASSWORD")

try:
    gemini_client = genai.Client(
        vertexai=True,
        project=PROJECT_ID,
        location="us-central1"
    )
    storage_client = storage.Client(project=PROJECT_ID)
    bq_client = bigquery.Client(project=PROJECT_ID)
    logging.info("Cloud clients initialized.")
except Exception as e:
    logging.error(f"Client init failed: {e}")
    raise


def retry_with_backoff(func, max_retries=5, base_delay=2):
    for attempt in range(1, max_retries + 1):
        try:
            return func()
        except Exception as e:
            txt = str(e).lower()
            if any(key in txt for key in ["resource", "quota", "rate", "limit"]):
                wait = base_delay * attempt + random.uniform(0, 1)
                time.sleep(wait)
                continue
            raise
    raise Exception("Max retries reached")


def load_and_analyze_jd(jd_file_path=JD_FILE_PATH):
    try:
        with open(jd_file_path, "r", encoding="utf-8") as f:
            jd_text = f.read().lower()
    except:
        jd_text = ""

    keywords = {
        "skills": [
            "python", "sql", "sklearn", "pandas", "numpy",
            "tensorflow", "pytorch", "docker", "git", "ci/cd",
            "mlflow", "kubeflow", "gcp", "bigquery", "machine learning"
        ],
        "experience": [
            "deployed", "production", "pipeline", "monitoring",
            "drift", "scalable", "api", "rest"
        ],
        "projects": [
            "classification", "regression", "nlp", "cv",
            "computer vision", "deep learning"
        ],
        "education": ["cs", "computer science", "engineering", "statistics"],
        "soft_indicators": ["collaboration", "timeline", "leadership"]
    }
    return jd_text, keywords


def calculate_ats_score(text, keywords):
    text = (text or "").lower()
    score = 0
    weights = {
        "skills": 0.60,
        "experience": 0.15,
        "projects": 0.15,
        "education": 0.05,
        "soft_indicators": 0.05
    }

    for cat, keys in keywords.items():
        hit = sum(1 for k in keys if k in text)
        max_sc = len(keys) or 1
        score += (hit / max_sc) * weights.get(cat, 0)

    return round(score * 100, 2)


def parse_pdf_with_gemini(blob_path):
    def run():
        bucket = storage_client.bucket(BUCKET_NAME)
        blob = bucket.blob(blob_path)
        pdf_bytes = blob.download_as_bytes()
        pdf_part = types.Part.from_bytes(data=pdf_bytes, mime_type="application/pdf")

        response = gemini_client.models.generate_content(
            model="gemini-2.5-flash",
            contents=[pdf_part, "Extract the full resume text only."]
        )
        return response.text

    return retry_with_backoff(run)


def extract_structured_data_with_gemini(text):
    def run():
        prompt = f"""
Extract the candidate details.

Return ONLY JSON:
- name
- phone_number
- email

If not available return empty string.
Resume:
{text}
"""
        response = gemini_client.models.generate_content(
            model="gemini-2.5-flash",
            contents=[prompt],
            config=types.GenerateContentConfig(
                response_mime_type="application/json",
                response_schema={
                    "type": "object",
                    "properties": {
                        "name": {"type": "string"},
                        "phone_number": {"type": "string"},
                        "email": {"type": "string"}
                    },
                    "required": ["name", "phone_number", "email"]
                }
            )
        )
        return json.loads(response.text)

    return retry_with_backoff(run)


def load_to_bigquery(rows):
    if not rows:
        return

    df = pd.DataFrame(rows)
    df["candidate_id"] = df["candidate_id"].astype("Int64")
    df["ats_score"] = pd.to_numeric(df["ats_score"], errors="coerce").fillna(0)

    cfg = bigquery.LoadJobConfig(write_disposition="WRITE_APPEND")

    try:
        job = bq_client.load_table_from_dataframe(df, FULL_TABLE_ID, job_config=cfg)
        job.result()
    except Exception as e:
        logging.error(f"BQ load failed: {e}")


def send_email_via_gmail(to_email, subject, body):
    if not SENDER_EMAIL or not SENDER_APP_PASSWORD:
        return

    msg = MIMEMultipart()
    msg["From"] = SENDER_EMAIL
    msg["To"] = to_email
    msg["Subject"] = subject
    msg.attach(MIMEText(body, "plain"))

    try:
        with smtplib.SMTP("smtp.gmail.com", 587) as server:
            server.starttls()
            server.login(SENDER_EMAIL, SENDER_APP_PASSWORD)
            server.send_message(msg)
    except:
        pass


def prepare_email_data(all_candidate_data):
    shortlisted = [
        c for c in all_candidate_data
        if c.get("shortlisted") == "YES"
        and c.get("email")
        and "@" in c["email"]
    ]

    for candidate in shortlisted:
        name = candidate.get("name", "").split(" ")[0] or "Candidate"
        cid = candidate.get("candidate_id", "")
        body = f"""
Hi {name},

You have been shortlisted for the Machine Learning Engineer role at {COMPANY_NAME}.

Candidate ID: {cid}

Please complete your voice interview:
{ONLINE_INTERVIEW_LINK}

Best regards,
{COMPANY_NAME} Recruitment Team
"""
        send_email_via_gmail(
            candidate["email"],
            "Interview Invitation - Machine Learning Engineer",
            body
        )


def process_all_resumes(process_all_in_bucket=True, specific_blob_names=None, send_email=False):
    jd_text, jd_keywords = load_and_analyze_jd()

    bucket = storage_client.bucket(BUCKET_NAME)

    blob_names = []
    if process_all_in_bucket:
        for blob in bucket.list_blobs(prefix=FOLDER_ALL + "/"):
            if blob.name.lower().endswith(".pdf"):
                blob_names.append(blob.name)
    else:
        blob_names = specific_blob_names

    if not blob_names:
        return

    # NEW BATCH
    batch_id = int(time.time())
    results = []
    base_id = 100

    for i, blob_name in enumerate(blob_names):
        cid = base_id + i

        try:
            text = parse_pdf_with_gemini(blob_name)
            extracted = extract_structured_data_with_gemini(text)
            ats = calculate_ats_score(text, jd_keywords)

            is_short = ats >= 60 and (
                extracted.get("email") or extracted.get("phone_number")
            )
            status = "YES" if is_short else "NO"

            if is_short:
                src = bucket.blob(blob_name)
                dst = bucket.blob(f"{FOLDER_SHORT}/{os.path.basename(blob_name)}")
                bucket.copy_blob(src, bucket, dst.name)

            results.append({
                "candidate_id": cid,
                "name": extracted.get("name", ""),
                "phone_number": extracted.get("phone_number", ""),
                "email": extracted.get("email", ""),
                "resume_text": text,
                "ats_score": ats,
                "shortlisted": status,
                "batch_id": batch_id
            })

        except Exception as e:
            results.append({
                "candidate_id": cid,
                "name": "",
                "phone_number": "",
                "email": "",
                "resume_text": str(e),
                "ats_score": 0,
                "shortlisted": "NO",
                "batch_id": batch_id
            })

    load_to_bigquery(results)

    if send_email:
        prepare_email_data(results)


def fetch_shortlisted_from_bq(limit=200):
    sql = f"""
    WITH latest AS (
        SELECT MAX(batch_id) AS batch_id
        FROM `{FULL_TABLE_ID}`
    )
    SELECT name, candidate_id, ats_score
    FROM `{FULL_TABLE_ID}`
    WHERE LOWER(shortlisted) = 'yes'
    AND batch_id = (SELECT batch_id FROM latest)
    ORDER BY ats_score DESC
    LIMIT @limit
    """

    cfg = bigquery.QueryJobConfig(
        query_parameters=[bigquery.ScalarQueryParameter("limit", "INT64", limit)]
    )

    try:
        rows = bq_client.query(sql, cfg).result()
        return [
            {"name": r.name, "candidate_id": r.candidate_id, "ats_score": float(r.ats_score)}
            for r in rows
        ]
    except:
        return []
