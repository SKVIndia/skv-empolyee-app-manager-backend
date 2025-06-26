#!/usr/bin/env python3
import os
import sys
import pandas as pd
import psycopg2
from flask import Flask, request, jsonify
from flask_cors import CORS
from dotenv import load_dotenv
from werkzeug.utils import secure_filename

# Load .env variables
load_dotenv()

# Flask app setup
app = Flask(__name__)
CORS(app)  # Enable CORS for all routes

UPLOAD_FOLDER = "./uploads"
os.makedirs(UPLOAD_FOLDER, exist_ok=True)

DATABASE_URL = os.getenv("DATABASE_URL", "")
PORT = int(os.environ.get("PORT", 5000))


@app.route("/", methods=["GET"])
def home():
    return jsonify({"message": "✅ SKV Employee Uploader is running."})


@app.route("/upload", methods=["POST"])
def upload_file():
    if 'file' not in request.files:
        return jsonify({"error": "No file uploaded"}), 400

    file = request.files['file']
    if file.filename == "":
        return jsonify({"error": "Empty file name"}), 400

    filename = secure_filename(file.filename)
    file_path = os.path.join(UPLOAD_FOLDER, filename)
    file.save(file_path)

    try:
        create_neon_database(file_path)
        return jsonify({"message": "✅ Upload and database sync successful"}), 200
    except Exception as e:
        return jsonify({"error": str(e)}), 500


def create_neon_database(file_path: str):
    ext = file_path.split('.')[-1].lower()
    df = pd.read_csv(file_path) if ext == 'csv' else pd.read_excel(file_path)

    if df.empty:
        raise ValueError("❌ Empty or invalid file")

    df.columns = [col.strip().lower().replace(" ", "_") for col in df.columns]
    user_cols = ['employee_email', 'password']
    app_cols = [col for col in df.columns if col not in user_cols]

    conn = psycopg2.connect(DATABASE_URL, sslmode="require")
    cur = conn.cursor()

    # Drop old tables
    cur.execute("DROP TABLE IF EXISTS permissions;")
    cur.execute("DROP TABLE IF EXISTS users CASCADE;")

    # Create users table
    cur.execute(f"""
        CREATE TABLE users (
            employee_email TEXT PRIMARY KEY,
            password TEXT NOT NULL,
            {', '.join([f"{col} TEXT" for col in app_cols])}
        );
    """)

    # Create permissions table
    cur.execute("""
        CREATE TABLE permissions (
            email TEXT REFERENCES users(employee_email) ON DELETE CASCADE,
            app_name TEXT NOT NULL,
            app_link TEXT
        );
    """)

    for _, row in df.iterrows():
        values = [str(row[col]).strip() if pd.notna(row[col]) else None for col in df.columns]
        placeholders = ', '.join(['%s'] * len(df.columns))
        cur.execute(f"""
            INSERT INTO users ({', '.join(df.columns)})
            VALUES ({placeholders})
            ON CONFLICT (employee_email) DO UPDATE SET
            {', '.join([f"{col}=EXCLUDED.{col}" for col in df.columns if col != 'employee_email'])};
        """, values)

        email = str(row["employee_email"]).strip()
        for app_col in app_cols:
            link = str(row[app_col]).strip()
            if link.lower() not in ["n/a", "none", "null", ""] and pd.notna(link):
                cur.execute("INSERT INTO permissions (email, app_name, app_link) VALUES (%s, %s, %s);", (email, app_col, link))

    conn.commit()
    cur.close()
    conn.close()


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=PORT)
