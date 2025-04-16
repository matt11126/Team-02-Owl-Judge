import secrets
import os
import re
import io # For sending file data in response
from datetime import timedelta, datetime
from functools import wraps
import logging # Import logging
from logging.handlers import RotatingFileHandler # For log rotation

# Import send_from_directory for favicon
from flask import Flask, request, jsonify, session, redirect, url_for, render_template, flash, g, send_file, send_from_directory

from flask_sqlalchemy import SQLAlchemy
from werkzeug.security import generate_password_hash, check_password_hash

# Try importing pandas, required for import/export. Handle if not installed.
try:
    import pandas as pd
    # Check for openpyxl as well, needed for Excel writing
    import openpyxl
except ImportError:
    pd = None # Set pandas to None if not installed
    openpyxl = None # Set openpyxl to None if not installed

# --- Configuration ---
app = Flask(__name__)
# Secret key: Essential for session security. Use environment variable in production.
app.secret_key = os.environ.get('SECRET_KEY', os.urandom(24))
# Database path: Use absolute path relative to this file.
basedir = os.path.abspath(os.path.dirname(__file__)) # Base directory
db_path = os.path.join(basedir, 'database.db')
app.config['SQLALCHEMY_DATABASE_URI'] = f'sqlite:///{db_path}'
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
# Session configuration: Filesystem-based sessions.
app.config['SESSION_TYPE'] = 'filesystem'
app.config['SESSION_PERMANENT'] = True
app.config['PERMANENT_SESSION_LIFETIME'] = timedelta(days=30) # Session lifetime
# Ensure session directory exists relative to the app file
session_dir = os.path.join(basedir, 'flask_session')
os.makedirs(session_dir, exist_ok=True)
app.config['SESSION_FILE_DIR'] = session_dir
app.config['SESSION_USE_SIGNER'] = True # Recommended for security (signs session cookie)
app.config['SESSION_COOKIE_HTTPONLY'] = True # Prevent client-side script access
app.config['SESSION_COOKIE_SAMESITE'] = 'Lax' # Basic CSRF protection

# Configure basic logging
log_dir = os.path.join(basedir, 'logs')
os.makedirs(log_dir, exist_ok=True)
log_file = os.path.join(log_dir, 'owljudge.log')

# Set log level based on debug mode
log_level = logging.DEBUG if app.debug else logging.INFO

# Use RotatingFileHandler for production to prevent log file growing indefinitely
# Set delay=True to prevent file opening until first log message
file_handler = RotatingFileHandler(log_file, maxBytes=1024000, backupCount=10, delay=True)
file_handler.setFormatter(logging.Formatter(
    '%(asctime)s %(levelname)s: %(message)s [in %(pathname)s:%(lineno)d]'
))
file_handler.setLevel(log_level)

# Remove default Flask handler to avoid duplicate logs if necessary
# app.logger.removeHandler(default_handler)

# Add our handler
app.logger.addHandler(file_handler)
app.logger.setLevel(log_level)

# Log application start after configuration
app.logger.info('OwlJudge startup configured.')

# --- Database Initialization ---
db = SQLAlchemy(app)

# --- Database Models ---

class User(db.Model):
    __tablename__ = 'users'
    id = db.Column(db.Integer, primary_key=True)
    email = db.Column(db.String(120), unique=True, nullable=False, index=True) # Added index
    password = db.Column(db.String(255), nullable=False)
    name = db.Column(db.String(50), nullable=False)
    role = db.Column(db.String(20), default='user', nullable=False) # 'user', 'judge', 'admin'

    # --- Flag for Judge Role Request ---
    judge_request_pending = db.Column(db.Boolean, default=False, nullable=False)
    # --- END ---

    # --- Fields for Password Reset ---
    reset_token = db.Column(db.String(100), nullable=True, index=True) # Store the secure token
    reset_token_expiration = db.Column(db.DateTime, nullable=True) # Store expiration time
    # --- END ---

    # Relationships
    # Scores given by this user (if they are a judge)
    judge_scores = db.relationship('Scores', back_populates='judge', foreign_keys='Scores.judge_id', lazy='dynamic') # Added lazy='dynamic'

    def __repr__(self):
        return f'<User {self.id}: {self.email} ({self.role})>'

    def set_password(self, password):
        """Hashes and sets the user's password."""
        # Ensure password is not empty before hashing
        if not password:
            raise ValueError("Password cannot be empty.")
        self.password = generate_password_hash(password)

    def check_password(self, password):
        """Checks if the provided password matches the stored hash."""
        # Ensure password arg is not None or empty before checking
        if not password:
            return False
        return check_password_hash(self.password, password)

    # --- Methods for Password Reset ---
    def generate_reset_token(self):
        """Generates a secure reset token and sets expiration."""
        token = secrets.token_urlsafe(32)
        self.reset_token = token
        # Set expiration (e.g., 1 hour from now)
        self.reset_token_expiration = datetime.utcnow() + timedelta(hours=1)
        return token

    def is_reset_token_valid(self, token):
        """Checks if the provided token matches and hasn't expired."""
        # Ensure token exists, matches, expiration is set, and expiration is in the future
        return (self.reset_token is not None and
                token is not None and # Ensure provided token is not None
                secrets.compare_digest(self.reset_token, token) and # Use compare_digest for security
                self.reset_token_expiration is not None and
                self.reset_token_expiration > datetime.utcnow())

    def invalidate_reset_token(self):
        """Clears the reset token and expiration after use or expiration."""
        self.reset_token = None
        self.reset_token_expiration = None
    # --- END NEW ---

class Projects(db.Model):
    __tablename__ = 'projects'
    project_id = db.Column(db.Integer, primary_key=True)
    project_name = db.Column(db.String(100), nullable=False, index=True) # Added index
    group_id = db.Column(db.Integer, nullable=False, index=True) # Added index
    description = db.Column(db.Text, nullable=True)
    # Relationships
    # Scores associated with this project
    scores = db.relationship('Scores', back_populates='project', cascade="all, delete-orphan", lazy='dynamic') # Added lazy='dynamic'

    def __repr__(self):
        return f'<Project {self.project_id}: {self.project_name}>'

class Scores(db.Model):
    __tablename__ = 'scores'
    score_id = db.Column(db.Integer, primary_key=True)
    category = db.Column(db.String(100), nullable=False)
    score_given = db.Column(db.Integer, nullable=False)
    project_id = db.Column(db.Integer, db.ForeignKey('projects.project_id', ondelete='CASCADE'), nullable=False, index=True) # Added index and ondelete
    judge_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False, index=True) # Added index
    timestamp = db.Column(db.DateTime, default=datetime.utcnow, nullable=False) # Added nullable=False

    # Relationships
    project = db.relationship('Projects', back_populates='scores')
    judge = db.relationship('User', back_populates='judge_scores')

    # Constraints
    # Ensure a judge can only give one score per category for a specific project
    __table_args__ = (db.UniqueConstraint('project_id', 'judge_id', 'category', name='_project_judge_category_uc'),)

    def __repr__(self):
        return f'<Score {self.score_id} - Proj:{self.project_id} Judge:{self.judge_id} Cat:{self.category} Score:{self.score_given}>'


# --- Decorators ---
def login_required(f):
    """Decorator to ensure a user is logged in."""
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if g.current_user is None:
            flash('Please log in to access this page.', 'warning')
            # Store the intended destination in the session
            session['next_url'] = request.url
            return redirect(url_for('login'))
        # Clear the stored URL if login check passes (no longer needed)
        session.pop('next_url', None)
        return f(*args, **kwargs)
    return decorated_function

def role_required(role):
    """Decorator to ensure user has a specific role."""
    def decorator(f):
        @wraps(f)
        def decorated_function(*args, **kwargs):
            # First, ensure user is logged in
            if g.current_user is None:
                flash('Please log in to access this page.', 'warning')
                session['next_url'] = request.url
                return redirect(url_for('login'))
            # Then, check the role
            if g.current_user.role != role:
                app.logger.warning(f"Unauthorized access attempt: User {g.current_user.id} ({g.current_user.role}) tried to access role '{role}' page {request.path}")
                flash(f'You must be an {role} to access this page.', 'danger')
                return redirect(url_for('index')) # Or a specific 'unauthorized' page
            return f(*args, **kwargs)
        return decorated_function
    return decorator

def roles_required(roles):
    """Decorator to ensure user has one of the specified roles."""
    if not isinstance(roles, list):
        roles = [roles] # Allow single role string as input

    def decorator(f):
        @wraps(f)
        def decorated_function(*args, **kwargs):
            # First, ensure user is logged in
            if g.current_user is None:
                flash('Please log in to access this page.', 'warning')
                session['next_url'] = request.url
                return redirect(url_for('login'))
            # Then, check if user's role is in the allowed list
            if g.current_user.role not in roles:
                allowed_roles = ", ".join(roles)
                app.logger.warning(f"Unauthorized access attempt: User {g.current_user.id} ({g.current_user.role}) tried to access roles '{allowed_roles}' page {request.path}")
                flash(f'You must have one of the following roles to access this page: {allowed_roles}.', 'danger')
                return redirect(url_for('index')) # Or a specific 'unauthorized' page
            return f(*args, **kwargs)
        return decorated_function
    return decorator

# --- Helper Functions / Template Filters ---
@app.template_filter('format_datetime')
def _jinja2_filter_datetime(date, fmt=None):
    """Formats a datetime object for Jinja templates."""
    if date is None:
        return 'N/A'
    # Ensure it's a datetime object
    if not isinstance(date, datetime):
        try:
            # Attempt to parse if it's an ISO string
            date = datetime.fromisoformat(date)
        except (TypeError, ValueError):
             return date # Return original if not datetime or parsable string

    # Use default format if none provided
    format_str = fmt if fmt else '%Y-%m-%d %H:%M:%S' # More standard default format
    try:
        # Format as UTC and add indicator for clarity
        return date.strftime(format_str) + " UTC"
    except ValueError: # Handle potential issues with the format string
        app.logger.warning(f"Invalid format string '{fmt}' used for datetime filter.")
        return str(date) # Fallback

# --- Context Processors ---
@app.context_processor
def inject_user_and_now():
    """Inject current_user and datetime.utcnow into templates."""
    # Also inject app.debug for conditional rendering in templates
    return dict(current_user=g.current_user, now=datetime.utcnow, config=app.config)

# --- Before Request Handlers ---
@app.before_request
def load_logged_in_user():
    """Load user from session into Flask's g context before each request."""
    user_id = session.get('user_id')
    # Use db.session.get for optimized primary key lookup
    g.current_user = db.session.get(User, user_id) if user_id else None
    # Optionally store request start time for performance monitoring
    g.request_start_time = datetime.utcnow()

@app.before_request
def make_session_permanent():
    """Ensure sessions are permanent based on config."""
    session.permanent = app.config['SESSION_PERMANENT']
    # No need for session.modified = True on every request unless modifying session

# --- After Request Handler ---
# Optional: Log request duration
# @app.after_request
# def log_request_duration(response):
#     if 'request_start_time' in g:
#         duration = datetime.utcnow() - g.request_start_time
#         app.logger.debug(f"Request {request.path} duration: {duration.total_seconds():.4f}s")
#     return response

# --- Helper Functions for Responses ---
def handle_error(message, category="error", redirect_url_name='index', is_json=None):
    """Flashes an error message and redirects, or returns JSON."""
    is_json_request = is_json if is_json is not None else request.accept_mimetypes.accept_json and not request.accept_mimetypes.accept_html
    if is_json_request:
        return jsonify({"status": "error", "message": message}), 400 # Bad Request is common
    else:
        flash(message, category)
        return redirect(url_for(redirect_url_name))

def handle_success(message, redirect_url=None, redirect_url_name='index', is_json=None):
    """Flashes a success message and redirects, or returns JSON."""
    is_json_request = is_json if is_json is not None else request.accept_mimetypes.accept_json and not request.accept_mimetypes.accept_html
    redirect_target = redirect_url or url_for(redirect_url_name)
    if is_json_request:
        # Include redirect_url in JSON response for JS handling
        return jsonify({"status": "success", "message": message, "redirect_url": redirect_target}), 200 # OK
    else:
        flash(message, "success")
        return redirect(redirect_target)

# --- Routes ---

# +++ Add Route for favicon.ico +++
@app.route('/favicon.ico')
def favicon():
    """Serves the favicon icon."""
    # Assumes favicon.ico is in the static directory
    # Use max_age for caching
    return send_from_directory(os.path.join(app.root_path, 'static'),
                               'favicon.ico', mimetype='image/vnd.microsoft.icon',
                               max_age=2592000) # Cache for 30 days

@app.route('/')
def index():
    """Home page route."""
    featured_projects = None
    # Show featured projects only to logged-in judges or admins
    if g.current_user and g.current_user.role in ['judge', 'admin']:
        # Simple example: Show first 3 projects. Refine logic as needed.
        try:
             featured_projects = Projects.query.order_by(Projects.project_name).limit(3).all()
        except Exception as e:
             app.logger.error(f"Error fetching featured projects: {e}", exc_info=True)
             flash("Could not load featured projects.", "error")
    return render_template('index.html', featured_projects=featured_projects)

