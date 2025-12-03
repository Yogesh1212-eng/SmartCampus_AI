from flask import Flask, render_template, request, jsonify, redirect, url_for, session
import google.generativeai as genai
import firebase_admin
from firebase_admin import credentials, firestore
from google.cloud.firestore_v1.base_query import FieldFilter 
import json 
from pathlib import Path
import uuid
import os

# =======================================================================
# 1. APPLICATION & FIREBASE SETUP (Must be at the beginning)
# =======================================================================

app = Flask(__name__) # <--- THIS MUST BE THE FIRST LINE AFTER IMPORTS!
app.secret_key = 'secret key here ' 


# FIREBASE SETUP
SERVICE_ACCOUNT_FILE = "firebase-service-account.json"
db = None
DEFAULT_APP_ID = 'smartcampus-default'

try:
    base_dir = Path(__file__).parent
    service_account_path = base_dir / SERVICE_ACCOUNT_FILE

    cred = credentials.Certificate(service_account_path)
    
    with open(service_account_path, 'r') as f:
        service_account_data = json.load(f)
    
    DEFAULT_APP_ID = service_account_data.get('project_id', 'smartcampusai-8002a') 

    if not firebase_admin._apps:
        firebase_admin.initialize_app(cred)
    db = firestore.client()
    print(f"Firebase initialized successfully. Default App ID: {DEFAULT_APP_ID}")

except Exception as e:
    print(f"CRITICAL ERROR: Firebase Setup Failed. Root Cause: {e}")
    db = None
# GEMINI API SETUP: GLOBAL INITIALIZATION (FIXED)
# -------------------------------------------------------------------
# !!! PLACE YOUR GEMINI API KEY HERE FOR LOCAL TESTING !!!
# The code checks the OS environment variable first, then uses this hardcoded key.
GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY", "Your api key ")
# I have directly inserted the key you provided into the fallback area.
# -------------------------------------------------------------------

try:
    # 1. Configure the API key first
    if GEMINI_API_KEY and GEMINI_API_KEY != "YOUR_API_KEY_HERE":
        genai.configure(api_key=GEMINI_API_KEY)
        
    # 2. Initialize the model using the standard method (NO explicit 'tools' argument, 
    # as the runtime should handle grounding if available and compatible).
    model = genai.GenerativeModel('gemini-2.5-flash')
    print("Gemini model initialized successfully.")
except Exception as e:
    print(f"CRITICAL ERROR: Gemini Model Initialization Failed. Root Cause: {e}")
    # Define a robust fallback model that won't raise NameErrors
    def fallback_model_function(prompt):
        return type('Response', (object,), {'text': f"Sorry, the live AI is currently offline due to a model error. You asked: {prompt}"})()
    model = fallback_model_function
    
# Hardcoded Admin credentials for demonstration (FIXED)
ADMIN_USERNAME = "admin"
ADMIN_PASSWORD = "secure_password" # Set your secure password here


# =======================================================================
# 2. APPLICATION ROUTES
# =======================================================================

@app.route("/")
def index():
    """Renders the main dashboard page."""
    return render_template("index.html")

# --- Chatbot Route (FIXED to use global model without internal configure calls) ---
@app.route("/get", methods=["GET"])
def chatbot_reply():
    """Handles chatbot queries using the Gemini API."""
    user_msg = request.args.get("msg")
    
    if not user_msg:
        return jsonify({"reply": "Error: Missing user message."}), 400

    try:
        # Use the global model instance 'model'
        response = model.generate_content(user_msg)
        bot_reply = response.text
        return jsonify({"reply": bot_reply})

    except Exception as e:
        print(f"Gemini API Error: {e}") 
        # Fallback response if the API call or configuration fails
        return jsonify({"reply": "Sorry, an error occurred while connecting to the AI. Please try again."}), 500


# --- Admin & Auth Routes ---

@app.route("/admin/login", methods=["GET", "POST"])
def admin_login():
    """Handles Admin login via session management."""
    if request.method == "POST":
        username = request.form.get("username")
        password = request.form.get("password")
        
        if username == ADMIN_USERNAME and password == ADMIN_PASSWORD:
            session['logged_in'] = True
            session['username'] = username
            # Redirect admin to the attendance view
            return redirect(url_for('events')) 
        else:
            return render_template("admin_login.html", error="Invalid Credentials")
    
    return render_template("admin_login.html")

@app.route("/admin/logout")
def admin_logout():
    """Logs the admin out by clearing the session."""
    session.pop('logged_in', None)
    session.pop('username', None)
    return redirect(url_for('index'))


# --- Events CRUD & Utility Routes ---

