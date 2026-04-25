from flask import Flask, render_template, request, jsonify, redirect, url_for, session
from flask_limiter import Limiter
from flask_limiter.util import get_remote_address
import datetime
import jwt
import hashlib
from account import *
from sb_data_engine import *
import os

app = Flask(__name__)
app.config['JWT_SECRET'] = "Srijan_Loves_Chhar_Patra"
app.secret_key = 'Partha_is_greater_fool_than_he_thinks'
UPLOAD_FOLDER = 'static/profile_pics'
ALLOWED_EXTENSIONS = {'png', 'jpg', 'jpeg', 'avif'}
app.config['UPLOAD_FOLDER'] = UPLOAD_FOLDER

limiter = Limiter(
    get_remote_address,
    app=app,
    default_limits=["200 per day", "50 per hour"],
    storage_uri="memory://", # Use Redis for production environments
)


def allowed_file(filename):
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS

@app.route("/")
def index():
    return render_template("index.html")

@app.route("/needhelp")
def needhelp():
    return render_template("needhelp.html")

@app.route("/submit-crisis", methods=['POST'])
@limiter.limit("3 per hour")
def submit_help():
    data = request.json
    metrics = data.get('behavioralMetrics', {})
    if metrics.get('automationFlag') is True:
        return jsonify({"error": "Automated requests are not allowed."}), 403
    
    if metrics.get('loadTime', 0) < 5:
        return jsonify({"error": "Spam protection: Submission was too fast."}), 403

    crisis = Crisis_Account(
        name= data.get("fullName"),
        phone_no= data.get("phone"),
        addr= data.get("address"),
        district= data.get("district"),
        pin= int(data.get("pincode")),
        desc= data.get("crisis"),
    )

    success = Crisis_DB.insert_record(crisis)
    if (success):
        return jsonify({
            "status": "success",
            "message": "Your request has been received. Our team will contact you shortly."
        }), 200
    return jsonify({"error": "Crisis Submission Failed"}), 503


@app.errorhandler(429)
def handle_ratelimit(e):
    return jsonify({
        "error": "Too many requests. Please wait before trying again.",
        "details": str(e.description)
    }), 429








@app.route("/joinus")
def joinus():
    return render_template("join.html")

@app.route("/register")
def register_page():
    return render_template("register.html")

@app.route('/request-otp', methods=['POST'])
def handle_send_otp():
    email = request.json.get('email')
    valid = Donor_DB.verify_email(email)
    if(valid):
        return jsonify({"status": "error", "message": "This Account Already Exists."}), 400
    success = OTP_Auth.send_otp_to_email(email)    
    if success:
        return jsonify({"status": "success", "message": "OTP sent to your email."})
    return jsonify({"status": "error", "message": "Failed to send OTP."}), 500
    

@app.route('/verify-otp', methods=['POST'])
def handle_verify():
    data = request.json
    otp = data.get('otp')
    email = data.get('email')
    
    is_valid = OTP_Auth.verify_email_otp(email, otp)
    
    if is_valid:
        print("OTP Validated")
        user_agent = request.headers.get('User-Agent', '')
        fingerprint = hashlib.sha256(user_agent.encode()).hexdigest()
        payload = {
            "email": email,
            "status": "Verified",
            "exp": datetime.datetime.now(datetime.timezone.utc) + datetime.timedelta(seconds=240),
            "fprint": fingerprint
        }
        token = jwt.encode(payload, app.config['JWT_SECRET'], algorithm="HS256")

        return jsonify({"status": "success", "message": "Verified", "token" : token})
    
    print("OTP was not validated")
    return jsonify({"status": "error", "message": "Invalid OTP."}), 400


@app.route("/signup")
def signup_page():
    token = request.args.get('token')
    current_fprint = hashlib.sha256(request.headers.get('User-Agent', '').encode()).hexdigest()
    if not token:
        return redirect(url_for('register_page'))
    
    try:
        decoded_data = jwt.decode(token, app.config['JWT_SECRET'], algorithms=["HS256"], leeway=0)
        if decoded_data['fprint'] != current_fprint:
            return redirect(url_for('register_page'))
        verified_email = decoded_data['email']
        print(f"Verified SignUp Request for Email{verified_email}")
        return render_template("signup.html")

    except jwt.ExpiredSignatureError:
        return redirect(url_for('register_page'))
    except jwt.InvalidTokenError:
        return jsonify({"error": "Invalid token."}), 401
    

