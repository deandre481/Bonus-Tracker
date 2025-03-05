# main.py
from flask import Flask, render_template, request, redirect, url_for, session, flash
import firebase_admin
from firebase_admin import credentials, firestore
import datetime

app = Flask(__name__)
app.secret_key = 'your_secret_key'  # Replace with a strong, unique secret key

# Initialize Firebase Admin SDK using your service account key
cred = credentials.Certificate('serviceAccountKey.json')
firebase_admin.initialize_app(cred)
db = firestore.client()

# -------------------------------------------------------------------
# Helper Function: Get list of admin users for dropdowns
# -------------------------------------------------------------------
def get_admins():
    admins = []
    users_ref = db.collection('users')
    query = users_ref.where('role', '==', 'admin').stream()
    for doc in query:
        data = doc.to_dict()
        data['id'] = doc.id
        admins.append(data)
    return admins

# -------------------------------------------------------------------
# Route: Home (Redirect to login)
# -------------------------------------------------------------------
@app.route('/')
def index():
    admins = get_admins()
    return render_template('landing.html', admins=admins)

# -------------------------------------------------------------------
# Route: Sign Up (Handles both Admin and Student registrations)
# -------------------------------------------------------------------
@app.route('/signup', methods=['GET', 'POST'])
def signup():
    if request.method == 'POST':
        # Gather form data
        name = request.form['name']
        email = request.form['email']
        password = request.form['password']
        role = request.form['role']  # 'admin' or 'student'
        assigned_admin = request.form.get('assigned_admin') if role == 'student' else None

        # Check if user already exists
        users_ref = db.collection('users')
        user_query = users_ref.where('email', '==', email).stream()
        if any(user_query):
            flash("User already exists.", "danger")
            return redirect(url_for('signup'))

        # Create new user. For admins, initialize bonus_left to 1000.
        if role == 'admin':
            user_data = {
                'name': name,
                'email': email,
                'password': password,
                'role': role,
                'bonus_left': 1000
            }
        else:
            user_data = {
                'name': name,
                'email': email,
                'password': password,
                'role': role,
                'assigned_admin': assigned_admin
            }
        db.collection('users').add(user_data)
        flash("Sign up successful. Please log in.", "success")
        return redirect(url_for('index'))
    else:
        admins = get_admins()
        return render_template('signup.html', admins=admins)

# -------------------------------------------------------------------
# Route: Login
# -------------------------------------------------------------------
@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        email = request.form['email']
        password = request.form['password']
        users_ref = db.collection('users')
        user_docs = users_ref.where('email', '==', email).stream()
        user = None
        for doc in user_docs:
            data = doc.to_dict()
            data['id'] = doc.id
            if data['password'] == password:
                user = data
                break
        if user:
            session['user'] = user
            flash("Logged in successfully.", "success")
            return redirect(url_for('dashboard'))
        else:
            flash("Invalid credentials.", "danger")
            return redirect(url_for('index'))
    return render_template('login.html')

# -------------------------------------------------------------------
# Route: Dashboard (Separate view for Admin and Student)
# -------------------------------------------------------------------
@app.route('/dashboard')
def dashboard():
    if 'user' not in session:
        return redirect(url_for('login'))
    user = session['user']
    if user['role'] == 'admin':
        # Fetch updated admin record
        admin_doc = db.collection('users').document(user['id']).get()
        admin_data = admin_doc.to_dict()
        bonus_left = admin_data.get('bonus_left', 1000)
        
        # Get all students assigned to this admin
        students = []
        users_ref = db.collection('users')
        query = users_ref.where('role', '==', 'student').where('assigned_admin', '==', user['id']).stream()
        for doc in query:
            student = doc.to_dict()
            student['id'] = doc.id
            # Query transactions for this student, ordering by timestamp descending
            trans_query = db.collection('transactions') \
                .where('student_id', '==', student['id']) \
                .order_by('timestamp', direction=firestore.Query.DESCENDING) \
                .stream()
            transactions = []
            for t in trans_query:
                transactions.append(t.to_dict())
            student['transactions'] = transactions
            students.append(student)
        return render_template('admin_dashboard.html', user=user, students=students, bonus_left=bonus_left)
    elif user['role'] == 'student':
        # Student dashboard logic remains unchanged.
        transactions = []
        trans_ref = db.collection('transactions')
        query = trans_ref.where('student_id', '==', user['id']).stream()
        for doc in query:
            transactions.append(doc.to_dict())
        notifications = []
        notif_ref = db.collection('notifications')
        notif_query = notif_ref.where('student_id', '==', user['id'])\
            .order_by('timestamp', direction=firestore.Query.DESCENDING).stream()
        for doc in notif_query:
            notifications.append(doc.to_dict())
        return render_template('student_dashboard.html', user=user, transactions=transactions, notifications=notifications)
    else:
        flash("Unknown role.", "danger")
        return redirect(url_for('logout'))


# -------------------------------------------------------------------
# Route: Add Transaction (Admins can give Bonus/Deduction)
# -------------------------------------------------------------------
@app.route('/admin/add_transaction', methods=['POST'])
def add_transaction():
    if 'user' not in session or session['user']['role'] != 'admin':
        return redirect(url_for('login'))
    student_id = request.form['student_id']
    trans_type = request.form['trans_type']  # 'bonus' or 'deduction'
    amount = float(request.form['amount'])
    description = request.form['description']

    # For bonus transactions, subtract from admin's bonus_left.
    if trans_type == 'bonus':
        admin_doc_ref = db.collection('users').document(session['user']['id'])
        admin_data = admin_doc_ref.get().to_dict()
        current_bonus = admin_data.get('bonus_left', 1000)
        if current_bonus < amount:
            flash("Not enough bonus funds left.", "danger")
            return redirect(url_for('dashboard'))
        new_bonus = current_bonus - amount
        admin_doc_ref.update({'bonus_left': new_bonus})

    # Create the transaction record
    transaction_data = {
        'student_id': student_id,
        'admin_id': session['user']['id'],
        'type': trans_type,
        'amount': amount,
        'description': description,
        'timestamp': datetime.datetime.utcnow()
    }
    db.collection('transactions').add(transaction_data)

    # Create a notification for the student
    notif_data = {
        'student_id': student_id,
        'message': f"You received a {trans_type} of ${amount}: {description}",
        'timestamp': datetime.datetime.utcnow(),
        'read': False
    }
    db.collection('notifications').add(notif_data)
    flash("Transaction added and notification sent.", "success")
    return redirect(url_for('dashboard'))


# -------------------------------------------------------------------
# Route: Logout
# -------------------------------------------------------------------
@app.route('/logout')
def logout():
    session.clear()
    flash("Logged out.", "success")
    return redirect(url_for('index'))

if __name__ == '__main__':
    app.run(debug=True)