@app.route("/events/create", methods=["POST"])
def create_event():
    """Endpoint to handle event creation and save data to Firestore."""
    if not session.get('logged_in') or db is None:
        return jsonify({"success": False, "message": "Unauthorized or database unavailable."}), 401
    
    event_data = {
        'title': request.form.get('title'),
        'date': request.form.get('date'),
        'time': request.form.get('time'),
        'details': request.form.get('details'),
        'timestamp': firestore.SERVER_TIMESTAMP 
    }

    try:
        app_id = request.environ.get('__app_id', DEFAULT_APP_ID)
        collection_path = f"artifacts/{app_id}/public/data/events"
        
        db.collection(collection_path).add(event_data)
        print(f"Event successfully saved to: {collection_path}")
        return jsonify({"success": True, "message": "Event created successfully!"})
    except Exception as e:
        print(f"Firestore WRITE Error during create_event: {e}")
        return jsonify({"success": False, "message": "Failed to save event."}), 500

@app.route("/events/delete/<event_id>", methods=["POST"])
def delete_event(event_id):
    """Endpoint to handle event deletion by Admin."""
    if not session.get('logged_in') or db is None:
        return jsonify({"success": False, "message": "Unauthorized or database unavailable."}), 401

    try:
        app_id = request.environ.get('__app_id', DEFAULT_APP_ID)
        collection_path = f"artifacts/{app_id}/public/data/events"
        
        doc_ref = db.collection(collection_path).document(event_id)
        doc_ref.delete()
        
        print(f"Event {event_id} successfully deleted from {collection_path}")
        return jsonify({"success": True, "message": "Event deleted successfully!"})
    except Exception as e:
        print(f"Firestore DELETE Error: {e}")
        return jsonify({"success": False, "message": "Failed to delete event."}), 500

@app.route("/events/register/<event_id>", methods=["POST"])
def register_for_event(event_id):
    """Handles student registration for a specific event."""
    if db is None:
        return jsonify({"success": False, "message": "Database unavailable."}), 500

    # Using a temp UUID for unauthenticated user
    temp_user_id = str(uuid.uuid4()) 
    
    registration_data = {
        'event_id': event_id,
        'user_id': temp_user_id,
        'registration_date': firestore.SERVER_TIMESTAMP
    }

    try:
        app_id = request.environ.get('__app_id', DEFAULT_APP_ID)
        collection_path = f"artifacts/{app_id}/public/data/registrations" 
        
        db.collection(collection_path).add(registration_data)
        
        print(f"Registration successful for user {temp_user_id} on event {event_id}")
        return jsonify({
            "success": True, 
            "message": "Registration successful!",
            "user_id": temp_user_id
        })
        
    except Exception as e:
        print(f"Firestore WRITE Error during registration: {e}")
        return jsonify({"success": False, "message": "Failed to save registration record."}), 500


@app.route("/events/generate_summary", methods=["POST"])
def generate_summary():
    """Generates a short, engaging summary for the event using Gemini."""
    if not session.get('logged_in'):
        return jsonify({"success": False, "message": "Unauthorized access."}), 401
    
    event_details = request.form.get('details', '')
    event_title = request.form.get('title', 'Campus Event')
    
    prompt = (f"Write a short, engaging, 1-2 sentence social media caption for a student event titled '{event_title}'. "
            f"The event details are: {event_details}. The tone should be exciting and informal.")
    
    try:
        # Use a model without grounding, as summaries are creative.
        summary_model = genai.GenerativeModel('gemini-2.5-flash')
        response = summary_model.generate_content(prompt)
        return jsonify({"success": True, "summary": response.text})
    except Exception as e:
        print(f"Gemini API Error (Summary): {e}")
        return jsonify({"success": False, "message": "Failed to generate summary."}), 500

@app.route("/events/analyze_registrations/<event_id>", methods=["GET"])
def analyze_registrations(event_id):
    """Analyzes registration data for an event and generates a short report using Gemini."""
    if not session.get('logged_in') or db is None:
        return jsonify({"success": False, "message": "Unauthorized or database unavailable."}), 401

    try:
        app_id = request.environ.get('__app_id', DEFAULT_APP_ID)
        reg_collection_path = f"artifacts/{app_id}/public/data/registrations"
        
        registrations_ref = db.collection(reg_collection_path).where(filter=FieldFilter('event_id', '==', event_id)).stream()
        registrations = [doc.to_dict() for doc in registrations_ref]
        
        total_registrations = len(registrations)
        if total_registrations == 0:
            return jsonify({"success": True, "report": "No registrations recorded yet."})

        prompt_data = f"Total Registrations: {total_registrations}"
        
        prompt = (f"Act as a campus analyst. Analyze this registration data for an event: {prompt_data}. "
                f"Provide a brief, single-paragraph summary of the current engagement status and future expected turnout. "
                f"The current total is {total_registrations}.")
        
        # Use a model for analysis
        analysis_model = genai.GenerativeModel('gemini-2.5-flash')
        response = analysis_model.generate_content(prompt)
        return jsonify({"success": True, "report": response.text})
        
    except Exception as e:
        print(f"Error analyzing registrations: {e}")
        return jsonify({"success": False, "message": "Failed to generate analysis report."}), 500