@app.route('/complete-signup', methods=['POST'])
def finalize_registration():
    token = request.headers.get('Authorization')
    current_fprint = hashlib.sha256(request.headers.get('User-Agent', '').encode()).hexdigest()
    if not token:
        return redirect(url_for('register_page'))
    
    try:
        decoded_data = jwt.decode(token, app.config['JWT_SECRET'], algorithms=["HS256"])
        if decoded_data['fprint'] != current_fprint:
            return jsonify({"error": "Security Mismatch: Session bound to another device"}), 401
        verified_email = decoded_data['email']
        user_data = request.json
        donor_profile = Donor_Profile(
            email= verified_email,
            name = user_data.get("fullname"),
            phone_no= user_data.get("phone"), 
            prof= user_data.get("profession"),
            addr=user_data.get("address"),
            district=user_data.get("district"),
            pin= int(user_data.get("pincode")),
            pw= user_data.get("password")
            )
        success = Donor_DB.insert_profile(donor_profile)
        if success:
            return jsonify({"status": "success", "message": f"Account created for {verified_email}"})
        
        return jsonify({"error": "Account Creation Failed"}), 503

    except jwt.ExpiredSignatureError:
        return redirect(url_for('register_page'))
    except jwt.InvalidTokenError:
        return jsonify({"error": "Invalid token."}), 401


@app.route("/signin")
def signin_page():
    return render_template("signin.html")

@app.route('/signin-request', methods=['POST'])
def handle_signin():
    data = request.json
    email = data.get('email')
    password = data.get('password')

    is_valid, id = Donor_DB.get_id_through_email_password(email, password)

    if is_valid:
        user_agent = request.headers.get('User-Agent', '')
        fingerprint = hashlib.sha256(user_agent.encode()).hexdigest()
        payload = {
            "id": id,
            "iat": datetime.datetime.now(datetime.timezone.utc),
            "exp": datetime.datetime.now(datetime.timezone.utc) + datetime.timedelta(hours=1),
            "fprint": fingerprint
        }
        
        token = jwt.encode(payload, app.config['JWT_SECRET'], algorithm="HS256")

        return jsonify({
            "status": "success",
            "token": token
        })

    return jsonify({"error": "Invalid email or password"}), 401

@app.route("/session-validate")
def session_validate():
    token = request.headers.get('Authorization')
    current_fprint = hashlib.sha256(request.headers.get('User-Agent', '').encode()).hexdigest()

    if not token:
        return jsonify({"error": "Sign is Required."}), 401
    
    try:
        decoded_data = jwt.decode(token, app.config['JWT_SECRET'], algorithms=["HS256"], leeway=0)
        if decoded_data['fprint'] != current_fprint:
            return jsonify({"error": "Security Mismatch: Session bound to another device"}), 401
        id = decoded_data["id"]
        print(f"Log in session of {id} is validated")
        return render_template("dashboard.html")

    except jwt.ExpiredSignatureError:
        return jsonify({"error": "Token Expired."}), 401
    except jwt.InvalidTokenError:
        return jsonify({"error": "Invalid token."}), 401

@app.route('/dashboard')
def dashboard_page():
    token = request.args.get('token')
    current_fprint = hashlib.sha256(request.headers.get('User-Agent', '').encode()).hexdigest()

    if not token:
        return redirect(url_for('signin_page'))
    
    try:
        decoded_data = jwt.decode(token, app.config['JWT_SECRET'], algorithms=["HS256"], leeway=0)
        if decoded_data['fprint'] != current_fprint:
            return redirect(url_for('signin_page'))
        
        id = decoded_data["id"]
        print(f"NEW login with email {id}")
        return render_template("dashboard.html")

    except jwt.ExpiredSignatureError:
        return redirect(url_for('signin_page'))
    except jwt.InvalidTokenError:
        return jsonify({"error": "Invalid token."}), 401