@app.route('/about')
def about():
    """About Us page."""
    return render_template('about_us.html')

@app.route('/audience')
@login_required # Audience features likely require login
def audience():
    """Audience interaction page (placeholder if JS handles data)."""
    # Example: Fetch aggregated scores or project rankings if needed for audience view
    # This would require defining how audience view works.
    return render_template('audience.html')

@app.route('/contact', methods=['GET', 'POST'])
def contact():
    """Contact Us page with form handling."""
    if request.method == 'POST':
        name = request.form.get('name', '').strip()
        email = request.form.get('email', '').strip()
        message = request.form.get('message', '').strip()

        # Basic server-side validation
        if not name or not email or not message:
             flash('Please fill out all fields.', 'error')
             return render_template('contact_us.html') # Re-render form with error
        if not re.match(r"[^@]+@[^@]+\.[^@]+", email): # Simple email format check
             flash('Please enter a valid email address.', 'error')
             return render_template('contact_us.html', name=name, message=message) # Keep entered data

        # --- Placeholder for contact logic (e.g., send email, save to DB) ---
        # In a real app, implement email sending using Flask-Mail or another service
        app.logger.info(f"Contact form submission: Name='{name}', Email='{email}', Message='{message[:100]}...'") # Log truncated message
        # Consider storing messages or sending notifications
        # --- End Placeholder ---

        flash('Thank you for your message! We will get back to you soon.', 'success')
        return redirect(url_for('contact')) # Redirect after POST to prevent re-submission
    # GET request
    return render_template('contact_us.html')

@app.route('/profile')
@login_required
def profile():
    """User profile page."""
    # User object (g.current_user) is already available via context processor
    return render_template('profile.html', user=g.current_user)

# --- Authentication Routes ---

@app.route('/signup', methods=['GET', 'POST'])
def signup():
    """User signup route."""
    if g.current_user: # Redirect if already logged in
        flash("You are already logged in.", "info")
        return redirect(url_for('index'))

    if request.method == 'POST':
        # Expect JSON for signup POST
        if not request.is_json:
             app.logger.warning("Signup attempt failed: Request content type was not JSON.")
             return jsonify({"status": "error", "message": "Invalid request format. Only JSON is accepted."}), 415 # Unsupported Media Type

        data = request.get_json()
        if not data:
            app.logger.warning("Signup attempt failed: Empty JSON payload received.")
            return jsonify({"status": "error", "message": "Invalid JSON payload."}), 400

        email = data.get('email', '').strip()
        password = data.get('password') # Don't strip passwords
        confirm_password = data.get('confirm_password')
        name = data.get('name', '').strip()

        # --- Server-Side Validation ---
        errors = []
        if not all([email, password, confirm_password, name]):
            errors.append("All fields (Name, Email, Password, Confirm Password) are required.")
        # Simple email format check (more robust checks are complex)
        if email and not re.match(r"[^@]+@[^@]+\.[^@]+", email):
             errors.append("Invalid email format.")
        if password != confirm_password:
            errors.append("Passwords do not match.")

        # Password complexity (mirroring JS, but essential backend check)
        if not password or len(password) < 12: errors.append("Password must be at least 12 characters long.")
        if password and not re.search(r"[A-Z]", password): errors.append("Password must contain at least one uppercase letter.")
        if password and not re.search(r"[a-z]", password): errors.append("Password must contain at least one lowercase letter.")
        if password and not re.search(r"[0-9]", password): errors.append("Password must contain at least one number.")
        if password and not re.search(r"[!@#$%^&*()_+=\-{}\[\]:;\"'|\\<>,.?/~`]", password): errors.append("Password must contain at least one symbol.")

        if errors:
            # Log validation errors for debugging
            app.logger.warning(f"Signup validation failed for {email}: {'; '.join(errors)}")
            # Return validation errors as JSON
            return jsonify({"status": "error", "message": " ".join(errors)}), 400 # Bad Request
        # --- End Server-Side Validation ---

        # Check if email already exists (case-insensitive check recommended for email)
        if User.query.filter(db.func.lower(User.email) == db.func.lower(email)).first():
            app.logger.warning(f"Signup attempt failed: Email '{email}' already registered.")
            return jsonify({"status": "error", "message": "Email address already registered."}), 409 # Conflict

        try:
            # Create user with 'user' role by default.
            new_user = User(email=email, name=name, role='user')
            new_user.set_password(password) # Hash password
            db.session.add(new_user)
            db.session.commit()
            app.logger.info(f"New user signup successful: {email} (ID: {new_user.id})")

            # Return success JSON for AJAX request
            return jsonify({"status": "success", "message": "Account created successfully! Please log in.", "redirect_url": url_for('login')}), 201 # Created

        except ValueError as ve: # Catch password hashing errors (e.g., empty password)
             app.logger.error(f"Password validation error during signup for {email}: {ve}")
             return jsonify({"status": "error", "message": str(ve)}), 400
        except Exception as e:
            db.session.rollback()
            app.logger.error(f"Error during signup for {email}: {e}", exc_info=True) # Log traceback
            return jsonify({"status": "error", "message": "An error occurred during signup. Please try again."}), 500

    # GET request - Render the HTML template
    # Wrap the render_template in a try...except to catch potential template errors during GET
    try:
        return render_template('signup.html')
    except Exception as e:
        app.logger.error(f"Error rendering signup.html (GET request): {e}", exc_info=True)
        # Fallback to a generic error or redirect
        flash("An error occurred displaying the signup page.", "error")
        return redirect(url_for('index')) # Redirect to index as a safe fallback


@app.route('/login', methods=['GET', 'POST'])
def login():
    """User login route."""
    if g.current_user: # Redirect if already logged in
        flash("You are already logged in.", "info")
        return redirect(url_for('index'))

    if request.method == 'POST':
        # Expect JSON for login POST
        if not request.is_json:
            app.logger.warning("Login attempt failed: Request content type was not JSON.")
            return jsonify({"status": "error", "message": "Invalid request format. Only JSON is accepted."}), 415

        data = request.get_json()
        if not data:
             app.logger.warning("Login attempt failed: Empty JSON payload received.")
             return jsonify({"status": "error", "message": "Invalid JSON payload."}), 400

        email = data.get('email', '').strip()
        password = data.get('password') # Don't strip password

        if not email or not password:
            return jsonify({"status": "error", "message": "Email and password are required."}), 400

        # Find user by email (case-insensitive)
        user = User.query.filter(db.func.lower(User.email) == db.func.lower(email)).first()

        if user and user.check_password(password):
            session.clear() # Clear old session data for security (prevents session fixation)
            session['user_id'] = user.id
            session.permanent = True # Make session permanent as configured
            app.logger.info(f"User login successful: {user.email} (ID: {user.id})")

            # Determine redirect based on role, checking stored 'next_url' first
            next_url = session.pop('next_url', None) # Get and remove the stored URL
            if next_url:
                 redirect_url = next_url
                 app.logger.debug(f"Redirecting user {user.id} to stored next_url: {next_url}")
            elif user.role == 'admin':
                redirect_url = url_for('admin_dashboard')
            elif user.role == 'judge':
                redirect_url = url_for('vote_casting')
            else: # Default 'user' role
                redirect_url = url_for('index')

            return jsonify({"status": "success", "message": "Login successful!", "redirect_url": redirect_url}), 200
        else:
            app.logger.warning(f"Failed login attempt for email: {email}")
            # Keep error message generic to prevent user enumeration
            return jsonify({"status": "error", "message": "Invalid email or password."}), 401 # Unauthorized

    # GET request
    return render_template('login.html')

@app.route('/logout')
@login_required # Must be logged in to log out
def logout():
    """User logout route."""
    user_id = session.get('user_id', 'Unknown')
    user_email = g.current_user.email if g.current_user else 'Unknown'
    session.clear() # Clear all session data
    flash("You have been successfully logged out.", "success")
    app.logger.info(f"User logout successful: {user_email} (ID: {user_id})")
    return redirect(url_for('index'))

# --- User Profile Actions ---

@app.route('/update_name', methods=['POST'])
@login_required
def update_name():
    """API endpoint for logged-in user to update their name."""
    if not request.is_json:
        return jsonify({'status': 'error', 'message': 'Request must be JSON.'}), 415

    data = request.get_json()
    if not data:
        return jsonify({'status': 'error', 'message': 'Invalid JSON payload.'}), 400

    new_name = data.get('name', '').strip()

    if not new_name:
        return jsonify({'status': 'error', 'message': 'Name cannot be empty.'}), 400
    if len(new_name) > 50: # Match model length
        return jsonify({'status': 'error', 'message': 'Name cannot exceed 50 characters.'}), 400

    user = g.current_user
    try:
        user.name = new_name
        db.session.commit()
        app.logger.info(f"User {user.id} updated name to '{new_name}'")
        return jsonify({'status': 'success', 'message': 'Name updated successfully.'}), 200
    except Exception as e:
        db.session.rollback()
        app.logger.error(f"Error updating name for user {user.id}: {e}", exc_info=True)
        return jsonify({'status': 'error', 'message': 'An error occurred while updating name.'}), 500

@app.route('/change_password', methods=['POST'])
@login_required
def change_password():
    """API endpoint for logged-in user to change their password."""
    if not request.is_json:
        return jsonify({'status': 'error', 'message': 'Request must be JSON.'}), 415

    data = request.get_json()
    if not data:
        return jsonify({'status': 'error', 'message': 'Invalid JSON payload.'}), 400

    current_password = data.get('current_password')
    new_password = data.get('new_password')
    confirm_password = data.get('confirm_password')

    user = g.current_user

    if not all([current_password, new_password, confirm_password]):
        return jsonify({'status': 'error', 'message': 'All password fields are required.'}), 400

    if not user.check_password(current_password):
        app.logger.warning(f"Failed password change attempt for user {user.id}: Incorrect current password.")
        return jsonify({'status': 'error', 'message': 'Incorrect current password.'}), 401 # Unauthorized

    if new_password != confirm_password:
        return jsonify({'status': 'error', 'message': 'New passwords do not match.'}), 400

    # --- Password Strength Validation (Backend is crucial) ---
    errors = []
    if len(new_password) < 12: errors.append("Password must be at least 12 characters long.")
    if not re.search(r"[A-Z]", new_password): errors.append("Password must contain at least one uppercase letter.")
    if not re.search(r"[a-z]", new_password): errors.append("Password must contain at least one lowercase letter.")
    if not re.search(r"[0-9]", new_password): errors.append("Password must contain at least one number.")
    if not re.search(r"[!@#$%^&*()_+=\-{}\[\]:;\"'|\\<>,.?/~`]", new_password): errors.append("Password must contain at least one symbol.")
    if errors:
        return jsonify({'status': 'error', 'message': "Password validation failed: " + " ".join(errors)}), 400
    # --- End Validation ---

    if current_password == new_password:
        return jsonify({'status': 'error', 'message': 'New password cannot be the same as the current password.'}), 400

    try:
        user.set_password(new_password) # Hash and set the new password
        # Invalidate password reset tokens if they exist after successful change
        user.invalidate_reset_token()
        db.session.commit()
        app.logger.info(f"User {user.id} successfully changed their password.")
        # Optionally, log the user out after password change for security:
        # session.clear()
        # flash("Password changed successfully. Please log in again.", "success")
        # return jsonify({'status': 'success', 'message': 'Password changed successfully. Please log in again.', 'redirect_url': url_for('login')}), 200
        return jsonify({'status': 'success', 'message': 'Password changed successfully.'}), 200
    except ValueError as ve: # Catch password hashing errors
         app.logger.error(f"Password validation error during password change for user {user.id}: {ve}")
         return jsonify({"status": "error", "message": str(ve)}), 400
    except Exception as e:
        db.session.rollback()
        app.logger.error(f"Error changing password for user {user.id}: {e}", exc_info=True)
        return jsonify({'status': 'error', 'message': 'An error occurred while changing the password.'}), 500

# --- Password Reset Routes ---

# IMPORTANT: Email Sending Simulation - Replace with actual email logic in production!
def send_password_reset_email(user_email, reset_link):
    """Simulates sending a password reset email. Replace with actual email sending."""
    # --- Production Email Sending Example (requires Flask-Mail setup) ---
    # from flask_mail import Message
    # from extensions import mail # Assuming mail = Mail(app) setup in extensions.py or similar
    # try:
    #     msg = Message('Reset Your OwlJudge Password',
    #                   sender=app.config.get('MAIL_DEFAULT_SENDER', 'noreply@example.com'), # Configure in app.config
    #                   recipients=[user_email])
    #     # Consider using HTML templates for nicer emails
    #     msg.body = f'''Hello,
    #
    # Someone (hopefully you) requested a password reset for your OwlJudge account.
    #
    # Please click the link below to set a new password. This link is valid for 1 hour:
    # {reset_link}
    #
    # If you did not request this, please ignore this email. Your password will remain unchanged.
    #
    # Thank you,
    # The OwlJudge Team
    # '''
    #     # mail.send(msg) # Uncomment to send real email
    #     app.logger.info(f"Password reset email nominally sent to {user_email}")
    # except Exception as e:
    #     app.logger.error(f"Failed to send password reset email to {user_email}: {e}", exc_info=True)
    #     # Decide if you want to bubble up the error or just log it.
    #     # For security, don't reveal email sending failure to the user requesting the reset.
    # --- End Production Example ---

    # --- Simulation for Development ---
    app.logger.info("="*60)
    app.logger.info("SIMULATING PASSWORD RESET EMAIL (Replace with actual sending logic)")
    app.logger.info(f"To: {user_email}")
    app.logger.info("Subject: Reset Your OwlJudge Password")
    app.logger.info("Body:")
    app.logger.info(f"Someone (hopefully you) requested a password reset for your OwlJudge account.")
    app.logger.info(f"Click the link below to set a new password. This link is valid for 1 hour.")
    app.logger.info(f"\n{reset_link}\n") # IMPORTANT: Log the link for testing!
    app.logger.info("If you did not request this, please ignore this email.")
    app.logger.info("="*60)
    # --- End Simulation ---


