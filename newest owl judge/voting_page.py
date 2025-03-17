from app import app
from flask import render_template, session, redirect, url_for, flash

@app.route('/voting')
def voting():
    # Check if the user is logged in by looking for 'user' in session
    if 'user' not in session:
        flash("Please log in to access the voting page.", "error")
        return redirect(url_for('login'))
    # Optionally assign a judge role (stored in session), though not strictly required
    session['role'] = 'judge'
    # Render the new voting.html file you added
    return render_template('HTML/templates/voting.html')
