# 🤖 AI-Powered ATS + Voice Interview System  
A complete end-to-end HR automation workflow built using:

- **Flask**
- **Google Cloud Storage (GCS)**
- **BigQuery**
- **Vertex AI Gemini 2.5 Flash**
- **Google Text-to-Speech**

This project consists of **two major modules**:

1. **Resume Processing ATS Engine** (runs locally or manually)
2. **AI Voice Interview System** (fully deployed)

Only the *AI Interview Module* is hosted in production. (The interview.py module can be run locally as well). <br> 
The ATS/Resume module is kept for internal/local use.

---

# 📌 Project Overview

## **1. Resume ATS Processing (Local Use Only)**  
The resume processing pipeline:

- Reads resumes from:
  - **Uploaded PDFs via app.py**, or
  - **Existing PDFs in GCS bucket via uploaded_resume_processing.py**
- Extracts structured data (name, email, phone)
- Computes ATS score based on ML Job Description
- Shortlists candidates with ATS ≥ 60
- Stores shortlisted results in **BigQuery**
- Copies shortlisted PDFs into a separate GCS folder
- Sends interview email with a unique **Candidate ID**

**This part is *not* hosted**, but is used by HR to prepare candidates for the voice interview.

---

## **2. AI Voice Interview System (Hosted)**  
This is the deployed module:

- Candidate enters **Candidate ID**
- System fetches the resume record from BigQuery
- Generates 10 interview questions:
  - 5 based on candidate resume
  - 5 based on ML concepts
- Uses Google TTS to speak the questions
- Candidate responds via microphone
- Audio is recorded & transcribed using **Gemini 2.5 Flash**
- At the end, Gemini evaluates:
  - Each answer (score + reasoning)
  - Final average score
  - Summary feedback
- Results are stored in **BigQuery**

---

# 🧭 Architecture

                    ┌────────────────────────┐
                    │    Resume PDFs (.pdf)  │
                    └─────────────┬──────────┘
                                  │
                    ┌─────────────▼─────────────┐
                    │  Resume Processing Module  │
                    │  (local use only)          │
                    └───────┬─────────┬─────────┘
                            │         │
               ┌────────────▼─┐   ┌───▼──────────────────┐
               │ BigQuery ATS │   │ Shortlisted GCS PDFs  │
               │   Table      │   └────────────────────────┘
               └───────┬─────┘
                       │ Candidate ID
                       ▼
             ┌────────────────────────┐
             │ AI Voice Interview App │   (Hosted)
             └───────────┬────────────┘
                         │
                   Gemini + TTS
                         │
                    Final Score
                         ▼
             ┌────────────────────────┐
             │  interview_results BQ  │
             └────────────────────────┘


---

# 🔐 Environment Setup (Important)

This project requires two sensitive credentials:

✔ `GOOGLE_APPLICATION_CREDENTIALS`  
✔ `SENDER_APP_PASSWORD`  

Because these contain confidential information, **do NOT upload them to GitHub**.  
Each contributor must create their own credentials by following the steps below.

# 1️⃣ Generate `GOOGLE_APPLICATION_CREDENTIALS`

This is the path to your **Google Cloud Service Account JSON key**, used for BigQuery and Google Cloud authentication.

### **Steps**

1. Go to **Google Cloud Console**  
   https://console.cloud.google.com/

2. Select your project 

3. Open the sidebar → **IAM & Admin → Service Accounts**

4. Click **Create Service Account**

5. Enter a name, e.g.:

6. Click **Create and Continue**

7. Assign these roles:

- **BigQuery Data Viewer**  
- **BigQuery Data Editor**  
- **BigQuery Job User**

8. Click **Continue → Done**

9. Open the created account → go to the **Keys** tab

10. Click **Add Key → Create New Key**

11. Choose **JSON**, then download the file.

12. Place it inside your project.

13. Add this into your `.env`: GOOGLE_APPLICATION_CREDENTIALS=path/to/service_account.json

# 2️⃣ Generate `SENDER_APP_PASSWORD` (Gmail App Password)

This password is required for sending OTP emails from your Gmail account.

### **Steps**

1. Open your Google Security settings:  
https://myaccount.google.com/security

2. Under **Signing in to Google**, enable:
- **2-Step Verification**

