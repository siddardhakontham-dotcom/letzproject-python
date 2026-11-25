from flask import Flask, render_template, request, jsonify, send_file
from werkzeug.utils import secure_filename
from pathlib import Path
from io import BytesIO, StringIO
import csv, json, re, uuid
from datetime import datetime
from duplicate_finder import analyze_text, clean_text, analyze_entries

BASE_DIR = Path(__file__).resolve().parent
UPLOAD_DIR = BASE_DIR / "uploads"
UPLOAD_DIR.mkdir(exist_ok=True)
ALLOWED_EXTENSIONS = {"txt", "csv", "json"}

app = Flask(__name__)
app.config["MAX_CONTENT_LENGTH"] = 10 * 1024 * 1024
app.config["UPLOAD_FOLDER"] = str(UPLOAD_DIR)

scan_history = []

def allowed_file(filename):
    return "." in filename and filename.rsplit(".", 1)[1].lower() in ALLOWED_EXTENSIONS

@app.get("/")
def index():
    return render_template("index.html")

@app.post("/api/analyze")
def api_analyze():
    payload = request.get_json(silent=True) or {}
    text = payload.get("text", "")
    options = {
        "ignore_case": bool(payload.get("ignore_case", False)),
        "ignore_whitespace": bool(payload.get("ignore_whitespace", False)),
        "trim_lines": bool(payload.get("trim_lines", True)),
    }
    result = analyze_text(text, **options)
    result["scan_id"] = str(uuid.uuid4())[:8]
    result["created_at"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    scan_history.insert(0, {
        "scan_id": result["scan_id"],
        "created_at": result["created_at"],
        "total_entries": result["total_entries"],
        "duplicate_entries": result["duplicate_entries"],
        "unique_entries": result["unique_entries"],
    })
    del scan_history[20:]
    return jsonify(result)

@app.post("/api/upload")
def api_upload():
    if "file" not in request.files:
        return jsonify({"error": "Choose a file to upload."}), 400
    file = request.files["file"]
    if not file.filename:
        return jsonify({"error": "No file selected."}), 400
    if not allowed_file(file.filename):
        return jsonify({"error": "Supported formats: TXT, CSV and JSON."}), 400
    filename = secure_filename(file.filename)
    data = file.read()
    try:
        content = data.decode("utf-8-sig")
    except UnicodeDecodeError:
        return jsonify({"error": "Please upload a UTF-8 encoded file."}), 400
    if filename.lower().endswith(".json"):
        try:
            parsed = json.loads(content)
            if isinstance(parsed, list):
                content = "\n".join(str(item) for item in parsed)
            else:
                content = json.dumps(parsed, ensure_ascii=False, indent=2)
        except json.JSONDecodeError:
            return jsonify({"error": "The JSON file is not valid."}), 400
    elif filename.lower().endswith(".csv"):
        rows = list(csv.reader(StringIO(content)))
        content = "\n".join(" | ".join(row) for row in rows)
    return jsonify({"filename": filename, "text": content})

@app.get("/api/history")
def api_history():
    return jsonify(scan_history)

@app.post("/api/export")
def api_export():
    payload = request.get_json(silent=True) or {}
    fmt = payload.get("format", "txt").lower()
    result = payload.get("result") or {}
    entries = result.get("entries", [])
    duplicates = result.get("duplicates", [])
    if fmt == "json":
        content = json.dumps(result, ensure_ascii=False, indent=2).encode("utf-8")
        mimetype, name = "application/json", "duplicate-report.json"
    elif fmt == "csv":
        output = StringIO()
        writer = csv.writer(output)
        writer.writerow(["Line", "Text", "Status", "Occurrences"])
        duplicate_map = {d["normalized"]: d["count"] for d in duplicates}
        for entry in entries:
            writer.writerow([entry["line"], entry["text"], entry["status"], duplicate_map.get(entry["normalized"], 1)])
        content = output.getvalue().encode("utf-8-sig")
        mimetype, name = "text/csv", "duplicate-report.csv"
    else:
        lines = ["DUPLICATE TEXT FINDER REPORT", "=" * 30,
                 f"Total entries: {result.get('total_entries', 0)}",
                 f"Unique entries: {result.get('unique_entries', 0)}",
                 f"Duplicate entries: {result.get('duplicate_entries', 0)}",
                 f"Duplicate groups: {result.get('duplicate_groups', 0)}", "", "DUPLICATE GROUPS"]
        for group in duplicates:
            lines.append(f'\n{group["count"]} occurrences: {group["text"]}')
            lines.append("Lines: " + ", ".join(map(str, group["lines"])))
        content = "\n".join(lines).encode("utf-8")
        mimetype, name = "text/plain", "duplicate-report.txt"
    return send_file(BytesIO(content), mimetype=mimetype, as_attachment=True, download_name=name)

if __name__ == "__main__":
    app.run(debug=True, host="127.0.0.1", port=5000)
