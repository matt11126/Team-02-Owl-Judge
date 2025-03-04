from flask import Flask, render_template

app = Flask(__name__)


@app.route('/')
def hello_world():  # put application's code here


    return render_template('index.html')
    return render_template('about_us.html.html')
    return render_template('contact_us.html')
    return render_template('dashboard.html')
    return render_template('login.html')
    return render_template('profile.html')
    return render_template('vote_casting.html')


if __name__ == '__main__':
    app.run()