@app.route('/forgot_password', methods=['GET', 'POST'])
def forgot_password():
    """Page for requesting a password reset link."""
    if g.current_user: # Redirect if already logged in
        flash("You are already logged in.", "info")
        return redirect(url_for('index'))

    if request.method == 'POST':
        email = request.form.get('email', '').strip()
        if not email:
            flash('Please enter your email address.', 'warning')
            return redirect(url_for('forgot_password'))

        # Find user case-insensitively
        user = User.query.filter(db.func.lower(User.email) == db.func.lower(email)).first()

        # SECURITY: Always show the same generic message whether the user exists or not.
        message = 'If an account with that email exists, a password reset link has been sent. Please check your inbox (and spam folder).'

        if user:
            try:
                token = user.generate_reset_token()
                db.session.commit() # Commit token and expiration to DB *before* sending email
                reset_url = url_for('reset_password_with_token', token=token, _external=True) # Generate full URL
                send_password_reset_email(user.email, reset_url) # Send email (simulated or real)
                app.logger.info(f"Generated password reset token for user {user.id} ({user.email})")
            except Exception as e:
                 db.session.rollback()
                 app.logger.error(f"Error processing password reset request for {email}: {e}", exc_info=True)
                 # Still show the generic success message to the user for security.

        flash(message, 'info')
        return redirect(url_for('login')) # Redirect to login page after request

    # GET request
    return render_template('forgot_password.html')

@app.route('/reset_password/<token>', methods=['GET', 'POST'])
def reset_password_with_token(token):
    """Page for resetting password using a token from email."""
    if g.current_user: # Redirect if already logged in
        flash("You are already logged in.", "info")
        return redirect(url_for('index'))

    # Find user by token AND validate it using the model method
    # Querying first is slightly more efficient than validating all users' tokens.
    user = User.query.filter_by(reset_token=token).first()

    # Check if user exists and token is valid (checks expiration and matches token)
    if not user or not user.is_reset_token_valid(token):
        app.logger.warning(f"Invalid or expired password reset token used: {token}")
        flash('The password reset link is invalid or has expired. Please request a new one.', 'danger')
        return redirect(url_for('forgot_password'))

    if request.method == 'POST':
        new_password = request.form.get('new_password')
        confirm_password = request.form.get('confirm_password')

        if not new_password or not confirm_password:
             flash('Both password fields are required.', 'warning')
             return render_template('reset_password.html', token=token) # Re-render with token

        if new_password != confirm_password:
            flash('Passwords do not match.', 'warning')
            return render_template('reset_password.html', token=token)

        # --- Password Strength Validation (same as signup/change) ---
        errors = []
        if len(new_password) < 12: errors.append("Password must be at least 12 characters long.")
        if not re.search(r"[A-Z]", new_password): errors.append("Password must contain at least one uppercase letter.")
        if not re.search(r"[a-z]", new_password): errors.append("Password must contain at least one lowercase letter.")
        if not re.search(r"[0-9]", new_password): errors.append("Password must contain at least one number.")
        if not re.search(r"[!@#$%^&*()_+=\-{}\[\]:;\"'|\\<>,.?/~`]", new_password): errors.append("Password must contain at least one symbol.")
        if errors:
            flash("Password validation failed: " + " ".join(errors), 'warning')
            return render_template('reset_password.html', token=token)
        # --- End Validation ---

        # Optional: Check if the new password is the same as the old one.
        # This requires `check_password`, might not be strictly necessary here.
        # if user.check_password(new_password):
        #     flash('New password cannot be the same as the old password.', 'warning')
        #     return render_template('reset_password.html', token=token)

        try:
            user.set_password(new_password) # Set the new password
            user.invalidate_reset_token() # Crucial: Invalidate the token after successful use
            db.session.commit()
            app.logger.info(f"User {user.id} successfully reset password using token.")
            flash('Your password has been successfully reset! You can now log in.', 'success')
            return redirect(url_for('login'))
        except ValueError as ve:
             flash(f"Password validation failed: {ve}", 'warning')
             return render_template('reset_password.html', token=token)
        except Exception as e:
            db.session.rollback()
            app.logger.error(f"Error resetting password for user {user.id} with token {token}: {e}", exc_info=True)
            flash('An error occurred while resetting your password. Please try again.', 'danger')
            return render_template('reset_password.html', token=token) # Re-render form on error

    # GET request: Show the password reset form
    return render_template('reset_password.html', token=token)


# --- Judge Role Request ---
@app.route('/request_judge_role', methods=['POST'])
@login_required # Must be logged in
def request_judge_role():
    """API endpoint for a user to request promotion to judge role."""
    user = g.current_user

    if user.role != 'user':
        # Provide informative messages for non-user roles
        if user.role == 'judge':
            msg = 'You are already a judge.'
        elif user.role == 'admin':
            msg = 'As an administrator, you already have judge privileges.'
        else: # Should not happen with current roles, but good practice
            msg = f'Your current role ({user.role}) does not require a request.'
        return jsonify({'status': 'info', 'message': msg}), 409 # Conflict/Info

    if user.judge_request_pending:
        return jsonify({'status': 'info', 'message': 'You have already submitted a request to become a judge. Please wait for administrator review.'}), 409 # Conflict/Info

    try:
        user.judge_request_pending = True
        db.session.commit()
        app.logger.info(f"User {user.id} ({user.email}) requested judge role.")
        # In a real system, trigger an email notification to admin(s) here
        # send_admin_notification(f"User {user.name} ({user.email}) requested judge role promotion.")
        return jsonify({'status': 'success', 'message': 'Your request to become a judge has been submitted. An administrator will review it.'}), 200
    except Exception as e:
        db.session.rollback()
        app.logger.error(f"Error processing judge role request for user {user.id}: {e}", exc_info=True)
        return jsonify({'status': 'error', 'message': 'An error occurred while submitting your request. Please try again.'}), 500

# --- Judge Voting Routes ---

@app.route('/vote')
@roles_required(['judge', 'admin']) # Judges and Admins can access vote casting
def vote_casting():
    """Page for judges/admins to view projects and cast/edit votes."""
    projects_with_status = []
    try:
        all_projects = Projects.query.order_by(Projects.project_name).all()
        judge_id = g.current_user.id

        for project in all_projects:
            # Efficiently check if *any* score exists for this judge/project combination
            # Using exists() is much faster than fetching all scores and checking len()
            has_voted = db.session.query(
                Scores.query.filter(
                    Scores.project_id == project.project_id,
                    Scores.judge_id == judge_id
                ).exists()
            ).scalar()
            projects_with_status.append({
                'project_id': project.project_id,
                'project_name': project.project_name,
                'group_id': project.group_id,
                'description': project.description, # Pass description too
                'has_voted': has_voted
            })
        return render_template('vote_casting.html', projects=projects_with_status)
    except Exception as e:
        app.logger.error(f"Error loading vote casting page for judge {g.current_user.id}: {e}", exc_info=True)
        flash("Error loading projects for voting. Please try again later.", "error")
        return redirect(url_for('index'))


@app.route('/get_scores/<int:project_id>', methods=['GET'])
@roles_required(['judge', 'admin'])
def get_scores(project_id):
    """API endpoint for a judge/admin to get their previously submitted scores for a project."""
    try:
        # Verify project exists
        project = db.session.get(Projects, project_id)
        if not project:
             return jsonify({'status': 'error', 'message': 'Project not found.'}), 404

        scores = Scores.query.filter_by(project_id=project_id, judge_id=g.current_user.id).all()
        # Return scores in a simple dictionary format {category: score}
        scores_dict = {score.category: score.score_given for score in scores}
        return jsonify(scores_dict), 200
    except Exception as e:
        app.logger.error(f"Error fetching scores for project {project_id} by judge {g.current_user.id}: {e}", exc_info=True)
        return jsonify({'status': 'error', 'message': 'An error occurred while fetching scores.'}), 500

@app.route('/submit_vote', methods=['POST'])
@roles_required(['judge', 'admin'])
def submit_vote():
    """API endpoint for a judge/admin to submit or update their scores for a project."""
    data = request.get_json()
    if not data:
        return jsonify({'status': 'error', 'message': 'Invalid request format. Expecting JSON.'}), 400

    # --- REFINED CHECKS ---
    project_id_raw = data.get('project_id') # Get raw value first
    scores_data = data.get('scores')

    if project_id_raw is None: # Specifically check for missing key
         app.logger.warning(f"Submit vote failed: Missing project_id field. Data: {data}")
         return jsonify({'status': 'error', 'message': 'Submission failed: Missing project_id field.'}), 400
    try:
        # Attempt conversion to integer AFTER checking it exists
        project_id = int(project_id_raw)
        if project_id <= 0: # Project IDs should be positive
             raise ValueError("Project ID must be a positive number.")
    except (ValueError, TypeError):
         # Catches non-integer strings, negative numbers, zero etc.
         app.logger.warning(f"Submit vote failed: Invalid project_id value '{project_id_raw}'. Data: {data}")
         return jsonify({'status': 'error', 'message': f'Submission failed: Invalid project_id value "{project_id_raw}". Must be a positive integer.'}), 400 # More specific message

    # Check scores_data is a non-empty dict
    if not scores_data or not isinstance(scores_data, dict) or not scores_data:
        app.logger.warning(f"Submit vote failed: Missing or invalid scores data for project {project_id}. Data: {data}")
        return jsonify({'status': 'error', 'message': 'Submission failed: Missing or invalid scores data.'}), 400
    # --- END REFINED CHECKS ---

    # Proceed with existing logic, using the validated integer `project_id`
    project = db.session.get(Projects, project_id)
    if not project:
        # This check remains important
        app.logger.warning(f"Submit vote failed: Project with ID {project_id} not found.")
        return jsonify({'status': 'error', 'message': f'Submission failed: Project with ID {project_id} not found.'}), 404

    judge_id = g.current_user.id

    try:
        # --- Score validation loop (Update range again if necessary) ---
        validated_scores = {}
        MIN_SCORE = 1 # Ensure this matches your form
        MAX_SCORE = 10 # Ensure this matches your form
        for category, score_value in scores_data.items():
            category = category.strip()
            if not category:
                 return jsonify({'status': 'error', 'message': "Score category cannot be empty."}), 400
            try:
                score = int(score_value)
                if not MIN_SCORE <= score <= MAX_SCORE:
                     raise ValueError(f"Score for '{category}' must be between {MIN_SCORE} and {MAX_SCORE}.")
                validated_scores[category] = score
            except (ValueError, TypeError):
                 return jsonify({'status': 'error', 'message': f"Invalid score value '{score_value}' for category '{category}'. Must be a whole number between {MIN_SCORE} and {MAX_SCORE}."}), 400
        # --- End score validation ---

        # Process validated scores (update or insert)
        updated_count = 0
        added_count = 0
        for category, score in validated_scores.items():
            existing_score = Scores.query.filter_by(
                project_id=project_id,
                judge_id=judge_id,
                category=category
            ).first()

            if existing_score:
                if existing_score.score_given != score: # Only update if changed
                    existing_score.score_given = score
                    existing_score.timestamp = datetime.utcnow()
                    db.session.add(existing_score) # Ensure it's added to session if modified
                    updated_count += 1
            else:
                new_score = Scores(
                    project_id=project_id,
                    judge_id=judge_id,
                    category=category,
                    score_given=score
                )
                db.session.add(new_score)
                added_count += 1

        if updated_count > 0 or added_count > 0:
            db.session.commit()
            action = "updated" if updated_count > 0 else "submitted"
            app.logger.info(f"Judge {judge_id} {action} votes for project {project_id} (Added: {added_count}, Updated: {updated_count})")
            return jsonify({'status': 'success', 'message': f'Votes for {project.project_name} {action} successfully.'}), 200
        else:
             # Case where submitted scores are identical to existing ones
             app.logger.info(f"Judge {judge_id} submitted identical votes for project {project_id}. No changes made.")
             return jsonify({'status': 'success', 'message': f'Votes for {project.project_name} submitted. No changes were needed.'}), 200


    except ValueError as ve: # Catch specific validation error from score range check
        db.session.rollback()
        app.logger.warning(f"Validation error submitting vote for project {project_id} by judge {judge_id}: {ve}")
        return jsonify({'status': 'error', 'message': str(ve)}), 400
    except Exception as e:
        db.session.rollback()
        app.logger.error(f"Error submitting vote for project {project_id} by judge {judge_id}: {e}", exc_info=True) # Log traceback
        return jsonify({'status': 'error', 'message': 'An internal error occurred while submitting votes.'}), 500
