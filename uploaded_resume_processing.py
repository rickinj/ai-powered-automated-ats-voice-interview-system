# uploaded_resume_processing.py
import os
import uuid
import re
import json
from dotenv import load_dotenv
from google.cloud import storage, bigquery
from google import genai
from google.genai import types
import pandas as pd
import logging
import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart

import time
import random

def retry_with_backoff(func, max_retries=5, base_delay=2):
    for attempt in range(1, max_retries + 1):
        try:
            return func()
        except Exception as e:
            error_message = str(e).lower()

            # retry only if resource issue
            if ("resource" in error_message or 
                "quota" in error_message or 
                "exhaust" in error_message or 
                "rate" in error_message or 
                "limit" in error_message):

                wait = base_delay * attempt + random.uniform(0, 1)
                logging.warning(f"⚠️ Resource issue on attempt {attempt}. Retrying in {wait:.2f}s...")
                time.sleep(wait)
                continue

            # Any other error = break
            raise e

    raise Exception("❌ Max retries reached — still failing.")


# Configure logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

# =============================================================================
# 1. SETUP AND CONFIGURATION (UPDATED)
# =============================================================================

# Load environment variables from .env file
load_dotenv()

# --- Configuration Variables ---
PROJECT_ID = os.getenv("GCP_PROJECT_ID")
#GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")

BUCKET_NAME = os.getenv("GCS_BUCKET_NAME", "hr_ats_voicebot") # main bucket name
RESUMES_ALL_PREFIX = os.getenv("RESUMES_ALL_PREFIX", "resumes-all/") # folder containing all resumes
RESUMES_SHORTLISTED_PREFIX = os.getenv("RESUMES_SHORTLISTED_PREFIX", "resumes-shortlisted/") # folder where shortlisted resumes get uploaded

BQ_DATASET_ID = os.getenv("BQ_DATASET_ID", "hr_resume_transcript") 
BQ_TABLE_ID = os.getenv("BQ_TABLE_ID", "shortlisted_resume")
FULL_TABLE_ID = f"{PROJECT_ID}.{BQ_DATASET_ID}.{BQ_TABLE_ID}"

# --- NEW EMAIL/COMPANY CONFIGURATION ---
SENDER_EMAIL = os.getenv("SENDER_EMAIL", "recruitment@default.com")
COMPANY_NAME = os.getenv("COMPANY_NAME", "{COMPANY}")

JD_FILE_PATH = "machine_learning_jd.txt"
ONLINE_INTERVIEW_LINK = "your interview link - project link should come after hosting project on GCS or any other cloud service"


try:
    GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")

    # ❌ DO NOT USE API KEY WITH google.genai (Google Cloud Gemini)
    # Force Vertex AI usage (service account)
    gemini_client = genai.Client(
        vertexai=True,
        project=PROJECT_ID,
        location="us-central1"
    )
    logging.info("✅ Gemini client initialized using Vertex AI service account.")

    storage_client = storage.Client(project=PROJECT_ID)
    bq_client = bigquery.Client(project=PROJECT_ID)
    logging.info("✅ Google Cloud clients initialized successfully.")

except Exception as e:
    logging.error(f"🚨 Failed to initialize clients: {e}")
    exit(1)



# =============================================================================
# 2. JOB DESCRIPTION & ATS SCORING LOGIC
# =============================================================================

def load_and_analyze_jd(jd_file_path):
    try:
        with open(jd_file_path, 'r', encoding='utf-8') as f:
            jd_content = f.read().lower()
    except FileNotFoundError:
        logging.error(f"JD file not found at: {jd_file_path}")
        return None, {}

    keywords = {
        "skills": [
            "python", "sql", "sklearn", "pandas", "numpy",
            "tensorflow", "pytorch", "docker", "git", "ci/cd",
            "mlflow", "kubeflow", "gcp", "bigquery", "machine learning"
        ],
        "experience": [
            "deployed", "production", "pipeline", "monitoring", "drift",
            "scalable", "high-volume", "api", "rest"
        ],
        "projects": [
            "classification", "regression", "nlp", "cv", "computer vision",
            "measurable impact", "model training", "deep learning"
        ],
        "education": [
            "cs", "computer science", "engineering", "statistics", "related field"
        ],
        "soft_indicators": [
            "collaboration", "timeline", "cross-functional", "leadership", "communication"
        ]
    }
    return jd_content, keywords


