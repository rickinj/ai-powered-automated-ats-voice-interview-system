# interview.py
from flask import Flask, render_template, request, redirect, url_for, session, jsonify
from google.cloud import bigquery, texttospeech
from vertexai.preview.generative_models import GenerativeModel, Part
from dotenv import load_dotenv
from concurrent.futures import ThreadPoolExecutor
import vertexai, json, os, base64, uuid

# --- FLASK APP CONFIG ---
app = Flask(__name__)
app.secret_key = "super_secret_key"

# Store sessions on filesystem (prevents cookie overflow)
app.config["SESSION_TYPE"] = "filesystem"
app.config["SESSION_PERMANENT"] = False

# --- LOAD ENV ---
load_dotenv()
GCP_PROJECT_ID = os.getenv("GCP_PROJECT_ID")
BQ_DATASET_ID = os.getenv("BQ_DATASET_ID")

vertexai.init(project=GCP_PROJECT_ID, location="us-central1")
GEMINI = GenerativeModel("gemini-2.5-flash")
bq_client = bigquery.Client(project=GCP_PROJECT_ID)
tts_client = texttospeech.TextToSpeechClient()

SHORTLIST_TABLE = f"{GCP_PROJECT_ID}.{BQ_DATASET_ID}.shortlisted_resume" # shortlisted_resume is the table name containing resumes that are shortlisted
RESULTS_TABLE = f"{GCP_PROJECT_ID}.{BQ_DATASET_ID}.interview_results" # contains the results of the interview processed by Gemini

executor = ThreadPoolExecutor(max_workers=3)


# ===============================================
# AUTHENTICATE CANDIDATE
# ===============================================
def authenticate_candidate(candidate_id):
    query = f"""
        SELECT candidate_id, name, email, phone_number, resume_text
        FROM `{SHORTLIST_TABLE}`
        WHERE candidate_id = @id
    """

    job_config = bigquery.QueryJobConfig(
        query_parameters=[bigquery.ScalarQueryParameter("id", "INT64", int(candidate_id))]
    )

    try:
        rows = list(bq_client.query(query, job_config=job_config))
        if rows:
            row = rows[0]
            return {
                "candidate_id": row["candidate_id"],
                "name": row["name"],
                "email": row["email"],
                "phone_number": row["phone_number"],
                "resume_text": row["resume_text"]
            }
    except Exception as e:
        print(f"BigQuery Error: {e}")

    return None

def check_duplicate_interview(candidate_id):
    """Checks if a candidate_id already exists in the interview_results table."""
    query = f"""
        SELECT candidate_id
        FROM `{RESULTS_TABLE}`
        WHERE candidate_id = @id
        LIMIT 1
    """

    job_config = bigquery.QueryJobConfig(
        query_parameters=[
            bigquery.ScalarQueryParameter("id", "INT64", int(candidate_id))
        ]
    )

    try:
        rows = list(bq_client.query(query, job_config=job_config))
        return len(rows) > 0
    except Exception as e:
        print(f"BigQuery Error checking duplicates: {e}")
        return False


# ===============================================
# GENERATE QUESTIONS
# ===============================================
def generate_questions(name, resume_context):
    prompt = f"""
    You are a recruiter. Generate 10 interview questions for {name}:
    - 5 from resume context: {resume_context}
    - 5 from Machine Learning concepts
    Return ONLY JSON list of strings.
    """

    res = GEMINI.generate_content(prompt)
    cleaned = res.text.strip().replace("```json", "").replace("```", "")
    return json.loads(cleaned)


# ===============================================
# TTS
# ===============================================
def text_to_speech(text):
    input_text = texttospeech.SynthesisInput(text=text)

    voice = texttospeech.VoiceSelectionParams(
        language_code="en-IN",
        name="en-IN-Wavenet-B"
    )

    audio_config = texttospeech.AudioConfig(
        audio_encoding=texttospeech.AudioEncoding.MP3
    )

    response = tts_client.synthesize_speech(
        input=input_text, voice=voice, audio_config=audio_config
    )

    return base64.b64encode(response.audio_content).decode("utf-8")


# ===============================================
# ASYNC AUDIO PROCESSOR
# ===============================================
def process_audio_async(filename, candidate_info, question, transcript_index):
    try:
        with open(filename, "rb") as f:
            audio_bytes = f.read()

        audio_part = Part.from_data(data=audio_bytes, mime_type="audio/webm")

        prompt = "Please provide a clean, accurate transcription of the following audio. Only provide the transcribed text."

        response = GEMINI.generate_content([prompt, audio_part])
        raw_transcript = response.text.strip() if hasattr(response, "text") else "[No speech detected]"

        print(f"✅ [Async] Gemini transcript {transcript_index + 1}: {raw_transcript[:150]}...")

        qa_entry = (
            f"Question{transcript_index + 1}: {question}\n"
            f"Answer{transcript_index + 1}: {raw_transcript}\n\n"
        )

        os.makedirs("answers_cleaned", exist_ok=True)
        path = f"answers_cleaned/{candidate_info.get('candidate_id')}.txt"

        if os.path.exists(path):
            with open(path, "r", encoding="utf-8") as f:
                content = f.read()
        else:
            content = ""

        if f"Question{transcript_index + 1}:" not in content:
            with open(path, "a", encoding="utf-8") as f:
                f.write(qa_entry)
            print("💾 Saved")
        else:
            print("⚠️ Skipped duplicate")

    except Exception as e:
        print(f"⚠️ [Async] Error in processing audio: {e}")