# --- Admin Routes ---

@app.route('/admin/dashboard')
@role_required('admin')
def admin_dashboard():
    """Admin dashboard page showing users, projects, scores, and pending requests."""
    try:
        # Fetch data using efficient queries and pre-loading related data
        # Use joinedload for Scores -> Project/Judge to avoid N+1 queries
        users_obj = User.query.order_by(User.name).all()
        projects_obj = Projects.query.order_by(Projects.project_name).all()
        # Preload project and judge data when querying scores
        scores_obj = db.session.query(Scores).options(
            db.joinedload(Scores.project),
            db.joinedload(Scores.judge)
        ).order_by(Scores.timestamp.desc()).all()

        # Convert objects to lists of dictionaries suitable for template/JSON
        # This transformation isolates template logic from DB objects
        users_list = [{
            'id': u.id, 'email': u.email, 'name': u.name, 'role': u.role,
            'judge_request_pending': u.judge_request_pending # Crucial for pending table
            } for u in users_obj]

        projects_list = [{
            'project_id': p.project_id, 'project_name': p.project_name, 'group_id': p.group_id,
            'description': p.description
            } for p in projects_obj]

        scores_list = [{
            'score_id': s.score_id, 'category': s.category, 'score_given': s.score_given,
            'project_id': s.project_id, 'judge_id': s.judge_id,
            'timestamp': s.timestamp.isoformat() if s.timestamp else None, # Use ISO format for consistency
            'project_name': s.project.project_name if s.project else 'N/A', # Handle potentially missing related objects gracefully
            'judge_name': s.judge.name if s.judge else 'N/A'
            } for s in scores_obj]

        return render_template('admin_dashboard.html',
                               users=users_list,
                               projects=projects_list,
                               scores=scores_list)
    except Exception as e:
        app.logger.error(f"Error loading admin dashboard: {e}", exc_info=True)
        flash("Error loading dashboard data. Please try again.", "error")
        return redirect(url_for('index')) # Redirect to a safe page on error


@app.route('/admin/approve_judge/<int:user_id>', methods=['POST'])
@role_required('admin')
def approve_judge_role(user_id):
    """API endpoint for admin to approve a user's request to become a judge."""
    user = db.session.get(User, user_id)
    if not user:
        return jsonify({'status': 'error', 'message': 'User not found.'}), 404

    if not user.judge_request_pending:
        return jsonify({'status': 'info', 'message': 'User does not have a pending request.'}), 400 # Bad request (nothing to approve)

    if user.role != 'user': # Safety check: Only promote 'user' role
         user.judge_request_pending = False # Clear flag if they are already judge/admin
         db.session.commit()
         app.logger.info(f"Admin {g.current_user.id} cleared pending flag for user {user_id} who is already '{user.role}'.")
         return jsonify({'status': 'info', 'message': f'User is already a {user.role}. Request flag cleared.'}), 200

    try:
        user.role = 'judge'
        user.judge_request_pending = False # Clear the flag
        db.session.commit()
        app.logger.info(f"Admin {g.current_user.id} approved judge role for user {user.id}")
        # In a real system, consider sending an email notification to the user
        # send_user_notification(user.email, "Your judge role request has been approved!")

        # Return updated user data for potential UI update on the frontend
        updated_user_data = {
            'id': user.id, 'email': user.email, 'name': user.name,
            'role': user.role, 'judge_request_pending': user.judge_request_pending
        }
        return jsonify({
            'status': 'success',
            'message': f'"{user.name}" ({user.email}) has been promoted to Judge.',
            'user': updated_user_data
        }), 200
    except Exception as e:
        db.session.rollback()
        app.logger.error(f"Error approving judge role for user {user_id}: {e}", exc_info=True)
        return jsonify({'status': 'error', 'message': 'Internal server error occurred while approving the role.'}), 500

# --- Admin CRUD Operations (Users) ---

@app.route('/admin/users', methods=['POST'])
@role_required('admin')
def add_user():
    """API endpoint for admin to add a new user."""
    if not request.is_json: return jsonify({'status': 'error', 'message': 'Request must be JSON.'}), 415
    data = request.get_json()
    if not data: return jsonify({'status': 'error', 'message': 'Invalid JSON payload.'}), 400

    required = ['name', 'email', 'password', 'role']
    if not all(k in data and data[k] not in [None, ''] for k in required): # Ensure required fields are present and not empty
        return jsonify({'status': 'error', 'message': 'Missing or empty required fields: name, email, password, role.'}), 400

    email = data['email'].strip()
    name = data['name'].strip()
    password = data['password'] # Don't strip password
    role = data.get('role', 'user').lower().strip() # Default to user, ensure lowercase

    if role not in ['admin', 'judge', 'user']:
        return jsonify({'status': 'error', 'message': 'Invalid role specified. Must be admin, judge, or user.'}), 400

    # Email format validation
    if not re.match(r"[^@]+@[^@]+\.[^@]+", email):
        return jsonify({'status': 'error', 'message': 'Invalid email format.'}), 400

    # Check for existing email (case-insensitive)
    if User.query.filter(db.func.lower(User.email) == db.func.lower(email)).first():
        return jsonify({'status': 'error', 'message': 'Email address already registered.'}), 409 # Conflict

    # Password strength validation
    errors = []
    if len(password) < 12: errors.append("Password min 12 chars.")
    if not re.search(r"[A-Z]", password): errors.append("Needs uppercase.")
    if not re.search(r"[a-z]", password): errors.append("Needs lowercase.")
    if not re.search(r"[0-9]", password): errors.append("Needs number.")
    if not re.search(r"[!@#$%^&*()_+=\-{}\[\]:;\"'|\\<>,.?/~`]", password): errors.append("Needs symbol.")
    if errors:
        return jsonify({'status': 'error', 'message': "Password validation failed: " + " ".join(errors)}), 400

    try:
        new_user = User(email=email, name=name, role=role)
        new_user.set_password(password) # Hashes password
        # judge_request_pending defaults to False in model
        db.session.add(new_user)
        db.session.commit()
        app.logger.info(f"Admin {g.current_user.id} added user {new_user.id} ({new_user.email}) with role '{role}'")
        # Return the newly created user data
        user_data = {
            'id': new_user.id, 'email': new_user.email, 'name': new_user.name,
            'role': new_user.role, 'judge_request_pending': new_user.judge_request_pending
        }
        return jsonify({'status': 'success', 'message': 'User added successfully.', 'user': user_data}), 201 # Created
    except ValueError as ve: # Catch password hash errors
        app.logger.error(f"Password validation error adding user {email} via admin: {ve}")
        return jsonify({'status': 'error', 'message': str(ve)}), 400
    except Exception as e:
        db.session.rollback()
        app.logger.error(f"Error adding user {email} via admin: {e}", exc_info=True)
        return jsonify({'status': 'error', 'message': 'Failed to add user due to an internal error.'}), 500

@app.route('/admin/users/<int:user_id>', methods=['PUT'])
@role_required('admin')
def update_user(user_id):
    """API endpoint for admin to update an existing user."""
    user = db.session.get(User, user_id)
    if not user:
        return jsonify({'status': 'error', 'message': 'User not found.'}), 404

    if not request.is_json: return jsonify({'status': 'error', 'message': 'Request must be JSON.'}), 415
    data = request.get_json()
    if not data:
        return jsonify({'status': 'error', 'message': 'No data provided for update.'}), 400

    try:
        updated = False
        # Update email if provided and different, checking for uniqueness (case-insensitive)
        if 'email' in data:
            new_email = data['email'].strip()
            if not new_email:
                 return jsonify({'status': 'error', 'message': 'Email cannot be empty.'}), 400
            if not re.match(r"[^@]+@[^@]+\.[^@]+", new_email):
                 return jsonify({'status': 'error', 'message': 'Invalid email format.'}), 400
            # Check if email is changing and if the new one is already taken by another user
            if new_email.lower() != user.email.lower():
                if User.query.filter(db.func.lower(User.email) == db.func.lower(new_email), User.id != user_id).first():
                    return jsonify({'status': 'error', 'message': 'Email address is already in use by another user.'}), 409
                user.email = new_email
                updated = True

        # Update name if provided and different
        if 'name' in data:
            new_name = data['name'].strip()
            if not new_name:
                 return jsonify({'status': 'error', 'message': 'Name cannot be empty.'}), 400
            if len(new_name) > 50: # Check model length
                 return jsonify({'status': 'error', 'message': 'Name cannot exceed 50 characters.'}), 400
            if new_name != user.name:
                user.name = new_name
                updated = True

        # Update role if provided and different/valid
        if 'role' in data:
            new_role = data['role'].lower().strip()
            if not new_role:
                 return jsonify({'status': 'error', 'message': 'Role cannot be empty.'}), 400
            if new_role != user.role:
                if new_role not in ['admin', 'judge', 'user']:
                    return jsonify({'status': 'error', 'message': 'Invalid role specified.'}), 400
                # Prevent admin from demoting themselves inadvertently if they are the only admin
                if user.id == g.current_user.id and new_role != 'admin':
                     # Check if there are other admins before allowing self-demotion
                     other_admins = User.query.filter(User.role == 'admin', User.id != user.id).count()
                     if other_admins == 0:
                         return jsonify({'status': 'error', 'message': 'Cannot change role: You are the only administrator.'}), 403
                user.role = new_role
                # Clear pending flag if role changes away from 'user' where it's relevant
                if new_role != 'user': user.judge_request_pending = False
                updated = True

        # Update password if provided (non-empty)
        if 'password' in data and data['password']:
            new_password = data['password']
            # Password strength validation
            errors = []
            if len(new_password) < 12: errors.append("Password min 12 chars.")
            if not re.search(r"[A-Z]", new_password): errors.append("Needs uppercase.")
            if not re.search(r"[a-z]", new_password): errors.append("Needs lowercase.")
            if not re.search(r"[0-9]", new_password): errors.append("Needs number.")
            if not re.search(r"[!@#$%^&*()_+=\-{}\[\]:;\"'|\\<>,.?/~`]", new_password): errors.append("Needs symbol.")
            if errors: return jsonify({'status': 'error', 'message': "Password validation failed: " + " ".join(errors)}), 400
            user.set_password(new_password)
            updated = True

        # Explicitly handle judge_request_pending - Admin might need to clear it manually sometimes
        if 'judge_request_pending' in data and isinstance(data['judge_request_pending'], bool):
             if data['judge_request_pending'] != user.judge_request_pending:
                 user.judge_request_pending = data['judge_request_pending']
                 updated = True

        if updated:
            db.session.commit()
            app.logger.info(f"Admin {g.current_user.id} updated user {user_id}")
            # Return the updated user data
            user_data = {
                'id': user.id, 'email': user.email, 'name': user.name,
                'role': user.role, 'judge_request_pending': user.judge_request_pending
            }
            return jsonify({'status': 'success', 'message': 'User updated successfully.', 'user': user_data}), 200
        else:
             return jsonify({'status': 'info', 'message': 'No changes detected or applied.'}), 200 # Use 200 OK for info

    except ValueError as ve: # Catch password hash errors
        db.session.rollback()
        app.logger.error(f"Password validation error updating user {user_id} via admin: {ve}")
        return jsonify({'status': 'error', 'message': str(ve)}), 400
    except Exception as e:
        db.session.rollback()
        app.logger.error(f"Error updating user {user_id} by admin {g.current_user.id}: {e}", exc_info=True)
        return jsonify({'status': 'error', 'message': 'Failed to update user due to an internal error.'}), 500
# Keep ONE of these blocks, delete the other identical one

# ---- START OF BLOCK TO POTENTIALLY DELETE ----
@app.route('/admin/users/<int:user_id>', methods=['DELETE']) # <--- Look for this decorator
@role_required('admin')
def delete_user(user_id): # <--- And this function definition
    """API endpoint for admin to delete a user."""
    if g.current_user.id == user_id:
        return jsonify({'status': 'error', 'message': 'Cannot delete your own account using this function.'}), 403

    user = db.session.get(User, user_id)
    if not user:
        return jsonify({'status': 'error', 'message': 'User not found.'}), 404

    try:
        # Check for dependencies: Does this user (as a judge) have scores?
        score_count = user.judge_scores.count()
        if score_count > 0:
             app.logger.warning(f"Attempt to delete user {user_id} failed: User has {score_count} scores recorded.")
             # Provide a clearer message about dependency
             return jsonify({'status': 'error', 'message': f'Cannot delete user: They have {score_count} existing score(s) recorded. Please delete these scores first or reassign them if applicable.'}), 409 # Conflict

        user_email = user.email # Get email for logging before deletion
        db.session.delete(user)
        db.session.commit() # <--- Commit the deletion
        app.logger.info(f"Admin {g.current_user.id} deleted user {user_id} ({user_email})")
        return jsonify({'status': 'success', 'message': 'User deleted successfully.'}), 200
    except Exception as e:
        db.session.rollback()
        # --- Enhanced Logging ---
        app.logger.error(f"Error deleting user {user_id} by admin {g.current_user.id}. Exception: {type(e).__name__} - {e}", exc_info=True)
        # --- End Enhanced Logging ---
        # Determine if it was likely a constraint violation
        error_message = 'Failed to delete user due to an internal error.'
        if "constraint" in str(e).lower(): # Basic check for constraint keywords
             error_message = 'Failed to delete user, possibly due to related records (e.g., scores). Please check dependencies.'
        return jsonify({'status': 'error', 'message': error_message}), 500