@app.route("/events")
def events():
    """Renders the Events page, fetching data from Firestore and checking admin status."""
    if db is None:
        return render_template("events.html", events=[], is_admin=session.get('logged_in', False), db_error=True)

    app_id = request.environ.get('__app_id', DEFAULT_APP_ID)
    collection_path = f"artifacts/{app_id}/public/data/events"

    try:
        events_ref = db.collection(collection_path).order_by('timestamp', direction=firestore.Query.DESCENDING).stream()
        event_list = [dict(doc.to_dict(), id=doc.id) for doc in events_ref] 
    except Exception as e:
        print(f"Firestore READ Error: {e}")
        event_list = []
    
    is_admin = session.get('logged_in', False)
    
    return render_template("events.html", events=event_list, is_admin=is_admin)


# --- Timetable Route ---
@app.route("/timetable")
def timetable():
    """Renders the Class Timetable page."""
    return render_template("timetable.html")


# --- Utility function to handle common read/write logic for Circulars and Results ---
def handle_public_record(record_type, is_write=False):
    """
    Handles common Firestore logic for read (circulars, results) and write (admin upload).
    record_type should be 'circulars' or 'results'.
    """
    is_admin = session.get('logged_in', False)
    app_id = request.environ.get('__app_id', DEFAULT_APP_ID)
    collection_path = f"artifacts/{app_id}/public/data/{record_type}"
    
    if db is None:
        return {'success': False, 'message': 'Database unavailable.'}

    if is_write:
        # WRITE/UPDATE LOGIC (Admin Only)
        if not is_admin:
            return {'success': False, 'message': 'Unauthorized access.'}
        
        doc_id = request.form.get('doc_id')
        title = request.form.get('title')
        details = request.form.get('details')
        
        if not doc_id or not title or not details:
            return {'success': False, 'message': 'Missing required fields (ID, Title, Details).'}

        try:
            record_data = {
                'title': title,
                'details': details,
                'timestamp': firestore.SERVER_TIMESTAMP 
            }
            db.collection(collection_path).document(doc_id).set(record_data, merge=True)
            return {'success': True, 'message': f"{record_type.capitalize()} record saved successfully!"}
        except Exception as e:
            print(f"Firestore WRITE Error ({record_type}): {e}")
            return {'success': False, 'message': f"Failed to save {record_type} record."}
    
    else:
        # READ LOGIC (Global Access)
        try:
            records_ref = db.collection(collection_path).order_by('timestamp', direction=firestore.Query.DESCENDING).stream()
            record_list = []
            for doc in records_ref:
                data = doc.to_dict()
                timestamp = data.get('timestamp')
                last_updated = 'N/A'
                if timestamp and hasattr(timestamp, 'strftime'):
                    last_updated = timestamp.strftime('%Y-%m-%d %H:%M')
                
                record_list.append({
                    'doc_id': doc.id,
                    'title': data.get('title', 'No Title'),
                    'details': data.get('details', 'No Details'),
                    'last_updated': last_updated
                })
            
            return {'success': True, 'records': record_list, 'is_admin': is_admin}
        
        except Exception as e:
            print(f"Firestore READ Error ({record_type}): {e}")
            return {'success': False, 'message': f"Failed to fetch {record_type} records."}


# --- Circulars Routes ---

@app.route("/circulars")
def circulars():
    """Renders the Circulars page and fetches all circulars."""
    context = handle_public_record('circulars', is_write=False)
    if not context['success']:
        # Return empty list and is_admin if read failed
        return render_template("circulars.html", records=[], is_admin=session.get('logged_in', False), error_message=context['message'])
        
    return render_template("circulars.html", records=context['records'], is_admin=context['is_admin'])

@app.route("/circulars/update", methods=["POST"])
def update_circulars():
    """Admin endpoint to update a circular record."""
    result = handle_public_record('circulars', is_write=True)
    return jsonify(result)


# --- Results Routes ---

