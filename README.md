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

Only the *AI Interview Module* is hosted in production. (The interview.py module can be run locally as well) 
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

This module is deployed using the included Dockerfile.

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

# 🛠️ Folder Structure

```

project/
│
├── app.py # Resume uploader (local use)
├── interview.py # Hosted voice interview system
│
├── resume_processing.py # For freshly uploaded resumes
├── uploaded_resume_processing.py # For resumes already in bucket
│
├── clean_up.py # Resets interview_results table
│
├── templates/
│ ├── index.html
│ ├── shortlisted.html
│ ├── login.html
│ ├── interview.html
│ ├── processing.html
│ ├── result.html
│
├── static/
│ ├── styles.css
│ └── css/style.css
│
├── machine_learning_jd.txt
├── Dockerfile
├── requirements.txt
└── .env.example

```

---

# 🚀 Running the Modules (app.py and interview.py)

### **1. Install dependencies: **
``` bash
pip install -r requirements.txt
```

### **2. Set environment variables: **
Create a `.env` file


### **3. Run locally: **

python app.py (for ats processing of resumes via a front-end)
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