# ---- END OF BLOCK TO POTENTIALLY DELETE ----

# --- Admin CRUD Operations (Projects) ---

@app.route('/admin/projects', methods=['POST'])
@role_required('admin')
def add_project():
    """API endpoint for admin to add a new project."""
    if not request.is_json: return jsonify({'status': 'error', 'message': 'Request must be JSON.'}), 415
    data = request.get_json()
    if not data: return jsonify({'status': 'error', 'message': 'Invalid JSON payload.'}), 400

    # Check presence and non-empty strings/null for required fields
    project_name = data.get('project_name', '').strip()
    group_id_str = str(data.get('group_id', '')).strip() # Read as string first for validation

    if not project_name or not group_id_str:
         return jsonify({'status': 'error', 'message': 'Missing or empty required fields: project_name, group_id.'}), 400

    try:
        group_id = int(group_id_str) # Validate group_id is integer
    except ValueError:
         return jsonify({'status': 'error', 'message': 'Group ID must be a whole number.'}), 400

    if len(project_name) > 100: # Match model
        return jsonify({'status': 'error', 'message': 'Project name cannot exceed 100 characters.'}), 400

    # Optional: Check for duplicate project name/group ID combo if needed
    existing = Projects.query.filter_by(project_name=project_name, group_id=group_id).first()
    if existing:
        app.logger.warning(f"Admin add project failed: Project '{project_name}' / Group {group_id} already exists (ID: {existing.project_id}).")
        return jsonify({'status': 'error', 'message': 'Project with the same name and group ID already exists.'}), 409 # Conflict

    try:
        new_project = Projects(
            project_name=project_name,
            group_id=group_id,
            description=data.get('description', '').strip() or None # Optional description, store NULL if empty
        )
        db.session.add(new_project)
        db.session.commit()
        app.logger.info(f"Admin {g.current_user.id} added project {new_project.project_id} ('{new_project.project_name}')")
        # Return newly created project data
        project_data = {
            'project_id': new_project.project_id, 'project_name': new_project.project_name,
            'group_id': new_project.group_id, 'description': new_project.description
        }
        return jsonify({'status': 'success', 'message': 'Project added successfully.', 'project': project_data}), 201 # Created
    except Exception as e:
        db.session.rollback()
        app.logger.error(f"Error adding project '{project_name}' via admin: {e}", exc_info=True)
        return jsonify({'status': 'error', 'message': 'Failed to add project due to an internal error.'}), 500

@app.route('/admin/projects/<int:project_id>', methods=['PUT'])
@role_required('admin')
def update_project(project_id):
    """API endpoint for admin to update an existing project."""
    project = db.session.get(Projects, project_id)
    if not project:
        return jsonify({'status': 'error', 'message': 'Project not found.'}), 404

    if not request.is_json: return jsonify({'status': 'error', 'message': 'Request must be JSON.'}), 415
    data = request.get_json()
    if not data:
        return jsonify({'status': 'error', 'message': 'No data provided for update.'}), 400

    try:
        updated = False
        new_name = project.project_name # Keep original values initially
        new_group_id = project.group_id
        new_desc = project.description

        # Update project_name if provided, not empty, and different
        if 'project_name' in data:
            name_val = data['project_name'].strip()
            if not name_val: return jsonify({'status': 'error', 'message': 'Project name cannot be empty.'}), 400
            if len(name_val) > 100: return jsonify({'status': 'error', 'message': 'Project name max 100 chars.'}), 400
            if name_val != project.project_name:
                 new_name = name_val
                 updated = True

        # Update group_id if provided and different
        if 'group_id' in data:
             group_id_str = str(data['group_id']).strip()
             if not group_id_str: return jsonify({'status': 'error', 'message': 'Group ID cannot be empty.'}), 400
             try:
                 group_id_val = int(group_id_str)
                 if group_id_val != project.group_id:
                      new_group_id = group_id_val
                      updated = True
             except ValueError:
                 return jsonify({'status': 'error', 'message': 'Group ID must be a whole number.'}), 400

        # Update description (allow empty string to clear it, store NULL)
        if 'description' in data: # Check if key exists, even if value is None/empty
             desc_val = data['description'].strip() if data['description'] is not None else ''
             # Store None if description is empty for consistency
             desc_db_val = desc_val if desc_val else None
             if desc_db_val != project.description:
                 new_desc = desc_db_val
                 updated = True

        if updated:
            # Optional: Check for duplicate name/group ID combo *before* commit if relevant fields changed
            if new_name != project.project_name or new_group_id != project.group_id:
                 existing = Projects.query.filter(
                     Projects.project_name == new_name,
                     Projects.group_id == new_group_id,
                     Projects.project_id != project_id # Exclude self
                 ).first()
                 if existing:
                      # Do not proceed with the update if it creates a conflict
                      return jsonify({'status': 'error', 'message': 'Update failed: Another project with the same name and group ID already exists.'}), 409

            # Apply the validated changes
            project.project_name = new_name
            project.group_id = new_group_id
            project.description = new_desc

            db.session.commit()
            app.logger.info(f"Admin {g.current_user.id} updated project {project_id}")
            project_data = {
                'project_id': project.project_id, 'project_name': project.project_name,
                'group_id': project.group_id, 'description': project.description
            }
            return jsonify({'status': 'success', 'message': 'Project updated successfully.', 'project': project_data}), 200
        else:
            return jsonify({'status': 'info', 'message': 'No changes detected or applied.'}), 200

    except Exception as e:
        db.session.rollback()
        app.logger.error(f"Error updating project {project_id} by admin {g.current_user.id}: {e}", exc_info=True)
        return jsonify({'status': 'error', 'message': 'Failed to update project due to an internal error.'}), 500

@app.route('/admin/projects/<int:project_id>', methods=['DELETE'])
@role_required('admin')
def delete_project(project_id):
    """API endpoint for admin to delete a project and its associated scores."""
    project = db.session.get(Projects, project_id)
    if not project:
        return jsonify({'status': 'error', 'message': 'Project not found.'}), 404

    try:
        # Scores associated with this project will be deleted automatically due to:
        # cascade="all, delete-orphan" on the Projects.scores relationship
        # and ondelete='CASCADE' on the Scores.project_id ForeignKey (SQL level cascade).
        # Count scores *before* deleting for logging purposes.
        score_count = project.scores.count() # Efficient count using lazy='dynamic'
        project_name = project.project_name # Get name for logging before deletion

        db.session.delete(project)
        db.session.commit()
        app.logger.info(f"Admin {g.current_user.id} deleted project {project_id} ('{project_name}') and its {score_count} associated scores.")
        return jsonify({'status': 'success', 'message': f'Project "{project_name}" and its {score_count} associated scores deleted successfully.'}), 200
    except Exception as e:
        db.session.rollback()
        app.logger.error(f"Error deleting project {project_id} by admin {g.current_user.id}: {e}", exc_info=True)
        return jsonify({'status': 'error', 'message': 'Failed to delete project due to an internal error.'}), 500

# --- Admin CRUD Operations (Scores) ---
# Note: Direct score manipulation by admin should be used cautiously (e.g., for corrections).

@app.route('/admin/scores', methods=['POST'])
@role_required('admin')
def add_score():
    """API endpoint for admin to manually add a score (use with caution)."""
    if not request.is_json: return jsonify({'status': 'error', 'message': 'Request must be JSON.'}), 415
    data = request.get_json()
    if not data: return jsonify({'status': 'error', 'message': 'Invalid JSON payload.'}), 400

    required = ['category', 'score_given', 'project_id', 'judge_id']
    if not all(k in data and data[k] is not None for k in required):
        return jsonify({'status': 'error', 'message': 'Missing required fields: category, score_given, project_id, judge_id.'}), 400

    try:
        category = str(data['category']).strip()
        score_given_str = str(data['score_given']).strip()
        project_id_str = str(data['project_id']).strip()
        judge_id_str = str(data['judge_id']).strip()

        if not category:
            return jsonify({'status': 'error', 'message': 'Score category cannot be empty.'}), 400
        if len(category) > 100: return jsonify({'status': 'error', 'message': 'Category max 100 chars.'}), 400

        # Validate numeric fields
        try:
             score_given = int(score_given_str)
             project_id = int(project_id_str)
             judge_id = int(judge_id_str)
        except ValueError:
             return jsonify({'status': 'error', 'message': 'Score, Project ID, and Judge ID must be valid whole numbers.'}), 400

        # Validate score range (consistent with submit_vote)
        MIN_SCORE = 1
        MAX_SCORE = 100
        if not MIN_SCORE <= score_given <= MAX_SCORE:
             return jsonify({'status': 'error', 'message': f'Score must be between {MIN_SCORE} and {MAX_SCORE}.'}), 400

        # Check if project and judge exist and judge has correct role
        project = db.session.get(Projects, project_id)
        judge = db.session.get(User, judge_id)
        if not project: return jsonify({'status': 'error', 'message': f'Project with ID {project_id} not found.'}), 404
        if not judge: return jsonify({'status': 'error', 'message': f'Judge (User) with ID {judge_id} not found.'}), 404
        if judge.role not in ['judge', 'admin']:
            return jsonify({'status': 'error', 'message': f'Selected user (ID: {judge_id}) does not have judge or admin role.'}), 400

        # Check for existing score (unique constraint) before adding
        existing_score = Scores.query.filter_by(category=category, project_id=project_id, judge_id=judge_id).first()
        if existing_score:
            return jsonify({'status': 'error', 'message': 'A score for this category, project, and judge already exists. Use PUT to update if needed.'}), 409 # Conflict

        new_score = Scores(
            category=category, score_given=score_given,
            project_id=project_id, judge_id=judge_id
            # timestamp defaults to utcnow
        )
        db.session.add(new_score)
        db.session.commit()
        app.logger.info(f"Admin {g.current_user.id} manually added score {new_score.score_id} (Proj:{project_id}, Judge:{judge_id}, Cat:{category})")

        # Return the newly created score data including related names for UI update
        score_data = {
            'score_id': new_score.score_id, 'category': new_score.category, 'score_given': new_score.score_given,
            'project_id': new_score.project_id, 'judge_id': new_score.judge_id,
            'project_name': project.project_name, 'judge_name': judge.name,
            'timestamp': new_score.timestamp.isoformat()
        }
        return jsonify({'status': 'success', 'message': 'Score added successfully.', 'score': score_data}), 201 # Created

    except Exception as e:
        db.session.rollback()
        app.logger.error(f"Error adding score via admin: {e}", exc_info=True)
        return jsonify({'status': 'error', 'message': 'Failed to add score due to an internal error.'}), 500