def calculate_ats_score(resume_text, jd_keywords):
    text = resume_text.lower()
    total_score = 0
    weights = {
        "skills": 0.60,
        "experience": 0.15,
        "projects": 0.15,
        "education": 0.05,
        "soft_indicators": 0.05
    }

    for category, keywords in jd_keywords.items():
        category_score = sum(1 for keyword in keywords if keyword in text)
        max_category_score = len(keywords) if keywords else 1
        normalized_score = min(category_score / max_category_score, 1.0)
        weighted_score = normalized_score * weights[category]
        total_score += weighted_score

    final_ats_score = round(total_score * 100, 2)
    return final_ats_score

# =============================================================================
# 3. GEMINI PARSING AND EXTRACTION
# =============================================================================

def parse_pdf_with_gemini(blob_path, gcs_client, bucket_name):

    def run():
        bucket = gcs_client.bucket(bucket_name)
        blob = bucket.blob(blob_path)
        pdf_bytes = blob.download_as_bytes()
        pdf_part = types.Part.from_bytes(data=pdf_bytes, mime_type='application/pdf')

        prompt = "Extract the entire content of this resume into plain text only."

        response = gemini_client.models.generate_content(
            model='gemini-2.5-flash',
            contents=[pdf_part, prompt]
        )
        return response.text

    return retry_with_backoff(run)



