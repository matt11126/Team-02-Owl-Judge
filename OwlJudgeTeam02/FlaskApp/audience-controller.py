from flask import Flask, render_template, request, session, jsonify, flash, redirect, url_for
from werkzeug.security import generate_password_hash, check_password_hash

app = Flask(__name__)
app.secret_key = 'your_secret_key_here'  # Required for sessions & flash messages

# In-memory user store (replace with DB in production)
users = {}

@app.route('/')
def index():
    return render_template('HTML/templates/index.html')

@app.route('/about')
def about():
    return render_template('HTML/templates/about_us.html')

@app.route('/audience')
def audience():
    return render_template('HTML/templates/audience.html')

@app.route('/dashboard')
def dashboard():
    return render_template('HTML/templates/dashboard.html')

@app.route('/login')
def login():
    # If the user is already logged in, skip login page
    if 'user' in session:
        return redirect(url_for('index'))
    return render_template('HTML/templates/login.html')

@app.route('/signup')
def signup():
    # If the user is already logged in, skip signup page
    if 'user' in session:
        return redirect(url_for('index'))
    return render_template('HTML/templates/signup.html')

@app.route('/profile')
def profile():
    if 'user' not in session:
        return redirect(url_for('login'))
    return render_template('HTML/templates/profile.html')

@app.route('/contact')
def contact():
    # Make sure templates/HTML/contact_us.html actually exists
    return render_template('HTML/contact_us.html')

@app.route('/vote_casting')
def vote_casting():
    # This is your older voting page route
    if 'user' not in session:
        flash("Please log in to cast votes.", "error")
        return redirect(url_for('login'))
    return render_template('HTML/templates/vote_casting.html')

# ----- LOGIN POST -----
@app.route('/login', methods=['POST'])
def login_post():
    email = request.form.get('username')
    password = request.form.get('password')
    if email in users and check_password_hash(users[email]['password'], password):
        # Logged in
        session['user'] = users[email]['name']
        session['role'] = 'FlaskApp'  # By default, user is FlaskApp
        flash("Logged in successfully!", "success")

        # If it's an AJAX request:
        if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
            return jsonify({'success': True, 'message': 'Logged in successfully!'})
        return redirect(url_for('index'))
    else:
        # Invalid credentials
        flash("Invalid credentials", "error")
        if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
            return jsonify({'success': False, 'message': 'Invalid credentials'})
        return redirect(url_for('login'))

# ----- SIGNUP POST -----
@app.route('/signup', methods=['POST'])
def signup_post():
    email = request.form.get('signupUsername')
    password = request.form.get('signupPassword')
    if email in users:
        flash("Email already registered.", "error")
        if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
            return jsonify({'success': False, 'message': 'Email already registered'})
        return redirect(url_for('signup'))
    else:
        hashed_password = generate_password_hash(password)
        users[email] = {'password': hashed_password, 'name': email.split('@')[0]}
        session['user'] = users[email]['name']
        session['role'] = 'FlaskApp'
        flash("Signed up and logged in successfully!", "success")

        if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
            return jsonify({'success': True, 'message': 'Signed up and logged in successfully!'})
        return redirect(url_for('index'))

@app.route('/logout')
def logout():
    session.clear()
    flash("You have been logged out.", "success")
    return redirect(url_for('index'))

# Optionally, register blueprint for /voting
try:
    from voting_blueprint import voting_bp
    app.register_blueprint(voting_bp)
except ImportError:
    pass

if __name__ == '__main__':
    app.run(debug=True)