@app.route('/admin/scores/<int:score_id>', methods=['PUT'])
@role_required('admin')
def update_score(score_id):
    """API endpoint for admin to update an existing score (use with caution)."""
    score = db.session.get(Scores, score_id)
    if not score:
        return jsonify({'status': 'error', 'message': 'Score not found.'}), 404

    if not request.is_json: return jsonify({'status': 'error', 'message': 'Request must be JSON.'}), 415
    data = request.get_json()
    if not data:
        return jsonify({'status': 'error', 'message': 'No data provided for update.'}), 400

    try:
        updated = False
        # Store original state for unique check if combination changes
        original_tuple = (score.project_id, score.judge_id, score.category)

        # Prepare potential new values, validating along the way
        new_cat = score.category
        new_score_val = score.score_given
        new_proj_id = score.project_id
        new_judge_id = score.judge_id

        if 'category' in data:
            cat_val = str(data['category']).strip()
            if not cat_val: return jsonify({'status': 'error', 'message': 'Score category cannot be empty.'}), 400
            if len(cat_val) > 100: return jsonify({'status': 'error', 'message': 'Category max 100 chars.'}), 400
            if cat_val != new_cat:
                new_cat = cat_val
                updated = True

        if 'score_given' in data:
            try:
                score_val = int(str(data['score_given']).strip())
                MIN_SCORE = 1; MAX_SCORE = 100
                if not MIN_SCORE <= score_val <= MAX_SCORE:
                     return jsonify({'status': 'error', 'message': f'Score must be between {MIN_SCORE} and {MAX_SCORE}.'}), 400
                if score_val != new_score_val:
                    new_score_val = score_val
                    updated = True
            except ValueError:
                return jsonify({'status': 'error', 'message': 'Score must be a whole number.'}), 400

        if 'project_id' in data:
             try:
                 proj_id_val = int(str(data['project_id']).strip())
                 if proj_id_val != new_proj_id:
                     if not db.session.get(Projects, proj_id_val):
                         return jsonify({'status': 'error', 'message': f'Target Project (ID: {proj_id_val}) not found.'}), 404
                     new_proj_id = proj_id_val
                     updated = True
             except ValueError:
                 return jsonify({'status': 'error', 'message': 'Project ID must be a number.'}), 400

        if 'judge_id' in data:
            try:
                judge_id_val = int(str(data['judge_id']).strip())
                if judge_id_val != new_judge_id:
                    judge = db.session.get(User, judge_id_val)
                    if not judge: return jsonify({'status': 'error', 'message': f'Target Judge (User ID: {judge_id_val}) not found.'}), 404
                    if judge.role not in ['judge', 'admin']: return jsonify({'status': 'error', 'message': 'Target user does not have judge or admin role.'}), 400
                    new_judge_id = judge_id_val
                    updated = True
            except ValueError:
                 return jsonify({'status': 'error', 'message': 'Judge ID must be a number.'}), 400

        if updated:
            # Check for potential unique constraint violation BEFORE applying changes if combination changed
            new_tuple = (new_proj_id, new_judge_id, new_cat)
            if new_tuple != original_tuple:
                 existing = Scores.query.filter(
                     Scores.project_id == new_proj_id,
                     Scores.judge_id == new_judge_id,
                     Scores.category == new_cat,
                     Scores.score_id != score_id # Exclude self
                 ).first()
                 if existing:
                     return jsonify({'status': 'error', 'message': 'Updating score would create a duplicate entry for this project, judge, and category combination.'}), 409

            # Apply changes to the score object
            score.category = new_cat
            score.score_given = new_score_val
            score.project_id = new_proj_id
            score.judge_id = new_judge_id
            score.timestamp = datetime.utcnow() # Update timestamp on any change

            db.session.commit()
            app.logger.info(f"Admin {g.current_user.id} updated score {score_id}")

            # Re-fetch related names after commit, in case project/judge changed
            db.session.refresh(score) # Ensure relationship attributes are updated
            score_data = {
                'score_id': score.score_id, 'category': score.category, 'score_given': score.score_given,
                'project_id': score.project_id, 'judge_id': score.judge_id,
                'project_name': score.project.project_name if score.project else 'N/A',
                'judge_name': score.judge.name if score.judge else 'N/A',
                'timestamp': score.timestamp.isoformat()
            }
            return jsonify({'status': 'success', 'message': 'Score updated successfully.', 'score': score_data}), 200
        else:
            return jsonify({'status': 'info', 'message': 'No changes detected or applied.'}), 200

    except Exception as e:
        db.session.rollback()
        app.logger.error(f"Error updating score {score_id} by admin {g.current_user.id}: {e}", exc_info=True)
        return jsonify({'status': 'error', 'message': 'Failed to update score due to an internal error.'}), 500

@app.route('/admin/scores/<int:score_id>', methods=['DELETE'])
@role_required('admin')
def delete_score(score_id):
    """API endpoint for admin to delete a specific score."""
    score = db.session.get(Scores, score_id)
    if not score:
        return jsonify({'status': 'error', 'message': 'Score not found.'}), 404

    try:
        # Get details for logging before deleting
        details = f"Proj:{score.project_id}, Judge:{score.judge_id}, Cat:{score.category}"
        db.session.delete(score)
        db.session.commit()
        app.logger.info(f"Admin {g.current_user.id} deleted score {score_id} ({details})")
        return jsonify({'status': 'success', 'message': 'Score deleted successfully.'}), 200
    except Exception as e:
        db.session.rollback()
        app.logger.error(f"Error deleting score {score_id} by admin {g.current_user.id}: {e}", exc_info=True)
        return jsonify({'status': 'error', 'message': 'Failed to delete score due to an internal error.'}), 500

# --- Admin Data Export/Import ---

# Check if pandas and openpyxl are available for export/import routes
# Log warning if either is missing
PANDAS_ENABLED = pd is not None
OPENPYXL_ENABLED = openpyxl is not None
IMPORT_EXPORT_ENABLED = PANDAS_ENABLED and OPENPYXL_ENABLED

if not IMPORT_EXPORT_ENABLED:
    missing_libs = []
    if not PANDAS_ENABLED: missing_libs.append('pandas')
    if not OPENPYXL_ENABLED: missing_libs.append('openpyxl')
    app.logger.warning(f"Missing libraries required for Excel import/export: {', '.join(missing_libs)}. Import/export features will be disabled. Install with 'pip install pandas openpyxl'")

    # Define dummy routes if libraries are not installed
    @app.route('/admin/export/<path:export_type>')
    @role_required('admin')
    def export_disabled(export_type):
        flash(f"Excel export functionality requires 'pandas' and 'openpyxl' libraries to be installed.", "error")
        return redirect(url_for('admin_dashboard'))

    @app.route('/admin/import/<path:import_type>', methods=['POST'])
    @role_required('admin')
    def import_disabled(import_type):
        return jsonify({'status': 'error', 'message': f"Excel import functionality requires 'pandas' and 'openpyxl' libraries to be installed."}), 501 # Not Implemented