def extract_structured_data_with_gemini(resume_text):

    def run():
        extraction_prompt = f"""
Extract the candidate details from the resume.

Return JSON ONLY with these exact keys:
- name
- phone_number
- email

Rules:
- Do NOT add comments.
- Do NOT add extra fields.
- If the value does not exist, return an empty string.
- Be strict: name must be a proper human name (not job titles).

RESUME TEXT:
{resume_text}
"""

        response = gemini_client.models.generate_content(
            model="gemini-2.5-flash",
            contents=[extraction_prompt],
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




# =============================================================================
# 4. BIGQUERY LOAD AND EMAIL PREPARATION (UPDATED)
# =============================================================================

def load_to_bigquery(data):
    if not data:
        logging.info("No data to load to BigQuery.")
        return

    # ✅ Keep only shortlisted candidates
    shortlisted_data = [d for d in data if d.get("shortlisted") == "YES"]

    if not shortlisted_data:
        logging.info("No shortlisted candidates to load to BigQuery.")
        return

    df = pd.DataFrame(shortlisted_data)
    df['candidate_id'] = df['candidate_id'].astype('Int64')
    df['ats_score'] = df['ats_score'].astype('float64')

    # Optional: Clean up email formatting
    df['email'] = df['email'].str.strip().str.lower()

    job_config = bigquery.LoadJobConfig(write_disposition=bigquery.WriteDisposition.WRITE_APPEND)

    try:
        logging.info(f"Loading {len(df)} shortlisted candidates to {FULL_TABLE_ID}...")
        job = bq_client.load_table_from_dataframe(df, FULL_TABLE_ID, job_config=job_config)
        job.result()
        logging.info("✅ BigQuery load successful (only shortlisted resumes).")
    except Exception as e:
        logging.error(f"🚨 BigQuery load failed: {e}")




def send_email_via_gmail(to_email, subject, body):
    sender_email = os.getenv("SENDER_EMAIL")
    sender_password = os.getenv("SENDER_APP_PASSWORD")

    if not sender_email or not sender_password:
        logging.error("Missing SENDER_EMAIL or SENDER_APP_PASSWORD in .env file.")
        return

    msg = MIMEMultipart()
    msg["From"] = sender_email
    msg["To"] = to_email
    msg["Subject"] = subject
    msg.attach(MIMEText(body, "plain"))

    try:
        with smtplib.SMTP("smtp.gmail.com", 587) as server:
            server.starttls()
            server.login(sender_email, sender_password)
            server.send_message(msg)
        logging.info(f"✅ Email sent successfully to {to_email}")
    except Exception as e:
        logging.error(f"❌ Failed to send email to {to_email}: {e}")


def prepare_email_data(all_candidate_data):
    shortlisted_candidates = [
        c for c in all_candidate_data if c['shortlisted'] == 'YES' and c.get('email')
    ]

    logging.info(f"\nPreparing emails for {len(shortlisted_candidates)} shortlisted candidates...")

    for candidate in shortlisted_candidates:
        candidate_id = candidate.get('candidate_id', 'N/A')
        first_name = candidate['name'].split(' ')[0].strip() if candidate['name'] else "Candidate"

        email_body = f"""
Hi {first_name},

Congratulations! Based on the evaluation of your resume, we are pleased to inform you that you have been shortlisted for the position of Machine Learning Engineer at {COMPANY_NAME}.

------------------------------------------------------------
Candidate Details
------------------------------------------------------------
Candidate ID: {candidate_id}
Position: Machine Learning Engineer

------------------------------------------------------------
Next Step: Round 1 – Automated Voice Interview
------------------------------------------------------------
Please complete your first interview round using the link below:

Interview Link: {ONLINE_INTERVIEW_LINK}

This is an automated voice-based interview designed to assess your technical and communication skills. 
Kindly ensure:
• A quiet environment  
• Stable internet connection  
• Your microphone is working properly  

------------------------------------------------------------
If you have any questions, feel free to reply to this email.
------------------------------------------------------------

Best regards,
{COMPANY_NAME} Recruitment Team
"""



        send_email_via_gmail(
            candidate['email'],
            "Interview Invitation – Machine Learning Engineer",
            email_body
        )


# =============================================================================
# 5. ORCHESTRATION FUNCTION
# =============================================================================

def process_all_resumes(send_email=False):
    jd_content, jd_keywords = load_and_analyze_jd(JD_FILE_PATH)
    if not jd_content:
        logging.error("JD content not loaded. Stopping.")
        return

    bucket = storage_client.bucket(BUCKET_NAME)

    # ✅ Fetch resumes from resumes-all folder (not shortlisted)
    all_resumes_blobs = bucket.list_blobs(prefix=RESUMES_ALL_PREFIX)

    all_candidate_data = []
    start_id = 100

    for i, blob in enumerate(all_resumes_blobs, start=start_id):
        if not blob.name.lower().endswith('.pdf'):
            continue

        logging.info(f"Processing resume: {blob.name}")

        try:
            resume_transcript = parse_pdf_with_gemini(blob.name, storage_client, BUCKET_NAME)
            extracted_data = extract_structured_data_with_gemini(resume_transcript)
            name = extracted_data.get('name', 'N/A')
            email = extracted_data.get('email', '')
            phone_number = extracted_data.get('phone_number', '')

            ats_score = calculate_ats_score(resume_transcript, jd_keywords)
            logging.info(f"Candidate: {name}, ATS Score: {ats_score}")

            is_contact_present = bool(email or phone_number)
            is_shortlisted = (ats_score >= 60) and is_contact_present
            shortlisted_status = "YES" if is_shortlisted else "NO"

            if is_shortlisted:
                source_blob = bucket.blob(blob.name)
                new_blob_name = f"{RESUMES_SHORTLISTED_PREFIX}{blob.name.split('/')[-1]}"
                bucket.copy_blob(source_blob, bucket, new_blob_name)
                logging.info(f"Shortlisted: YES. Copied to {new_blob_name}")

            candidate_id = i  # Sequential ID (100, 101, 102...)

            all_candidate_data.append({
                "candidate_id": candidate_id,
                "name": name,
                "phone_number": phone_number,
                "email": email,
                "resume_text": resume_transcript,
                "ats_score": ats_score,
                "shortlisted": shortlisted_status
            })

        except Exception as e:
            logging.error(f"Error processing {blob.name}: {e}")
            continue

    load_to_bigquery(all_candidate_data)

    if send_email:
        prepare_email_data(all_candidate_data)
    else:
        logging.info("Email sending skipped by user choice.")

    logging.info("\n*** ATS Process Complete. ***")


# =============================================================================
# EXECUTION
# =============================================================================

if __name__ == "__main__":
    user_choice = input("Do you want to send emails to shortlisted candidates? (yes/no): ").strip().lower()
    if user_choice == 'yes':
        process_all_resumes(send_email=True)
    else:
        logging.info("Process terminated. Emails not sent.")