@app.route("/results")
def results():
    """Renders the Results page and fetches all results."""
    context = handle_public_record('results', is_write=False)
    if not context['success']:
        return render_template("results.html", records=[], is_admin=session.get('logged_in', False), error_message=context['message'])
        
    return render_template("results.html", records=context['records'], is_admin=context['is_admin'])

@app.route("/results/update", methods=["POST"])
def update_results():
    """Admin endpoint to update a result record."""
    result = handle_public_record('results', is_write=True)
    return jsonify(result)


# --- Attendance Routes (Unchanged) ---
@app.route("/attendance")
def attendance():
    """Renders the Attendance page, fetching ALL student data for global view."""
    is_admin = session.get('logged_in', False)
    
    # 1. Initialize data structures
    all_students_data = [] 
    
    # Default data for the specific student card (used when not admin)
    student_id = request.args.get('user_id', 'generic_student') 
    attendance_data = {
        'student_id': student_id,
        'percentage': 0,
        'status': 'Data Not Found',
        'last_updated': 'N/A'
    }

    if db:
        app_id = request.environ.get('__app_id', DEFAULT_APP_ID)
        collection_path = f"artifacts/{app_id}/public/data/attendance"
        
        try:
            # --- GLOBAL DATA FETCH (Needed by EVERYONE for the table) ---
            students_ref = db.collection(collection_path).stream()
            
            for doc in students_ref:
                data = doc.to_dict()
                timestamp = data.get('timestamp')
                last_updated = 'N/A'
                
                if timestamp and hasattr(timestamp, 'strftime'):
                    last_updated = timestamp.strftime('%Y-%m-%d %H:%M')
                elif timestamp and hasattr(timestamp, 'date'):
                    last_updated = timestamp.date().strftime('%Y-%m-%d')
                    
                all_students_data.append({
                    'student_id': doc.id,
                    'percentage': data.get('percentage', 0),
                    'status': data.get('status', 'Unknown'),
                    'last_updated': last_updated
                })
            
            # Sort students for consistent display (e.g., by ID)
            all_students_data.sort(key=lambda x: x['student_id'])
            
            # --- SINGLE STUDENT DATA FETCH (Needed only by the student-specific card) ---
            # Look up the specific student data from the list we just fetched (or fetch again if needed)
            single_student_doc = db.collection(collection_path).document(student_id).get()
            
            if single_student_doc.exists:
                data = single_student_doc.to_dict()
                attendance_data['percentage'] = data.get('percentage', 0)
                attendance_data['status'] = data.get('status', 'Unknown')
                
                timestamp = data.get('timestamp')
                if timestamp and hasattr(timestamp, 'strftime'):
                    attendance_data['last_updated'] = timestamp.strftime('%Y-%m-%d %H:%M')
                elif timestamp and hasattr(timestamp, 'date'):
                    attendance_data['last_updated'] = timestamp.date().strftime('%Y-%m-%d')
                         
        except Exception as e:
            print(f"Firestore READ Error (Attendance): {e}")
            # If the database read fails, all_students_data will be empty, and single data will show error
            attendance_data['status'] = 'Database Read Error' 
    
    return render_template("attendance.html", 
                        attendance=attendance_data, # For the single student card view
                        is_admin=is_admin,
                        all_students=all_students_data) # For the global table view

@app.route("/attendance/update", methods=["POST"])
def update_attendance():
    """Admin endpoint to update a student's attendance record in Firestore."""
    if not session.get('logged_in') or db is None:
        return jsonify({"success": False, "message": "Unauthorized or database unavailable."}), 401
    
    student_id = request.form.get('student_id')
    percentage = request.form.get('percentage')
    status = request.form.get('status')

    if not student_id or not percentage or not status:
        return jsonify({"success": False, "message": "Missing required fields (Student ID, Percentage, Status)."}), 400

    try:
        attendance_data = {
            'percentage': int(percentage),
            'status': status,
            'timestamp': firestore.SERVER_TIMESTAMP 
        }

        app_id = request.environ.get('__app_id', DEFAULT_APP_ID)
        collection_path = f"artifacts/{app_id}/public/data/attendance" 
        
        db.collection(collection_path).document(student_id).set(attendance_data, merge=True)
        
        print(f"Attendance for {student_id} updated successfully.")
        return jsonify({"success": True, "message": f"Attendance for {student_id} updated successfully!"})
        
    except Exception as e:
        print(f"Firestore WRITE Error (Attendance Update): {e}")
        return jsonify({"success": False, "message": "Failed to save attendance record."}), 500


# =======================================================================
# 3. RUN THE APPLICATION
# =======================================================================
if __name__ == "__main__":
    app.run(debug=True)