@app.route('/get-donor-profile', methods=['GET'])
def get_donor_profile():
    token = request.headers.get('Authorization')
    if not token:
        return jsonify({"error": "Unauthorized access"}), 401

    try:
        decoded_data = jwt.decode(token, app.config['JWT_SECRET'], algorithms=["HS256"])
        id = int(decoded_data.get("id"))
        success ,data = Donor_DB.read_profile(id)

        if success:
            donor_data = {
                "full_name": data["full_name"],
                "phone": data["phone_no"],
                "email": data["email"],
                "profession": data["prof"],
                "address": data["address"],
                "district": data["district"],
                "pincode": data["pin_code"],
                "profile_pic": None,
            }

            return jsonify(donor_data), 200
        
        return jsonify({"error": "Internal Server Error"}), 500

    except jwt.ExpiredSignatureError:
        return jsonify({"error": "Session expired"}), 401
    except jwt.InvalidTokenError:
        return jsonify({"error": "Invalid session"}), 401
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route('/get-leaderboard', methods=['GET'])
def get_leaderboard():
    print("inside get leader board")
    try:
        success, donors = Donor_DB.read_top_10_profiles()
        
        if success:
            print(jsonify(donors))
            return jsonify(donors), 200
        
        return jsonify({"error": "Could not fetch leaderboard"}), 500
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route('/settings')
def settings_page():
    token = request.args.get('token')
    current_fprint = hashlib.sha256(request.headers.get('User-Agent', '').encode()).hexdigest()

    if not token:
        return redirect(url_for('signin_page'))
    
    try:
        decoded_data = jwt.decode(token, app.config['JWT_SECRET'], algorithms=["HS256"], leeway=0)
        if decoded_data['fprint'] != current_fprint:
            return redirect(url_for('signin_page'))
        
        id = decoded_data["id"]
        print(f"NEW login with email {id}")
        return render_template("settings.html")

    except jwt.ExpiredSignatureError:
        return redirect(url_for('signin_page'))
    except jwt.InvalidTokenError:
        return jsonify({"error": "Invalid token."}), 401

@app.route('/update-donor-profile', methods=['POST'])
def update_donor_profile():
    token = request.headers.get('Authorization')
    current_fprint = hashlib.sha256(request.headers.get('User-Agent', '').encode()).hexdigest()
    
    if not token:
        return jsonify({"error": "Unauthorized access"}), 401
    
    try:
        decoded_data = jwt.decode(token, app.config['JWT_SECRET'], algorithms=["HS256"])
        if decoded_data.get('fprint') != current_fprint:
            return jsonify({"error": "Security Mismatch: Session bound to another device"}), 401
        
        user_id = int(decoded_data.get("id"))
        user_data = request.json
        
        updated_profile = Donor_Profile(
            name= user_data.get("fullName"),
            phone_no = user_data.get("phone"),
            prof = user_data.get("profession"),
            addr = user_data.get("address"),
            district = user_data.get("district"),
            pin= int(user_data.get("pincode")),
            email= None,
            pw = None
        )

        success = Donor_DB.update_profile(user_id, updated_profile)
        
        if success:
            return jsonify({"status": "success", "message": "Profile updated successfully"})
        return jsonify({"error": "Update Failed"}), 503

    except jwt.ExpiredSignatureError:
        return jsonify({"error": "Session expired"}), 401
    except jwt.InvalidTokenError:
        return jsonify({"error": "Invalid session"}), 401
    except Exception as e:
        return jsonify({"error": str(e)}), 500
















@app.route('/forgot-password')
def forgot_pw_page():
    return render_template("forgotpw.html")

@app.route('/request-reset-otp', methods=['POST'])
def handle_reset_otp_request():
    email = request.json.get('email')
    valid = Donor_DB.verify_email(email)
    if(valid):
        success = OTP_Auth.send_otp_to_email(email)
        if success:
            return jsonify({"status": "success", "message": "OTP sent to your email."})
        return jsonify({"status": "error", "message": "Failed to send OTP."}), 500
    return jsonify({"status": "error", "message": "No Such Account Exists"}), 404