# ===============================================
# GEMINI EVALUATION
# ===============================================
def evaluate_answers_with_gemini(full_transcript):

    scoring_prompt = f"""
You are an AI Interview Evaluator.

FULL TRANSCRIPT:
{full_transcript}

TASK:
1. Score each of the 10 answers (1–10)
2. Give 1–2 lines of reasoning per answer
3. Provide an average score
4. Provide a final summary paragraph

Return JSON:
{{
  "results": [
    {{"question": 1, "score": 8, "reason": "Good answer"}},
    {{"question": 2, "score": 5, "reason": "Weak detail"}}
  ],
  "average_score": 6.5,
  "summary": "Good conceptual knowledge but lacks examples."
}}
"""

    response = GEMINI.generate_content(scoring_prompt)
    cleaned = response.text.strip().replace("```json", "").replace("```", "")

    data = json.loads(cleaned)
    return data["results"], data["average_score"], data["summary"]


# ===============================================
# FLASK ROUTES
# ===============================================

@app.route("/", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        candidate_id = request.form.get("candidate_id")
        if check_duplicate_interview(candidate_id):
            return render_template("login.html", error="Error: This Candidate ID has already completed the interview.")
        
        info = authenticate_candidate(candidate_id)

        if info:
            session["candidate_info"] = dict(info)
            session["questions"] = generate_questions(info["name"], info["resume_text"])
            session["index"] = 0
            session["transcript"] = []
            return redirect(url_for("interview"))

        return render_template("login.html", error="Invalid Candidate ID")

    return render_template("login.html")


@app.route("/interview")
def interview():
    if "questions" not in session:
        return redirect(url_for("login"))

    idx = session["index"]
    total = len(session["questions"])

    if idx >= total:
        return redirect(url_for("processing"))

    q = session["questions"][idx]
    audio = text_to_speech(q)

    return render_template(
        "interview.html",
        question=q,
        audio_data=audio,
        q_number=idx + 1,
        total=total
    )

@app.route("/processing")
def processing():
    if session.get("index", 0) < len(session.get("questions", [])):
        return redirect(url_for("interview")) # Safety check

    # This page will show the loading bar while the backend finishes transcription and evaluation.
    return render_template("processing.html")

@app.route("/submit_answer", methods=["POST"])
def submit_answer():
    from flask.sessions import SecureCookieSessionInterface
    import copy

    if "audio_data" in request.files:
        audio_file = request.files["audio_data"]
        audio_bytes = audio_file.read()

        filename = f"answers/{uuid.uuid4()}.webm"
        os.makedirs("answers", exist_ok=True)

        with open(filename, "wb") as f:
            f.write(audio_bytes)

        idx = session["index"]
        question = session["questions"][idx]
        candidate_info = copy.deepcopy(session["candidate_info"])

        session["transcript"].append({"question": question, "answer": "[Processing...]"})
        session["index"] += 1
        session.modified = True

        # Save session before async
        session_interface = SecureCookieSessionInterface()
        response = jsonify({"next_url": url_for("interview")})
        session_interface.save_session(app, session, response)

        executor.submit(process_audio_async, filename, candidate_info, question, idx)
        return response

    # No audio (text answer fallback)
    data = request.get_json()
    answer = data.get("answer_text", "[no answer]")

    idx = session["index"]
    question = session["questions"][idx]

    session["transcript"].append({"question": question, "answer": answer})
    session["index"] += 1
    session.modified = True

    return jsonify({"next_url": url_for("interview")})


@app.route("/results")
def results():
    import time

    info = session.get("candidate_info")
    transcript = session.get("transcript")

    if not info or not transcript:
        return redirect(url_for("login"))

    candidate_id = info["candidate_id"]
    filepath = f"answers_cleaned/{candidate_id}.txt"

    # Wait for all answers (max 15 sec)
    for _ in range(15):
        if os.path.exists(filepath):
            with open(filepath, "r", encoding="utf-8") as f:
                content = f.read()

            if content.count("Question") >= 10:
                break
        time.sleep(1)

    # Read transcript
    if os.path.exists(filepath):
        with open(filepath, "r", encoding="utf-8") as f:
            final_text = f.read()
    else:
        final_text = "Transcription incomplete."

    # Evaluate with Gemini
    try:
        qscores, avg, summary = evaluate_answers_with_gemini(final_text)
        final_score = float(avg)
        feedback = summary

        print("\n📊 FINAL INTERVIEW SUMMARY")
        print("Score:", final_score)
        print("Summary:", summary)

    except Exception as e:
        print("Gemini scoring failed:", e)
        final_score = 0.0
        feedback = "Evaluation error."
        summary = "Evaluation error."

    # Insert into BigQuery
    try:
        row = {
            "candidate_id": int(candidate_id),
            "name": info["name"],
            "email": info["email"],
            "phone_number": info["phone_number"],
            "full_transcript": final_text,
            "final_score": final_score,
            "summarised_feedback": summary
        }

        errors = bq_client.insert_rows_json(RESULTS_TABLE, [row])
        if not errors:
            print("Saved to BigQuery.")
        else:
            print("BQ errors:", errors)

    except Exception as e:
        print("BQ Insert Error:", e)

    return render_template(
        "result.html",
        name=info["name"],
        transcript=transcript,
        summary=summary,
        feedback=feedback,
        score=final_score
    )


if __name__ == "__main__":
    app.run(debug=True, use_reloader=False)