else: # Only define these routes if pandas and openpyxl are installed
    # --- Export Routes (Require pandas & openpyxl) ---
    @app.route('/admin/export/users')
    @role_required('admin')
    def export_users():
        try:
            users = User.query.order_by(User.name).all()
            # Include 'id' for potential re-import/update workflows
            data_to_export = [{
                'id': u.id, 'name': u.name, 'email': u.email, 'role': u.role,
                'judge_request_pending': u.judge_request_pending
            } for u in users]

            if not data_to_export:
                 flash("No users found to export.", "warning")
                 return redirect(url_for('admin_dashboard'))

            df = pd.DataFrame(data_to_export)
            # Create an in-memory Excel file
            output = io.BytesIO()
            with pd.ExcelWriter(output, engine='openpyxl') as writer:
                 # Write DataFrame to sheet named 'Users' without default pandas index
                 df.to_excel(writer, index=False, sheet_name='Users')
            output.seek(0) # Rewind the buffer to the beginning

            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            filename = f'owljudge_users_{timestamp}.xlsx'
            app.logger.info(f"Admin {g.current_user.id} exporting users to {filename}")
            return send_file(
                output,
                mimetype='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
                as_attachment=True,
                download_name=filename # Use download_name instead of attachment_filename (deprecated)
            )
        except Exception as e:
            app.logger.error(f"Error exporting users: {e}", exc_info=True)
            flash("An error occurred during user export.", "error")
            return redirect(url_for('admin_dashboard'))

    @app.route('/admin/export/projects')
    @role_required('admin')
    def export_projects():
        try:
            projects = Projects.query.order_by(Projects.project_name).all()
            # Include 'project_id' for potential re-import/update
            data_to_export = [{
                'project_id': p.project_id, 'project_name': p.project_name, 'group_id': p.group_id,
                'description': p.description
            } for p in projects]

            if not data_to_export:
                 flash("No projects found to export.", "warning")
                 return redirect(url_for('admin_dashboard'))

            df = pd.DataFrame(data_to_export)
            output = io.BytesIO()
            with pd.ExcelWriter(output, engine='openpyxl') as writer:
                df.to_excel(writer, index=False, sheet_name='Projects')
            output.seek(0)

            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            filename = f'owljudge_projects_{timestamp}.xlsx'
            app.logger.info(f"Admin {g.current_user.id} exporting projects to {filename}")
            return send_file(
                output,
                mimetype='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
                as_attachment=True,
                download_name=filename
            )
        except Exception as e:
            app.logger.error(f"Error exporting projects: {e}", exc_info=True)
            flash("An error occurred during project export.", "error")
            return redirect(url_for('admin_dashboard'))

    @app.route('/admin/export/scores')
    @role_required('admin')
    def export_scores():
        try:
            # Use joinedload for efficiency to avoid N+1 queries for project/judge names
            scores = db.session.query(Scores).options(
                db.joinedload(Scores.project),
                db.joinedload(Scores.judge)
            ).order_by(Scores.project_id, Scores.judge_id, Scores.category).all()

            # Include related names and IDs for clarity and potential re-import needs
            data_to_export = [{
                'score_id': s.score_id,
                'project_id': s.project_id,
                'project_name': s.project.project_name if s.project else 'N/A',
                'judge_id': s.judge_id,
                'judge_name': s.judge.name if s.judge else 'N/A',
                'judge_email': s.judge.email if s.judge else 'N/A', # Include judge email for easier lookup
                'category': s.category,
                'score_given': s.score_given,
                'timestamp': s.timestamp.strftime('%Y-%m-%d %H:%M:%S') if s.timestamp else None # Format timestamp
            } for s in scores]

            if not data_to_export:
                 flash("No scores found to export.", "warning")
                 return redirect(url_for('admin_dashboard'))

            df = pd.DataFrame(data_to_export)
            output = io.BytesIO()
            with pd.ExcelWriter(output, engine='openpyxl') as writer:
                df.to_excel(writer, index=False, sheet_name='Scores')
            output.seek(0)

            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            filename = f'owljudge_scores_{timestamp}.xlsx'
            app.logger.info(f"Admin {g.current_user.id} exporting scores to {filename}")
            return send_file(
                output,
                mimetype='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
                as_attachment=True,
                download_name=filename
            )
        except Exception as e:
            app.logger.error(f"Error exporting scores: {e}", exc_info=True)
            flash("An error occurred during score export.", "error")
            return redirect(url_for('admin_dashboard'))

    # --- Import Routes (Require pandas & openpyxl) ---

    @app.route('/admin/import/users', methods=['POST'])
    @role_required('admin')
    def import_users():
        if 'file' not in request.files:
            return jsonify({'status': 'error', 'message': 'No file part in the request.'}), 400
        file = request.files['file']
        if file.filename == '':
            return jsonify({'status': 'error', 'message': 'No file selected.'}), 400
        # Allow both xlsx and xls? Be explicit about format. Sticking to XLSX for simplicity.
        if not file.filename.lower().endswith('.xlsx'):
            return jsonify({'status': 'error', 'message': 'Invalid file type. Please upload an XLSX file.'}), 400

        try:
            # Read the first sheet by default
            df = pd.read_excel(file, engine='openpyxl', keep_default_na=False, dtype=str) # Read all as string initially
            # Expected columns (case-insensitive check, strip whitespace)
            # 'id' is optional (for updates), 'password' required only for *new* users
            required_cols = {'name', 'email', 'role'}
            actual_cols = {str(col).lower().strip() for col in df.columns}
            if not required_cols.issubset(actual_cols):
                 missing = required_cols - actual_cols
                 app.logger.error(f"User import failed: Missing columns {missing}")
                 return jsonify({'status': 'error', 'message': f'Missing required columns in Excel file: {", ".join(missing)}'}), 400

            # Normalize column names for consistent access
            df.columns = [str(col).lower().strip() for col in df.columns]

            # Data structures for processing
            errors = [] # List of error messages [(row_num, message), ...]
            users_to_add = [] # List of dicts for new users
            users_to_update = {} # Dict keyed by user ID: {user_id: {'data': {...}, 'row_num': row_num}}
            processed_emails = set() # Track emails *within the file* to prevent duplicates

            # --- Row-by-Row Validation and Preparation ---
            for index, row in df.iterrows():
                row_num = index + 2 # Excel row number (1-based + header)
                try:
                    # Read and clean data from the row (treat all as strings initially)
                    email_raw = row.get('email', '').strip()
                    name_raw = row.get('name', '').strip()
                    role_raw = row.get('role', '').strip().lower()
                    password_raw = row.get('password', '').strip() # Password not stripped generally, but maybe for empty check?
                    user_id_raw = row.get('id', '').strip() # Optional ID for updates

                    # --- Basic Row Validation ---
                    if not email_raw or not name_raw or not role_raw:
                        errors.append((row_num, "Skipping row due to missing required name, email, or role."))
                        continue
                    if len(name_raw) > 50:
                         errors.append((row_num, "Skipping row: Name exceeds 50 characters."))
                         continue
                    if len(email_raw) > 120:
                         errors.append((row_num, "Skipping row: Email exceeds 120 characters."))
                         continue
                    if not re.match(r"[^@]+@[^@]+\.[^@]+", email_raw):
                        errors.append((row_num, f"Skipping row due to invalid email format '{email_raw}'."))
                        continue
                    if role_raw not in ['user', 'judge', 'admin']:
                         errors.append((row_num, f"Skipping row due to invalid role '{role_raw}'. Must be user, judge, or admin."))
                         continue
                    # Prevent duplicate emails within the same import file (case-insensitive)
                    if email_raw.lower() in processed_emails:
                         errors.append((row_num, f"Skipping row due to duplicate email '{email_raw}' within the import file."))
                         continue
                    processed_emails.add(email_raw.lower())

                    # --- Determine Add vs Update ---
                    existing_user = None
                    user_id_int = None
                    is_update = False

                    if user_id_raw: # ID provided, potential update
                        try:
                            user_id_int = int(user_id_raw)
                            # Fetch user by ID to check existence
                            existing_user = db.session.get(User, user_id_int)
                            if not existing_user:
                                errors.append((row_num, f"User with specified ID {user_id_int} not found. Cannot update. Skipping row."))
                                continue
                            else:
                                is_update = True
                        except ValueError:
                            errors.append((row_num, f"Invalid ID '{user_id_raw}'. Must be a whole number. Skipping row."))
                            continue
                    else: # No ID provided, try finding by email for potential update or add new
                        existing_user = User.query.filter(db.func.lower(User.email) == db.func.lower(email_raw)).first()
                        if existing_user:
                             is_update = True
                             user_id_int = existing_user.id # Use the ID of the found user


                    # --- Process Based on Add/Update ---
                    if is_update and user_id_int:
                        # Prepare Update Data
                        update_data = {'name': name_raw, 'role': role_raw}
                        # Check for email change conflict only if email is actually changing
                        if email_raw.lower() != existing_user.email.lower():
                            # Check if the NEW email is already taken by ANOTHER user
                            if User.query.filter(db.func.lower(User.email) == db.func.lower(email_raw), User.id != user_id_int).first():
                                errors.append((row_num, f"Cannot update user {user_id_int}. Email '{email_raw}' is already in use by another user. Skipping update for this row."))
                                continue # Skip this row's update
                            update_data['email'] = email_raw # Include email in update data

                        # Include password only if provided in the sheet
                        if password_raw:
                            # Validate password strength for update
                            pw_errors = []
                            if len(password_raw) < 12: pw_errors.append("min 12 chars")
                            if not re.search(r"[A-Z]", password_raw): pw_errors.append("needs uppercase")
                            if not re.search(r"[a-z]", password_raw): pw_errors.append("needs lowercase")
                            if not re.search(r"[0-9]", password_raw): pw_errors.append("needs number")
                            if not re.search(r"[!@#$%^&*()_+=\-{}\[\]:;\"'|\\<>,.?/~`]", password_raw): pw_errors.append("needs symbol")
                            if pw_errors:
                                 errors.append((row_num, f"Password update ignored for user {user_id_int} (invalid: {', '.join(pw_errors)})."))
                                 # Don't skip entire row, just skip password update
                            else:
                                 update_data['password'] = password_raw # Store password to be hashed later

                        # Store update keyed by user ID, preventing multiple updates for same ID in one file
                        if user_id_int not in users_to_update:
                            users_to_update[user_id_int] = {'data': update_data, 'row_num': row_num}
                        else:
                            errors.append((row_num, f"Multiple updates specified for user ID {user_id_int} in the file. Using first encountered update only."))

                    elif not is_update: # Add New User
                        # Password is required for new users
                        if not password_raw:
                             errors.append((row_num, f"Password is required for new user '{email_raw}'. Skipping row."))
                             continue
                        # Check email uniqueness in DB again (should be covered by filter_by above, but belt-and-suspenders)
                        if User.query.filter(db.func.lower(User.email) == db.func.lower(email_raw)).first():
                             errors.append((row_num, f"Email '{email_raw}' already exists in the database. Skipping row."))
                             continue
                        # Validate password strength for new user
                        pw_errors = []
                        if len(password_raw) < 12: pw_errors.append("min 12 chars")
                        if not re.search(r"[A-Z]", password_raw): pw_errors.append("needs uppercase")
                        if not re.search(r"[a-z]", password_raw): pw_errors.append("needs lowercase")
                        if not re.search(r"[0-9]", password_raw): pw_errors.append("needs number")
                        if not re.search(r"[!@#$%^&*()_+=\-{}\[\]:;\"'|\\<>,.?/~`]", password_raw): pw_errors.append("needs symbol")
                        if pw_errors:
                             errors.append((row_num, f"Password for new user '{email_raw}' invalid ({', '.join(pw_errors)}). Skipping row."))
                             continue

                        new_user_data = {'email': email_raw, 'name': name_raw, 'role': role_raw, 'password': password_raw, 'row_num': row_num}
                        users_to_add.append(new_user_data)

                except Exception as e:
                    # Catch unexpected errors during row processing
                    app.logger.error(f"Unexpected error processing user import row {row_num}: {e}", exc_info=True)
                    errors.append((row_num, f"Unexpected error processing row - {e}. Skipping row."))

            # --- Perform Database Operations (Commit Once if Possible) ---
            added_count = 0
            updated_count = 0
            final_commit_error = None

            if not users_to_add and not users_to_update:
                 message = "User import finished. No valid users found to add or update." + (f" Found {len(errors)} issues." if errors else "")
                 status_code = 200
                 status_msg = 'warning' if errors else 'info'
                 return jsonify({'status': status_msg, 'message': message, 'errors': errors}), status_code

            try:
                # Process additions
                for data in users_to_add:
                    try:
                        new_user = User(email=data['email'], name=data['name'], role=data['role'])
                        new_user.set_password(data['password'])
                        db.session.add(new_user)
                        added_count += 1
                    except Exception as inner_e:
                        errors.append((data['row_num'], f"Error preparing user '{data['email']}' for addition: {inner_e}"))
                        # Do not commit if any addition preparation fails
                        raise ValueError("Error during user addition preparation.") from inner_e

                # Process updates
                for user_id, update_info in users_to_update.items():
                    try:
                        user_to_update = db.session.get(User, user_id) # Get user within this session context
                        if not user_to_update: # Should not happen if validation above worked, but safety check
                             errors.append((update_info['row_num'], f"User ID {user_id} disappeared before update. Skipping."))
                             continue

                        data = update_info['data']
                        # Prevent admin from demoting self if last admin
                        if user_to_update.id == g.current_user.id and data['role'] != 'admin':
                            other_admins = User.query.filter(User.role == 'admin', User.id != user_to_update.id).count()
                            if other_admins == 0:
                                errors.append((update_info['row_num'], f"Cannot change role for user ID {user_id}: This is the only administrator."))
                                # Skip applying changes for this user
                                continue

                        user_to_update.name = data['name']
                        user_to_update.role = data['role']
                        if 'email' in data: user_to_update.email = data['email']
                        if 'password' in data: user_to_update.set_password(data['password'])
                        # If role changed away from 'user', clear pending flag
                        if 'role' in data and data['role'] != 'user': user_to_update.judge_request_pending = False
                        # Note: We are not explicitly setting judge_request_pending=True via import here.

                        updated_count += 1
                    except Exception as inner_e:
                        errors.append((update_info['row_num'], f"Error preparing update for user ID {user_id}: {inner_e}"))
                        # Do not commit if any update preparation fails
                        raise ValueError("Error during user update preparation.") from inner_e

                # Attempt final commit only if no preparation errors occurred
                db.session.commit()
                app.logger.info(f"Admin {g.current_user.id} imported users. Added: {added_count}, Updated: {updated_count}, Errors/Skipped: {len(errors)}")
                message = f"User import finished. Added: {added_count}, Updated: {updated_count}."
                if errors:
                    message += f" Encountered {len(errors)} issues (see details)."
                    status_msg = 'warning'
                else:
                    status_msg = 'success'
                return jsonify({'status': status_msg, 'message': message, 'errors': errors}), 200

            except Exception as e:
                 db.session.rollback() # Rollback the entire transaction
                 final_commit_error = str(e)
                 app.logger.error(f"Database error during user import commit: {e}", exc_info=True)
                 # Add a general error message, keeping specific row errors if collected
                 errors.append(('N/A', f"Database error during final commit: {e}. No changes were saved."))
                 message = f"User import failed during database operation. Added: 0, Updated: 0. See errors for details."
                 return jsonify({'status': 'error', 'message': message, 'errors': errors}), 500

        except pd.errors.EmptyDataError:
            return jsonify({'status': 'error', 'message': 'The uploaded Excel file is empty or contains only headers.'}), 400
        except Exception as e:
            # Catch errors during file reading or initial processing
            db.session.rollback() # Rollback just in case
            app.logger.error(f"Error processing user import file '{file.filename}': {e}", exc_info=True)
            return jsonify({'status': 'error', 'message': f'Failed to process Excel file: {e}'}), 500

    @app.route('/admin/import/projects', methods=['POST'])
    @role_required('admin')
    def import_projects():
        if 'file' not in request.files: return jsonify({'status': 'error', 'message': 'No file part.'}), 400
        file = request.files['file']
        if file.filename == '': return jsonify({'status': 'error', 'message': 'No file selected.'}), 400
        if not file.filename.lower().endswith('.xlsx'): return jsonify({'status': 'error', 'message': 'Invalid file type (XLSX only).'}), 400

        try:
            df = pd.read_excel(file, engine='openpyxl', keep_default_na=False, dtype=str) # Read all as string
            required_cols = {'project_name', 'group_id'} # Description, project_id optional
            actual_cols = {str(col).lower().strip() for col in df.columns}
            if not required_cols.issubset(actual_cols):
                 missing = required_cols - actual_cols
                 return jsonify({'status': 'error', 'message': f'Missing required columns: {", ".join(missing)}'}), 400

            df.columns = [str(col).lower().strip() for col in df.columns]

            errors = []
            projects_to_add = []
            projects_to_update = {} # Keyed by project_id
            processed_name_group = set() # Track (name, group_id) combos in the file

            for index, row in df.iterrows():
                row_num = index + 2
                try:
                    project_name_raw = row.get('project_name', '').strip()
                    group_id_raw = row.get('group_id', '').strip()
                    description_raw = row.get('description', '') # Allow keeping None/empty as is initially
                    project_id_raw = row.get('project_id', '').strip()

                    # --- Basic Row Validation ---
                    if not project_name_raw or not group_id_raw:
                        errors.append((row_num, "Skipping row due to missing project_name or group_id."))
                        continue
                    if len(project_name_raw) > 100:
                        errors.append((row_num, f"Project name too long (max 100). Skipping row."))
                        continue
                    try:
                        group_id_int = int(group_id_raw)
                    except ValueError:
                        errors.append((row_num, f"Invalid group_id '{group_id_raw}'. Must be whole number. Skipping row."))
                        continue

                    # Clean description: Treat empty string as None for DB consistency
                    description_clean = description_raw.strip() if description_raw else None

                    # Prevent duplicate name/group combos *within the file*
                    name_group_key = (project_name_raw, group_id_int)
                    if name_group_key in processed_name_group:
                        errors.append((row_num, f"Duplicate Project Name/Group ID {name_group_key} in file. Skipping."))
                        continue
                    processed_name_group.add(name_group_key)

                    # --- Determine Add vs Update ---
                    existing_project = None
                    project_id_int = None
                    is_update = False

                    if project_id_raw: # ID provided, potential update
                        try:
                            project_id_int = int(project_id_raw)
                            existing_project = db.session.get(Projects, project_id_int)
                            if not existing_project:
                                errors.append((row_num, f"Project ID {project_id_int} not found. Cannot update. Skipping row."))
                                continue
                            else:
                                is_update = True
                        except ValueError:
                            errors.append((row_num, f"Invalid project_id '{project_id_raw}'. Skipping row."))
                            continue
                    else: # No ID, check if name/group combo exists for potential update (optional, safer to require ID for update)
                        # For simplicity, we'll only update if ID is provided. Otherwise, it's an Add attempt.
                        existing_project_by_name_group = Projects.query.filter_by(project_name=project_name_raw, group_id=group_id_int).first()
                        if existing_project_by_name_group:
                             # Found existing project by name/group, but no ID given in sheet. Treat as potential conflict/skip add.
                             errors.append((row_num, f"Project '{project_name_raw}' / Group {group_id_int} already exists (ID: {existing_project_by_name_group.project_id}) but no ID provided in sheet. Skipping row to avoid accidental duplication. Provide ID to update."))
                             continue


                    # --- Process ---
                    if is_update and project_id_int:
                        # Prepare Update Data
                        update_data = {'project_name': project_name_raw, 'group_id': group_id_int, 'description': description_clean}

                        # Check if update would conflict with another existing project (same name/group, different ID)
                        potential_conflict = Projects.query.filter(
                            Projects.project_name == project_name_raw,
                            Projects.group_id == group_id_int,
                            Projects.project_id != project_id_int # Exclude self
                        ).first()
                        if potential_conflict:
                             errors.append((row_num, f"Update failed: Another project (ID: {potential_conflict.project_id}) already has name '{project_name_raw}' and group ID {group_id_int}. Skipping update for project {project_id_int}."))
                             continue

                        # Store unique update instruction
                        if project_id_int not in projects_to_update:
                             projects_to_update[project_id_int] = {'data': update_data, 'row_num': row_num}
                        else:
                             errors.append((row_num, f"Multiple updates for project ID {project_id_int}. Using first one found."))

                    elif not is_update: # Add New Project (existing_project_by_name_group check handles case where name/group exists but no ID given)
                        # Add check again here to be absolutely sure before adding
                        if Projects.query.filter_by(project_name=project_name_raw, group_id=group_id_int).first():
                            errors.append((row_num, f"Project '{project_name_raw}' / Group {group_id_int} already exists in DB. Skipping add."))
                            continue

                        new_project_data = {
                            'project_name': project_name_raw, 'group_id': group_id_int,
                            'description': description_clean, 'row_num': row_num
                        }
                        projects_to_add.append(new_project_data)

                except Exception as e:
                    app.logger.error(f"Unexpected error processing project import row {row_num}: {e}", exc_info=True)
                    errors.append((row_num, f"Unexpected error processing row - {e}. Skipping."))

            # --- Perform Database Operations ---
            added_count = 0
            updated_count = 0
            if not projects_to_add and not projects_to_update:
                message = "Project import finished. No valid projects found to add or update." + (f" Found {len(errors)} issues." if errors else "")
                status_code = 200
                status_msg = 'warning' if errors else 'info'
                return jsonify({'status': status_msg, 'message': message, 'errors': errors}), status_code

            try:
                # Process additions
                for data in projects_to_add:
                    try:
                        new_project = Projects(project_name=data['project_name'], group_id=data['group_id'], description=data['description'])
                        db.session.add(new_project)
                        added_count += 1
                    except Exception as inner_e:
                        errors.append((data['row_num'], f"Error preparing project '{data['project_name']}' for addition: {inner_e}"))
                        raise ValueError("Error during project addition preparation.") from inner_e

                # Process updates
                for proj_id, update_info in projects_to_update.items():
                    try:
                        project_to_update = db.session.get(Projects, proj_id)
                        if not project_to_update: continue # Should be caught earlier

                        data = update_info['data']
                        project_to_update.project_name = data['project_name']
                        project_to_update.group_id = data['group_id']
                        project_to_update.description = data['description'] # Already cleaned description
                        updated_count += 1
                    except Exception as inner_e:
                        errors.append((update_info['row_num'], f"Error preparing update for project ID {proj_id}: {inner_e}"))
                        raise ValueError("Error during project update preparation.") from inner_e

                # Final commit
                db.session.commit()
                app.logger.info(f"Admin {g.current_user.id} imported projects. Added: {added_count}, Updated: {updated_count}, Errors/Skipped: {len(errors)}")
                message = f"Project import finished. Added: {added_count}, Updated: {updated_count}."
                if errors:
                     message += f" Encountered {len(errors)} issues (see details)."
                     status_msg = 'warning'
                else:
                     status_msg = 'success'
                return jsonify({'status': status_msg, 'message': message, 'errors': errors}), 200

            except Exception as e:
                 db.session.rollback()
                 app.logger.error(f"Database error during project import commit: {e}", exc_info=True)
                 errors.append(('N/A', f"Database error during final commit: {e}. No changes were saved."))
                 message = f"Project import failed during database operation. Added: 0, Updated: 0. See errors for details."
                 return jsonify({'status': 'error', 'message': message, 'errors': errors}), 500

        except pd.errors.EmptyDataError:
            return jsonify({'status': 'error', 'message': 'The uploaded Excel file is empty or contains only headers.'}), 400
        except Exception as e:
            db.session.rollback()
            app.logger.error(f"Error processing project import file '{file.filename}': {e}", exc_info=True)
            return jsonify({'status': 'error', 'message': f'Failed to process Excel file: {e}'}), 500