@app.route('/verify-reset-otp', methods=['POST'])
def handle_verify_reset_otp():
    data = request.json
    otp = data.get('otp')
    email = data.get('email')
    
    is_valid = OTP_Auth.verify_email_otp(email, otp)
    
    if is_valid:
        user_agent = request.headers.get('User-Agent', '')
        fingerprint = hashlib.sha256(user_agent.encode()).hexdigest()
        payload = {
            "email": email,
            "status": "Verified",
            "exp": datetime.datetime.now(datetime.timezone.utc) + datetime.timedelta(seconds=240),
            "fprint": fingerprint
        }
        token = jwt.encode(payload, app.config['JWT_SECRET'], algorithm="HS256")

        return jsonify({"status": "success", "message": "Verified", "token" : token})
    
    return jsonify({"status": "error", "message": "Invalid OTP."}), 400

@app.route("/reset-password-page")
def reset_pw_page():
    token = request.args.get('token')
    current_fprint = hashlib.sha256(request.headers.get('User-Agent', '').encode()).hexdigest()
    if not token:
        return redirect(url_for('forgot_pw_page'))
    
    try:
        decoded_data = jwt.decode(token, app.config['JWT_SECRET'], algorithms=["HS256"], leeway=0)
        if decoded_data['fprint'] != current_fprint:
            return redirect(url_for('register_page'))
        verified_email = decoded_data['email']
        print(f"Verified Reset PW Request for Email{verified_email}")
        return render_template("pwreset.html")

    except jwt.ExpiredSignatureError:
        return redirect(url_for('forgot_pw_page'))
    except jwt.InvalidTokenError:
        return jsonify({"error": "Invalid token."}), 401

@app.route("/update-password",  methods=['POST'])
def update_password():
    token = request.headers.get('Authorization')

    if not token:
        return jsonify({"error": "Missing or malformed token"}), 401

    data = request.json
    new_password = data.get('password')

    try:
        decoded_data = jwt.decode(token, app.config['JWT_SECRET'], algorithms=["HS256"], leeway=10)
        user_email = decoded_data.get('email')
        success = Donor_DB.update_password(user_email, new_password)
        if success:
            return jsonify({"status": "success", "message": "Password updated successfully"}), 200
        return jsonify({"error": "Failure to update password."}), 500
    except jwt.ExpiredSignatureError:
        return jsonify({"error": "Session expired."}), 401
    except jwt.InvalidTokenError:
        return jsonify({"error": "Invalid security token."}), 401
    except Exception as e:
        return jsonify({"error": "Internal server error"}), 500

@app.route('/delete-donor-account', methods=['POST'])
def delete_donor_account():
    token = request.headers.get('Authorization')
    if not token:
        return jsonify({"error": "Unauthorized access"}), 401

    try:
        decoded_data = jwt.decode(token, app.config['JWT_SECRET'], algorithms=["HS256"])
        user_id = int(decoded_data.get("id"))
        
        data = request.json
        provided_email = data.get("email")
        
        if not provided_email:
            return jsonify({"error": "Email is required for confirmation"}), 400

        deletion_success = Donor_DB.delete_profile_with_email(user_id, provided_email)
        
        if deletion_success:
            return jsonify({"status": "success", "message": "Account deleted successfully"}), 200
        else:
            return jsonify({"error": "Deletion Failed"}), 503

    except jwt.ExpiredSignatureError:
        return jsonify({"error": "Session expired"}), 401
    except jwt.InvalidTokenError:
        return jsonify({"error": "Invalid session"}), 401
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route('/update-old-password', methods=['POST'])
def update_old_password():
    token = request.headers.get('Authorization')
    if not token:
        return jsonify({"error": "Unauthorized access"}), 401

    try:
        decoded_data = jwt.decode(token, app.config['JWT_SECRET'], algorithms=["HS256"])
        user_id = int(decoded_data.get("id"))
        
        data = request.json
        old_pw = data.get("currentPassword")
        new_pw = data.get("newPassword")

        success, user_profile = Donor_DB.read_profile(user_id)
        if not success:
            return jsonify({"error": "User not found"}), 404
        if user_profile['password'] != old_pw:
            return jsonify({"error": "Incorrect current password"}), 400

        email = user_profile["email"]
       
        update_success = Donor_DB.update_password(email, new_pw)
        if update_success:
            return jsonify({"message": "Password updated successfully!"}), 200
        return jsonify({"error": "Update failed"}), 500

    except jwt.ExpiredSignatureError:
        return jsonify({"error": "Session expired"}), 401
    except Exception as e:
        return jsonify({"error": str(e)}), 500



if __name__ == "__main__":
    app.run(debug= True)