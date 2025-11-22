# clean_up.py
import os
from google.cloud import bigquery
from dotenv import load_dotenv

load_dotenv()
GCP_PROJECT_ID = os.getenv("GCP_PROJECT_ID")
BQ_DATASET_ID = os.getenv("BQ_DATASET_ID")

RESULTS_TABLE_ID = f"{GCP_PROJECT_ID}.{BQ_DATASET_ID}.interview_results"

# Match this to your BQ table
SCHEMA = [
    bigquery.SchemaField("candidate_id", "INT64"),
    bigquery.SchemaField("name", "STRING"),
    bigquery.SchemaField("email", "STRING"),
    bigquery.SchemaField("phone_number", "STRING"),
    bigquery.SchemaField("full_transcript", "STRING"),
    bigquery.SchemaField("final_score", "FLOAT64"),
    bigquery.SchemaField("summarised_feedback","STRING")
]

def reset_table():
    client = bigquery.Client(project=GCP_PROJECT_ID)
    
    print(f"Attempting to delete table: {RESULTS_TABLE_ID}")
    try:
        client.delete_table(RESULTS_TABLE_ID, not_found_ok=True)
        print("✅ Table deleted successfully.")
    except Exception as e:
        print(f"⚠️ Error deleting table: {e}")

    print(f"Attempting to create table: {RESULTS_TABLE_ID}")
    try:
        table = bigquery.Table(RESULTS_TABLE_ID, schema=SCHEMA)
        client.create_table(table) 
        print("✅ Table created successfully.")
    except Exception as e:
        print(f"⚠️ Error creating table: {e}")

if __name__ == "__main__":
    reset_table()