# --- Utility and Error Handling ---

@app.route('/health')
def health_check():
    """Basic health check endpoint."""
    # Could add DB connection check here if needed
    try:
        # A lightweight query to check DB connection
        db.session.execute(db.text('SELECT 1'))
        return jsonify(status="ok"), 200
    except Exception as e:
        app.logger.error(f"Health check failed: Database connection error - {e}", exc_info=True)
        return jsonify(status="error", message="Database connection failed"), 503 # Service Unavailable

@app.route('/debug-info') # Example debug route - REMOVE/PROTECT IN PRODUCTION
@role_required('admin') # Protect this route
def debug_info():
    """Debug route to inspect session, user, config. PROTECTED."""
    # This route is already protected by @role_required('admin')
    # Optionally, add an extra check for app.debug for more safety
    # if not app.debug:
    #    return "Debug endpoint disabled in production environment", 403

    # Be careful what you expose here, even for admin
    info = {
        'session': dict(session),
        'g.current_user_id': g.current_user.id if g.current_user else None,
        'g.current_user_role': g.current_user.role if g.current_user else None,
        'config': { # Only expose non-sensitive config keys
            'SQLALCHEMY_DATABASE_URI': app.config.get('SQLALCHEMY_DATABASE_URI'),
            'SESSION_TYPE': app.config.get('SESSION_TYPE'),
            'SESSION_FILE_DIR': app.config.get('SESSION_FILE_DIR'),
            'PERMANENT_SESSION_LIFETIME': str(app.config.get('PERMANENT_SESSION_LIFETIME')),
            'IMPORT_EXPORT_ENABLED': IMPORT_EXPORT_ENABLED,
            'DEBUG': app.debug,
        },
        'request_headers': dict(request.headers),
    }
    return jsonify(info)

@app.errorhandler(404)
def page_not_found(e):
    """Custom 404 error handler."""
    # Log the error including the path that wasn't found
    app.logger.info(f"404 Not Found: {request.path} (Referrer: {request.referrer})")
    # Return JSON if client primarily accepts JSON
    if request.accept_mimetypes.accept_json and not request.accept_mimetypes.accept_html:
        return jsonify(status="error", error="Not Found", message=f"The requested URL {request.path} was not found on this server."), 404
    # Otherwise, render the HTML template (assuming it exists now)
    return render_template('404.html'), 404

@app.errorhandler(403)
def forbidden(e):
    """Custom 403 error handler."""
    user_info = f"User {g.current_user.id} ({g.current_user.email})" if g.current_user else "Unauthenticated user"
    app.logger.warning(f"403 Forbidden: {user_info} attempted to access {request.path}")
    if request.accept_mimetypes.accept_json and not request.accept_mimetypes.accept_html:
        return jsonify(status="error", error="Forbidden", message="You do not have permission to access this resource."), 403
    flash("You do not have permission to access this page.", "danger")
    # Redirect to index or login depending on if user is logged in
    return redirect(url_for('login' if g.current_user is None else 'index'))

@app.errorhandler(500)
def internal_server_error(e):
    """Custom 500 error handler for Werkzeug/Flask/App exceptions."""
    # Log the full error with traceback
    # The original exception 'e' might be a Werkzeug HTTP exception
    original_exception = getattr(e, 'original_exception', e)
    app.logger.error(f"500 Internal Server Error: {original_exception} for request {request.path}", exc_info=True)
    # Rollback potentially broken database transactions
    try:
        db.session.rollback()
        app.logger.info("Rolled back database session due to internal server error.")
    except Exception as rollback_err:
         app.logger.error(f"Error during database rollback after 500 error: {rollback_err}", exc_info=True)

    if request.accept_mimetypes.accept_json and not request.accept_mimetypes.accept_html:
        return jsonify(status="error", error="Internal Server Error", message="An unexpected error occurred on the server. Please try again later."), 500
    # Render a user-friendly error page (assuming 500.html exists)
    return render_template('500.html'), 500

# --- REMOVE Generic Exception handler IF using specific 500 handler ---
# Using both @app.errorhandler(500) and @app.errorhandler(Exception) can sometimes lead to
# unexpected behavior depending on the exception type. The 500 handler should catch most
# application-level errors that aren't specific HTTP exceptions.
# If you need extremely broad capture, keep it, but ensure it doesn't mask specific handlers.
# Let's remove it for now as the 500 handler is usually sufficient.
# @app.errorhandler(Exception)
# def unhandled_exception(e): ...

# --- Initialization and Test Data ---
def create_test_data(force_create=False):
    """Function to populate database with initial test data if needed."""
    # Ensure this runs within an app context
    with app.app_context():
        app.logger.info("Checking/Creating test data...")
        changes_made = False
        try:
            # --- Create Admin ---
            admin_email = 'admin@example.com'
            admin_pass = 'adminpass' # Use a strong password!
            admin_exists = User.query.filter(db.func.lower(User.email) == db.func.lower(admin_email)).first()
            if not admin_exists or force_create:
                 if admin_exists: db.session.delete(admin_exists) # Delete if forcing creation
                 admin = User(email=admin_email, name='Admin User', role='admin')
                 admin.set_password(admin_pass)
                 db.session.add(admin)
                 app.logger.info(f" -> {'Updated' if admin_exists else 'Created'} test admin: {admin_email} / {admin_pass}")
                 changes_made = True

            # --- Create Judge ---
            judge_email = 'judge@example.com'
            judge_pass = 'judgepass' # Use a strong password!
            judge_exists = User.query.filter(db.func.lower(User.email) == db.func.lower(judge_email)).first()
            if not judge_exists or force_create:
                if judge_exists: db.session.delete(judge_exists)
                judge = User(email=judge_email, name='Judge User', role='judge')
                judge.set_password(judge_pass)
                db.session.add(judge)
                app.logger.info(f" -> {'Updated' if judge_exists else 'Created'} test judge: {judge_email} / {judge_pass}")
                changes_made = True

            # --- Create Regular User ---
            user_email = 'user@example.com'
            user_pass = 'userpass' # Use a strong password!
            user_exists = User.query.filter(db.func.lower(User.email) == db.func.lower(user_email)).first()
            if not user_exists or force_create:
                if user_exists: db.session.delete(user_exists)
                user = User(email=user_email, name='Regular User', role='user')
                user.set_password(user_pass)
                db.session.add(user)
                app.logger.info(f" -> {'Updated' if user_exists else 'Created'} test user: {user_email} / {user_pass}")
                changes_made = True

            # --- Create User requesting judge role ---
            req_email = 'request@example.com'
            req_pass = 'requestpass!' # Use a strong password!
            req_exists = User.query.filter(db.func.lower(User.email) == db.func.lower(req_email)).first()
            if not req_exists or force_create:
                 if req_exists: db.session.delete(req_exists)
                 req_user = User(email=req_email, name='Requesting User', role='user', judge_request_pending=True)
                 req_user.set_password(req_pass)
                 db.session.add(req_user)
                 app.logger.info(f" -> {'Updated' if req_exists else 'Created'} test user requesting judge role: {req_email} / {req_pass}")
                 changes_made = True

            # --- Create Test Projects ---
            if Projects.query.count() < 3:
                projects_to_add = [
                    {"project_name": "Project Alpha", "group_id": 101, "description": "Innovative project using AI."},
                    {"project_name": "Project Beta", "group_id": 102,
                     "description": "Engaging web application for social good."},
                    {"project_name": "Project Gamma", "group_id": 103,
                     "description": "Technical hardware project with IoT integration."}
                ]
            # Only add if fewer than 3 projects exist OR force_create is True
            if Projects.query.count() < len(projects_to_add) or force_create:
                 # If forcing, remove existing projects first? Or just add more?
                 # Let's just add if needed, checking uniqueness by name/group.
                 for p_data in projects_to_add:
                      if not Projects.query.filter_by(project_name=p_data["project_name"], group_id=p_data["group_id"]).first():
                           project = Projects(**p_data)
                           db.session.add(project)
                           app.logger.info(f" -> Created test project: {p_data['project_name']}")
                           changes_made = True

            # Commit all changes at once
            if changes_made:
                db.session.commit()
                app.logger.info("Test data changes committed.")
            else:
                app.logger.info("No new test data needed.")

        except Exception as e:
            db.session.rollback()
            print(f"Error creating/updating test data: {e}")
            app.logger.error(f"Error creating/updating test data: {e}", exc_info=True)
        finally:
            app.logger.info("-" * 20)

# --- Removed Student/Group CRUD operations as models are not defined ---
# Routes for /admin/students/<id> and /admin/groups/<id> were removed previously.

# --- Main Execution ---
if __name__ == '__main__':
    # Perform initialization within app context
    with app.app_context():
        app.logger.info("Initializing database...")
        try:
            # Create tables if they don't exist (idempotent)
            db.create_all()
            app.logger.info("Database tables created/verified.")
            # Populate with test data if needed
            # Set force_create=True only during development if you want to reset test data on each run
            create_test_data(force_create=False)
        except Exception as e:
            print(f"FATAL: Database initialization failed: {e}")
            app.logger.critical(f"Database initialization failed: {e}", exc_info=True)
            # Exit if DB init fails? Or let Flask handle it? Depends on deployment.
            # exit(1) # Consider exiting in critical failure scenarios

    # Run the Flask development server
    # Use environment variables for host, port, and debug mode for flexibility.
    run_host = os.environ.get('FLASK_RUN_HOST', '127.0.0.1')
    # Ensure port is an integer
    try:
        run_port = int(os.environ.get('FLASK_RUN_PORT', 5000))
    except ValueError:
        run_port = 5000
        app.logger.warning(f"Invalid FLASK_RUN_PORT environment variable. Using default port {run_port}.")

    # Check FLASK_DEBUG env variable; default to True for development if not set
    debug_mode_env = os.environ.get('FLASK_DEBUG', '1') # Default to '1' (True) if not set
    debug_mode = debug_mode_env.lower() in ('true', '1', 't', 'yes')

    app.logger.info(f"Starting Flask server on http://{run_host}:{run_port} (Debug: {debug_mode})")
    # Pass debug=debug_mode to app.run()
    app.run(host=run_host, port=run_port, debug=debug_mode)