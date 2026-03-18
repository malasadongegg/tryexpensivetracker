from flask import Flask, render_template, request, redirect, session, flash, url_for
from werkzeug.security import generate_password_hash, check_password_hash
from functools import wraps
from datetime import datetime, timedelta
import psycopg2
import psycopg2.extras
import os
from dotenv import load_dotenv

load_dotenv()

template_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'templates')
app = Flask(__name__, template_folder=template_path)
app.secret_key = os.getenv("SECRET_KEY", "fallback-secret-key")


# ── Database ──────────────────────────────────────────────────────────────────
def get_db():
    return psycopg2.connect(
        os.getenv("DATABASE_URL"),
        cursor_factory=psycopg2.extras.RealDictCursor
    )


# ── Auth guard ────────────────────────────────────────────────────────────────
def login_required(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        if 'user_id' not in session:
            return redirect(url_for('login'))
        return f(*args, **kwargs)
    return decorated


# ── Helpers ───────────────────────────────────────────────────────────────────
def enrich_subs(subs):
    today = datetime.today().date()
    soon  = today + timedelta(days=7)
    for sub in subs:
        bd = sub['next_billing_date']
        if isinstance(bd, str):
            bd = datetime.strptime(bd, '%Y-%m-%d').date()
        sub['due_soon'] = today <= bd <= soon
        sub['overdue']  = bd < today
    return subs


def calc_monthly_total(subs):
    total = 0.0
    for sub in subs:
        p = float(sub['price'])
        if sub['billing_cycle'] == 'yearly':
            total += p / 12
        elif sub['billing_cycle'] == 'weekly':
            total += p * 4.33
        else:
            total += p
    return round(total, 2)


def calc_annual_total(subs):
    total = 0.0
    for sub in subs:
        p = float(sub['price'])
        if sub['billing_cycle'] == 'yearly':
            total += p
        elif sub['billing_cycle'] == 'weekly':
            total += p * 52
        else:
            total += p * 12
    return round(total, 2)


# ── Register ──────────────────────────────────────────────────────────────────
@app.route('/register', methods=['GET', 'POST'])
def register():
    if 'user_id' in session:
        return redirect(url_for('dashboard'))

    if request.method == 'POST':
        username = request.form['username'].strip()
        password = request.form['password']
        confirm  = request.form['confirm_password']

        if not username or not password:
            flash('All fields are required.', 'error')
            return render_template('register.html')
        if password != confirm:
            flash('Passwords do not match.', 'error')
            return render_template('register.html')
        if len(password) < 6:
            flash('Password must be at least 6 characters.', 'error')
            return render_template('register.html')

        db     = get_db()
        cursor = db.cursor()
        cursor.execute("SELECT id FROM users WHERE username = %s", (username,))
        if cursor.fetchone():
            flash('Username already taken.', 'error')
            cursor.close(); db.close()
            return render_template('register.html')

        cursor.execute(
            "INSERT INTO users (username, password) VALUES (%s, %s)",
            (username, generate_password_hash(password))
        )
        db.commit()
        cursor.close(); db.close()
        flash('Account created! Please log in.', 'success')
        return redirect(url_for('login'))

    return render_template('register.html')


# ── Login ─────────────────────────────────────────────────────────────────────
@app.route('/login', methods=['GET', 'POST'])
def login():
    if 'user_id' in session:
        return redirect(url_for('dashboard'))

    if request.method == 'POST':
        username = request.form['username'].strip()
        password = request.form['password']

        db     = get_db()
        cursor = db.cursor()
        cursor.execute("SELECT * FROM users WHERE username = %s", (username,))
        user = cursor.fetchone()
        cursor.close(); db.close()

        if user and check_password_hash(user['password'], password):
            session['user_id']  = user['id']
            session['username'] = user['username']
            return redirect(url_for('dashboard'))

        flash('Invalid username or password.', 'error')

    return render_template('login.html')


# ── Logout ────────────────────────────────────────────────────────────────────
@app.route('/logout')
def logout():
    session.clear()
    return redirect(url_for('login'))


# ── Dashboard ─────────────────────────────────────────────────────────────────
@app.route('/')
@login_required
def dashboard():
    db     = get_db()
    cursor = db.cursor()
    cursor.execute(
        "SELECT * FROM subscriptions WHERE user_id = %s ORDER BY next_billing_date ASC",
        (session['user_id'],)
    )
    subs = cursor.fetchall()
    cursor.close(); db.close()

    subs           = enrich_subs(subs)
    total          = calc_monthly_total(subs)
    upcoming_count = sum(1 for s in subs if s['due_soon'])

    return render_template('dashboard.html',
        subs=subs, total=total, upcoming_count=upcoming_count)


# ── Subscriptions ─────────────────────────────────────────────────────────────
@app.route('/subscriptions')
@login_required
def subscriptions():
    db     = get_db()
    cursor = db.cursor()
    cursor.execute(
        "SELECT * FROM subscriptions WHERE user_id = %s ORDER BY next_billing_date ASC",
        (session['user_id'],)
    )
    subs = cursor.fetchall()
    cursor.close(); db.close()

    subs           = enrich_subs(subs)
    total          = calc_monthly_total(subs)
    annual         = calc_annual_total(subs)
    upcoming_count = sum(1 for s in subs if s['due_soon'])

    return render_template('activesubs.html',
        subs=subs, total=total, annual=annual, upcoming_count=upcoming_count)


# ── Add ───────────────────────────────────────────────────────────────────────
@app.route('/add-subscription', methods=['POST'])
@login_required
def add_subscription():
    billing_date = request.form['next_billing_date']
    if datetime.strptime(billing_date, '%Y-%m-%d').date() < datetime.today().date():
        flash('Billing date cannot be in the past.', 'error')
        return redirect(url_for('subscriptions'))

    db     = get_db()
    cursor = db.cursor()
    cursor.execute("""
        INSERT INTO subscriptions (user_id, name, price, billing_cycle, next_billing_date, category)
        VALUES (%s, %s, %s, %s, %s, %s)
    """, (
        session['user_id'],
        request.form['name'].strip(),
        request.form['price'],
        request.form['billing_cycle'],
        billing_date,
        request.form.get('category', 'General'),
    ))
    db.commit()
    cursor.close(); db.close()
    return redirect(url_for('subscriptions'))


# ── Edit ──────────────────────────────────────────────────────────────────────
@app.route('/edit-subscription/<int:id>', methods=['POST'])
@login_required
def edit_subscription(id):
    billing_date = request.form['next_billing_date']
    if datetime.strptime(billing_date, '%Y-%m-%d').date() < datetime.today().date():
        flash('Billing date cannot be in the past.', 'error')
        return redirect(url_for('subscriptions'))

    db     = get_db()
    cursor = db.cursor()
    cursor.execute("""
        UPDATE subscriptions
        SET name=%s, price=%s, billing_cycle=%s, next_billing_date=%s, category=%s
        WHERE id=%s AND user_id=%s
    """, (
        request.form['name'].strip(),
        request.form['price'],
        request.form['billing_cycle'],
        billing_date,
        request.form.get('category', 'General'),
        id,
        session['user_id'],
    ))
    db.commit()
    cursor.close(); db.close()
    return redirect(url_for('subscriptions'))


# ── Delete ────────────────────────────────────────────────────────────────────
@app.route('/delete-subscription/<int:id>', methods=['POST'])
@login_required
def delete_subscription(id):
    db     = get_db()
    cursor = db.cursor()
    cursor.execute(
        "DELETE FROM subscriptions WHERE id=%s AND user_id=%s",
        (id, session['user_id'])
    )
    db.commit()
    cursor.close(); db.close()
    return redirect(url_for('subscriptions'))


# ── Insights ──────────────────────────────────────────────────────────────────
@app.route('/insights')
@login_required
def insights():
    db     = get_db()
    cursor = db.cursor()
    cursor.execute(
        "SELECT * FROM subscriptions WHERE user_id = %s",
        (session['user_id'],)
    )
    subs = cursor.fetchall()
    cursor.close(); db.close()

    by_category = {}
    for sub in subs:
        cat = sub['category'] or 'General'
        p   = float(sub['price'])
        if sub['billing_cycle'] == 'yearly':
            p /= 12
        elif sub['billing_cycle'] == 'weekly':
            p *= 4.33
        by_category[cat] = round(by_category.get(cat, 0) + p, 2)

    today  = datetime.today()
    months = []
    for i in range(6):
        m = (today.month - 1 + i) % 12 + 1
        y = today.year + ((today.month - 1 + i) // 12)
        months.append(datetime(y, m, 1).strftime('%b %Y'))

    subs_enriched  = enrich_subs(subs)
    total          = calc_monthly_total(subs)
    annual         = calc_annual_total(subs)
    upcoming_count = sum(1 for s in subs_enriched if s['due_soon'])

    return render_template('insights.html',
        subs=subs_enriched,
        by_category=by_category,
        months=months,
        total=total,
        annual=annual,
        upcoming_count=upcoming_count,
    )



# ── Profile ───────────────────────────────────────────────────────────────────
@app.route('/profile')
@login_required
def profile():
    db     = get_db()
    cursor = db.cursor()
    cursor.execute("SELECT * FROM users WHERE id = %s", (session['user_id'],))
    user = cursor.fetchone()
    cursor.close(); db.close()
    return render_template('profile.html', user=user)


@app.route('/profile/update-username', methods=['POST'])
@login_required
def update_username():
    new_username = request.form['username'].strip()
    if not new_username:
        flash('Username cannot be empty.', 'error')
        return redirect(url_for('profile'))

    db     = get_db()
    cursor = db.cursor()
    cursor.execute("SELECT id FROM users WHERE username = %s AND id != %s", (new_username, session['user_id']))
    if cursor.fetchone():
        flash('Username already taken.', 'error')
        cursor.close(); db.close()
        return redirect(url_for('profile'))

    cursor.execute("UPDATE users SET username = %s WHERE id = %s", (new_username, session['user_id']))
    db.commit()
    cursor.close(); db.close()
    session['username'] = new_username
    flash('Username updated successfully.', 'success')
    return redirect(url_for('profile'))


@app.route('/profile/update-password', methods=['POST'])
@login_required
def update_password():
    current  = request.form['current_password']
    new_pass = request.form['new_password']
    confirm  = request.form['confirm_password']

    db     = get_db()
    cursor = db.cursor()
    cursor.execute("SELECT * FROM users WHERE id = %s", (session['user_id'],))
    user = cursor.fetchone()

    if not check_password_hash(user['password'], current):
        flash('Current password is incorrect.', 'error')
        cursor.close(); db.close()
        return redirect(url_for('profile'))

    if new_pass != confirm:
        flash('New passwords do not match.', 'error')
        cursor.close(); db.close()
        return redirect(url_for('profile'))

    if len(new_pass) < 6:
        flash('Password must be at least 6 characters.', 'error')
        cursor.close(); db.close()
        return redirect(url_for('profile'))

    cursor.execute("UPDATE users SET password = %s WHERE id = %s",
        (generate_password_hash(new_pass), session['user_id']))
    db.commit()
    cursor.close(); db.close()
    flash('Password updated successfully.', 'success')
    return redirect(url_for('profile'))


@app.route('/profile/delete-account', methods=['POST'])
@login_required
def delete_account():
    password = request.form['password']

    db     = get_db()
    cursor = db.cursor()
    cursor.execute("SELECT * FROM users WHERE id = %s", (session['user_id'],))
    user = cursor.fetchone()

    if not check_password_hash(user['password'], password):
        flash('Incorrect password.', 'error')
        cursor.close(); db.close()
        return redirect(url_for('profile'))

    cursor.execute("DELETE FROM users WHERE id = %s", (session['user_id'],))
    db.commit()
    cursor.close(); db.close()
    session.clear()
    return redirect(url_for('login'))



@app.route('/profile/update-color', methods=['POST'])
@login_required
def update_color():
    color = request.form.get('avatar_color', '#136dec')
    db     = get_db()
    cursor = db.cursor()
    cursor.execute("UPDATE users SET avatar_color = %s WHERE id = %s", (color, session['user_id']))
    db.commit()
    cursor.close(); db.close()
    flash('Avatar color updated.', 'success')
    return redirect(url_for('profile'))


if __name__ == '__main__':
    app.run(debug=True)