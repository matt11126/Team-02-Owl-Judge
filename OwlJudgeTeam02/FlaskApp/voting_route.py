from judge.models.judge import app
from flask import render_template, session, redirect, url_for, flash

@app.route('/voting')
def voting():
    # Ensure the user is logged in by checking the session.
    if 'user' not in session:
        flash("Please log in to access the voting page.", "error")
        return redirect(url_for('login'))
    # Optionally assign the role "FlaskApp" (this can also be handled client-side)
    session['role'] = 'FlaskApp'
    return render_template('HTML/templates/voting.html')
