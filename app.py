# app.py
import os
from flask import Flask, render_template, request, redirect, url_for, flash
from werkzeug.utils import secure_filename
from resume_processing import process_all_resumes, fetch_shortlisted_from_bq
from google.cloud import storage
from dotenv import load_dotenv

load_dotenv()

UPLOAD_TEMP_DIR = os.getenv("UPLOAD_TEMP_DIR", "/tmp/resume_uploads")
os.makedirs(UPLOAD_TEMP_DIR, exist_ok=True)

BUCKET_NAME = "hr_ats_voicebot"
FOLDER_ALL = "resumes-all"

ALLOWED_EXTENSIONS = {"pdf"}

app = Flask(__name__)
app.secret_key = os.getenv("FLASK_SECRET_KEY", "devsecretkey")

storage_client = storage.Client(project=os.getenv("GCP_PROJECT_ID"))


def allowed_file(name):
    return "." in name and name.rsplit(".", 1)[1].lower() == "pdf"


def upload_file_to_gcs(local_path, bucket_name, dest_name):
    bucket = storage_client.bucket(bucket_name)
    blob = bucket.blob(dest_name)
    blob.upload_from_filename(local_path)
    return blob.name


@app.route("/", methods=["GET", "POST"])
def index():
    if request.method == "POST":
        files = request.files.getlist("resumes")
        send_email_flag = True

        if not files:
            flash("Select a PDF.", "warning")
            return redirect("/")

        uploaded_blob_names = []

        for f in files:
            if f and allowed_file(f.filename):
                filename = secure_filename(f.filename)
                path = os.path.join(UPLOAD_TEMP_DIR, filename)
                f.save(path)

                blob_name = upload_file_to_gcs(
                    path,
                    BUCKET_NAME,
                    f"{FOLDER_ALL}/{filename}"
                )
                uploaded_blob_names.append(blob_name)

        if not uploaded_blob_names:
            flash("No valid PDFs uploaded.", "danger")
            return redirect("/")

        # PROCESS + EMAIL + AUTO-BATCH
        process_all_resumes(
            process_all_in_bucket=False,
            specific_blob_names=uploaded_blob_names,
            send_email=send_email_flag
        )

        flash(
            f"Processed {len(uploaded_blob_names)} resumes. Emails sent to shortlisted candidates.",
            "success"
        )
        return redirect(url_for("shortlisted"))

    return render_template("index.html")


@app.route("/shortlisted")
def shortlisted():
    rows = fetch_shortlisted_from_bq(limit=200)
    return render_template("shortlisted.html", candidates=rows)


if __name__ == "__main__":
    app.run(debug=True, host="0.0.0.0", port=int(os.getenv("PORT", 5000)))
