from flask import Flask, render_template, request, session, jsonify, flash, redirect, url_for
from werkzeug.security import generate_password_hash, check_password_hash

app = Flask(__name__)
app.secret_key = 'your_secret_key_here'  # Required for session management and flash messages

# Dummy in-memory user store (replace with a database in production)
users = {}

# --------------------------
# NEW: Inject the logged_in user into every template.
@app.context_processor
def inject_user():
    return dict(logged_in=session.get('user'))
# --------------------------

@app.route('/')
def index():
    return render_template('HTML/index.html')

@app.route('/about')
def about():
    return render_template('HTML/about_us.html')

@app.route('/audience')
def audience():
    return render_template('HTML/audience.html')

@app.route('/dashboard')
def dashboard():
    return render_template('HTML/dashboard.html')

@app.route('/login')
def login():
    return render_template('HTML/login.html')

@app.route('/profile')
def profile():
    return render_template('HTML/profile.html')

@app.route('/signup')
def signup():
    return render_template('HTML/signup.html')

@app.route('/vote_casting')
def vote_casting():
    return render_template('HTML/vote_casting.html')

@app.route('/contact')
def contact():
    return render_template('HTML/contact_us.html')

# Handle login form submission
@app.route('/login', methods=['POST'])
def login_post():
    email = request.form.get('username')  # Assuming the login form has a field named 'username'
    password = request.form.get('password')  # Assuming the login form has a field named 'password'

    if email in users and check_password_hash(users[email]['password'], password):
        session['user'] = users[email]['name']  # Store user in session
        return jsonify({'success': True, 'message': 'Logged in successfully!', 'user': users[email]['name']})
    else:
        return jsonify({'success': False, 'message': 'Invalid credentials'})

# Handle signup form submission
@app.route('/signup', methods=['POST'])
def signup_post():
    email = request.form.get('signupUsername')  # Assuming the signup form has a field named 'signupUsername'
    password = request.form.get('signupPassword')  # Assuming the signup form has a field named 'signupPassword'

    if email in users:
        return jsonify({'success': False, 'message': 'Email already registered'})
    else:
        hashed_password = generate_password_hash(password)
        users[email] = {'password': hashed_password, 'name': email.split('@')[0]}  # Add new user with hashed password
        return jsonify({'success': True, 'message': 'Account created successfully!'})

# Handle logout
@app.route('/logout')
def logout():
    session.pop('user', None)  # Clear the session
    flash('You have been logged out.', 'success')
    return redirect(url_for('index'))

if __name__ == '__main__':
    app.run(debug=True)