3. After that, open App Passwords:  
https://myaccount.google.com/apppasswords

4. Choose:
- **App:** Mail  
- **Device:** Your device (e.g., Windows Computer)

5. Click **Generate**

6. Copy the 16-character password (Google shows it once)

7. Add it to your `.env`: SENDER_APP_PASSWORD=your_generated_app_password.

8. **Never commit this password to GitHub.**

---

# 🛠️ Folder Structure

```

project/
│
├── app.py # Resume uploader (local use)
├── interview.py # Hosted voice interview system
│
├── answers # audio file gets auto created after processing speech for answer to the interview question
├── answers_cleaned # creates a .txt file of the transcript of the entire interview
│
├── resume_processing.py # For freshly uploaded resumes
├── uploaded_resume_processing.py # For resumes already in bucket
│
├── clean_up.py # Resets interview_results table
│
├── templates/
│ ├── index.html # resume uploading front end for HR
│ ├── shortlisted.html # shortlisted candidates (live from BigQuery)
│ ├── login.html # candidate interview start page
│ ├── interview.html # candidate interview questions page
│ ├── processing.html # candidate interview response process bar page
│ ├── result.html # candidate interview completed page
│
├── static/
│ ├── styles.css 
│ └── css/style.css
│
├── machine_learning_jd.txt
├── Dockerfile
├── requirements.txt
└── .env

```

---

# 🚀 Running the Modules (app.py and interview.py)

### **1. Install dependencies:**
``` bash
pip install -r requirements.txt
```

### **2. Set environment variables:**
Create a `.env` file


### **3. Run locally:**

python app.py (for ats processing of resumes via a front-end) <br>
python interview.py (for taking interview of the candidate)

---

# 📊 BigQuery Table Schemas

### **1. shortlisted_resume**

| Field          | Type     |
|----------------|----------|
| candidate_id   | INT64    |
| name           | STRING   |
| phone_number   | STRING   |
| email          | STRING   |
| resume_text    | STRING   |
| ats_score      | FLOAT64  |
| shortlisted    | STRING   |
| batch_id       | INT64    |

### **2. interview_results**

| Field              | Type     |
|--------------------|----------|
| candidate_id        | INT64    |
| name                | STRING   |
| email               | STRING   |
| phone_number        | STRING   |
| full_transcript     | STRING   |
| final_score         | FLOAT64  |
| summarised_feedback | STRING   |

---

## 💡 Highlights / Advantages

### 🔍 Smart Resume Screening (ATS Engine)
- Extracts **structured candidate data** (name, email, phone) using Gemini.
- Converts raw PDF resumes to clean text using LLM parsing.
- Calculates **ATS Compatibility Score** based on ML Job Description.
- Identifies and shortlists the strongest candidates automatically.
- Automatically copies **shortlisted PDFs** into a dedicated GCS folder.

### 🎤 AI Voice Interview System (Hosted)
- Generates **personalized interview questions** from the candidate’s resume.
- Uses Google **Text-to-Speech** for natural spoken questions.
- Captures candidate answers via microphone (browser-based).
- Transcribes answers with **Gemini 2.5 Flash**.
- AI evaluator rates each answer (1–10), gives reasoning, summary, and a final score.
- Saves results to BigQuery for HR review.

### ☁️ Seamless Google Cloud Integration
- Fully integrated with:
  - Google Cloud Storage  
  - BigQuery  
  - Vertex AI (Gemini)  
  - Google TTS  
- Uses **service account authentication** (secure).

### 🧩 Modular Architecture
- ATS, PDF parsing, email sending, interview, and scoring modules are decoupled.
- Easy to maintain and extend (e.g., add new job roles or change scoring logic).

### 📈 BigQuery-Based Workflow
- Complete resume + interview data pipeline.
- Shortlisted candidates stored in one table.
- Final interview results stored in another.
- Enables dashboards, analytics, and HR reports.

### 📬 Automated Email Workflow
- Sends interview invitation emails to shortlisted candidates.
- Unique Candidate ID assigned automatically.
- Ensures only qualified candidates enter the interview system.

### 🎨 Modern UI/UX
- Clean, responsive HTML/CSS.
- Modern dark theme for interview screens.
- Smooth transitions and user-friendly recording interface.

---

## 🤝 Contributions

PRs and improvements are welcome.
