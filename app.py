"""
Wood Market App
A marketplace + inventory management system for wood companies.
Combines features of Facebook Marketplace and QuickBooks-style inventory tracking.

Features:
- Seller inventory management (add / update / delete)
- Public marketplace
- Stripe Checkout payments
- Email notifications (purchase confirmation + sale notification)
- Low-stock alerts (email + SMS via Twilio)
- User roles: seller / buyer
"""

import os
from datetime import datetime
from dotenv import load_dotenv
from flask import Flask, render_template, request, redirect, url_for, flash, jsonify
from flask_login import LoginManager, UserMixin, login_user, login_required, logout_user, current_user
from flask_mail import Mail, Message
from werkzeug.security import generate_password_hash, check_password_hash
import sqlite3
import stripe

# Optional Twilio (gracefully degrades if not configured)
try:
    from twilio.rest import Client as TwilioClient
    TWILIO_AVAILABLE = True
except ImportError:
    TWILIO_AVAILABLE = False

load_dotenv()

app = Flask(__name__)
app.secret_key = os.environ.get("FLASK_SECRET_KEY", "dev-secret-change-me-in-production")

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------
LOW_STOCK_THRESHOLD = int(os.environ.get("LOW_STOCK_THRESHOLD", 10))

# Stripe
stripe.api_key = os.environ.get("STRIPE_SECRET_KEY")
STRIPE_PUBLISHABLE_KEY = os.environ.get("STRIPE_PUBLISHABLE_KEY")
STRIPE_ENDPOINT_SECRET = os.environ.get("STRIPE_ENDPOINT_SECRET")

# Email (Flask-Mail)
app.config["MAIL_SERVER"] = os.environ.get("MAIL_SERVER", "smtp.gmail.com")
app.config["MAIL_PORT"] = int(os.environ.get("MAIL_PORT", 465))
app.config["MAIL_USE_SSL"] = os.environ.get("MAIL_USE_SSL", "True").lower() == "true"
app.config["MAIL_USERNAME"] = os.environ.get("MAIL_USERNAME")
app.config["MAIL_PASSWORD"] = os.environ.get("MAIL_PASSWORD")
app.config["MAIL_DEFAULT_SENDER"] = os.environ.get(
    "MAIL_DEFAULT_SENDER", "Wood Market <noreply@woodmarket.local>"
)
mail = Mail(app)

# Twilio
TWILIO_ACCOUNT_SID = os.environ.get("TWILIO_ACCOUNT_SID")
TWILIO_AUTH_TOKEN = os.environ.get("TWILIO_AUTH_TOKEN")
TWILIO_PHONE_NUMBER = os.environ.get("TWILIO_PHONE_NUMBER")

twilio_client = None
if TWILIO_AVAILABLE and TWILIO_ACCOUNT_SID and TWILIO_AUTH_TOKEN:
    twilio_client = TwilioClient(TWILIO_ACCOUNT_SID, TWILIO_AUTH_TOKEN)

# ---------------------------------------------------------------------------
# Database helpers
# ---------------------------------------------------------------------------
DB_PATH = os.path.join(os.path.dirname(__file__), "wood_inventory.db")


def get_db():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def init_db():
    conn = get_db()
    c = conn.cursor()

    c.execute(
        """
        CREATE TABLE IF NOT EXISTS users (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            username TEXT UNIQUE NOT NULL,
            password TEXT NOT NULL,
            role TEXT NOT NULL CHECK(role IN ('seller', 'buyer')),
            email TEXT,
            phone TEXT,
            created_at TEXT DEFAULT CURRENT_TIMESTAMP
        )
        """
    )

    c.execute(
        """
        CREATE TABLE IF NOT EXISTS inventory (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL,
            type TEXT,
            quantity INTEGER NOT NULL DEFAULT 0,
            price REAL NOT NULL,
            description TEXT,
            seller_id INTEGER NOT NULL,
            created_at TEXT DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (seller_id) REFERENCES users (id)
        )
        """
    )

    c.execute(
        """
        CREATE TABLE IF NOT EXISTS sales (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            item_id INTEGER NOT NULL,
            buyer_id INTEGER NOT NULL,
            quantity INTEGER NOT NULL,
            total_amount REAL,
            stripe_session_id TEXT,
            date TEXT DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (item_id) REFERENCES inventory (id),
            FOREIGN KEY (buyer_id) REFERENCES users (id)
        )
        """
    )

    # Seed a default admin/seller if none exists
    c.execute("SELECT COUNT(*) FROM users")
    if c.fetchone()[0] == 0:
        hashed = generate_password_hash("adminpass")
        c.execute(
            "INSERT INTO users (username, password, role, email) VALUES (?, ?, ?, ?)",
            ("admin", hashed, "seller", "admin@woodmarket.local"),
        )
        print("→ Default seller created: username=admin  password=adminpass")

    conn.commit()
    conn.close()


init_db()

# ---------------------------------------------------------------------------
# Flask-Login
# ---------------------------------------------------------------------------
login_manager = LoginManager()
login_manager.init_app(app)
login_manager.login_view = "login"
login_manager.login_message_category = "warning"


class User(UserMixin):
    def __init__(self, id, username, role, email=None, phone=None):
        self.id = id
        self.username = username
        self.role = role
        self.email = email
        self.phone = phone


@login_manager.user_loader
def load_user(user_id):
    conn = get_db()
    row = conn.execute("SELECT * FROM users WHERE id = ?", (user_id,)).fetchone()
    conn.close()
    if row:
        return User(row["id"], row["username"], row["role"], row["email"], row["phone"])
    return None


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
def get_user_info(user_id):
    conn = get_db()
    row = conn.execute(
        "SELECT username, email, phone FROM users WHERE id = ?", (user_id,)
    ).fetchone()
    conn.close()
    return row


def send_sms(to_phone: str, body: str):
    """Send SMS via Twilio. Silently skips if not configured."""
    if not twilio_client or not TWILIO_PHONE_NUMBER or not to_phone:
        print(f"[SMS skipped] → {to_phone}: {body}")
        return
    try:
        msg = twilio_client.messages.create(
            body=body, from_=TWILIO_PHONE_NUMBER, to=to_phone
        )
        print(f"[SMS sent] sid={msg.sid}")
    except Exception as e:
        print(f"[SMS error] {e}")


def send_low_stock_alert(item_id, quantity, name, seller_id):
    info = get_user_info(seller_id)
    if not info:
        return

    # Email
    if info["email"]:
        try:
            msg = Message(
                subject="⚠️ Low Stock Alert – Wood Market",
                recipients=[info["email"]],
            )
            msg.body = f"""WARNING: Low Stock Alert!

Item: {name} (ID: {item_id})
Current quantity: {quantity} units

This item is now at or below the low-stock threshold ({LOW_STOCK_THRESHOLD} units).
Please restock soon to avoid running out.
"""
            mail.send(msg)
        except Exception as e:
            print(f"[Email error] {e}")

    # SMS
    if info["phone"]:
        send_sms(
            info["phone"],
            f"LOW STOCK ALERT! {name} is down to {quantity} units. Restock soon!",
        )


# ---------------------------------------------------------------------------
# Routes – Auth
# ---------------------------------------------------------------------------
@app.route("/")
def index():
    return render_template("index.html")


@app.route("/register", methods=["GET", "POST"])
def register():
    if current_user.is_authenticated:
        return redirect(url_for("dashboard"))

    if request.method == "POST":
        username = request.form.get("username", "").strip()
        email = request.form.get("email", "").strip()
        phone = request.form.get("phone", "").strip() or None
        password = request.form.get("password", "")
        role = request.form.get("role", "buyer")

        if not username or not password or not email:
            flash("Username, email and password are required.", "danger")
            return render_template("register.html")

        if role not in ("seller", "buyer"):
            role = "buyer"

        hashed = generate_password_hash(password)
        conn = get_db()
        try:
            conn.execute(
                "INSERT INTO users (username, password, role, email, phone) VALUES (?, ?, ?, ?, ?)",
                (username, hashed, role, email, phone),
            )
            conn.commit()
            flash("Registration successful! Please log in.", "success")
            return redirect(url_for("login"))
        except sqlite3.IntegrityError:
            flash("Username already exists.", "danger")
        finally:
            conn.close()

    return render_template("register.html")


@app.route("/login", methods=["GET", "POST"])
def login():
    if current_user.is_authenticated:
        return redirect(url_for("dashboard"))

    if request.method == "POST":
        username = request.form.get("username", "").strip()
        password = request.form.get("password", "")

        conn = get_db()
        row = conn.execute(
            "SELECT * FROM users WHERE username = ?", (username,)
        ).fetchone()
        conn.close()

        if row and check_password_hash(row["password"], password):
            user = User(
                row["id"], row["username"], row["role"], row["email"], row["phone"]
            )
            login_user(user)
            flash(f"Welcome back, {user.username}!", "success")
            return redirect(url_for("dashboard"))
        flash("Invalid username or password.", "danger")

    return render_template("login.html")


@app.route("/logout")
@login_required
def logout():
    logout_user()
    flash("You have been logged out.", "info")
    return redirect(url_for("index"))


@app.route("/dashboard")
@login_required
def dashboard():
    if current_user.role == "seller":
        return redirect(url_for("inventory"))
    return redirect(url_for("marketplace"))


# ---------------------------------------------------------------------------
# Routes – Inventory (sellers only)
# ---------------------------------------------------------------------------
@app.route("/inventory", methods=["GET", "POST"])
@login_required
def inventory():
    if current_user.role != "seller":
        flash("Access denied. Sellers only.", "danger")
        return redirect(url_for("dashboard"))

    conn = get_db()

    if request.method == "POST":
        action = request.form.get("action")

        if action == "add":
            name = request.form.get("name", "").strip()
            wood_type = request.form.get("type", "").strip()
            quantity = int(request.form.get("quantity", 0))
            price = float(request.form.get("price", 0))
            description = request.form.get("description", "").strip()

            if name and quantity >= 0 and price >= 0:
                cur = conn.execute(
                    """INSERT INTO inventory
                       (name, type, quantity, price, description, seller_id)
                       VALUES (?, ?, ?, ?, ?, ?)""",
                    (name, wood_type, quantity, price, description, current_user.id),
                )
                conn.commit()
                item_id = cur.lastrowid
                flash(f'Item "{name}" added successfully.', "success")

                if quantity <= LOW_STOCK_THRESHOLD:
                    send_low_stock_alert(item_id, quantity, name, current_user.id)
                    flash("Low-stock alert sent.", "warning")
            else:
                flash("Please fill in all required fields correctly.", "danger")

        elif action == "update":
            item_id = int(request.form.get("item_id"))
            new_qty = int(request.form.get("quantity", 0))
            new_price = float(request.form.get("price", 0))

            old = conn.execute(
                "SELECT quantity, name FROM inventory WHERE id = ? AND seller_id = ?",
                (item_id, current_user.id),
            ).fetchone()

            if old:
                conn.execute(
                    "UPDATE inventory SET quantity = ?, price = ? WHERE id = ? AND seller_id = ?",
                    (new_qty, new_price, item_id, current_user.id),
                )
                conn.commit()
                flash("Item updated.", "success")

                # Alert only when crossing the threshold downward
                if new_qty <= LOW_STOCK_THRESHOLD and old["quantity"] > LOW_STOCK_THRESHOLD:
                    send_low_stock_alert(item_id, new_qty, old["name"], current_user.id)
                    flash("Low-stock alert sent.", "warning")
            else:
                flash("Item not found.", "danger")

        elif action == "delete":
            item_id = int(request.form.get("item_id"))
            conn.execute(
                "DELETE FROM inventory WHERE id = ? AND seller_id = ?",
                (item_id, current_user.id),
            )
            conn.commit()
            flash("Item deleted.", "success")

    items = conn.execute(
        "SELECT * FROM inventory WHERE seller_id = ? ORDER BY id DESC",
        (current_user.id,),
    ).fetchall()
    conn.close()

    return render_template(
        "inventory.html", items=items, low_stock_threshold=LOW_STOCK_THRESHOLD
    )


# ---------------------------------------------------------------------------
# Routes – Marketplace
# ---------------------------------------------------------------------------
@app.route("/marketplace")
def marketplace():
    conn = get_db()
    items = conn.execute(
        """
        SELECT i.*, u.username AS seller_name
        FROM inventory i
        JOIN users u ON i.seller_id = u.id
        WHERE i.quantity > 0
        ORDER BY i.id DESC
        """
    ).fetchall()
    conn.close()
    return render_template(
        "marketplace.html",
        items=items,
        stripe_pk=STRIPE_PUBLISHABLE_KEY,
        low_stock_threshold=LOW_STOCK_THRESHOLD,
    )


@app.route("/create-checkout-session", methods=["POST"])
@login_required
def create_checkout_session():
    if current_user.role != "buyer":
        flash("Only buyers can purchase items.", "danger")
        return redirect(url_for("marketplace"))

    item_id = int(request.form.get("item_id", 0))
    quantity = int(request.form.get("quantity", 1))

    if quantity < 1:
        flash("Invalid quantity.", "danger")
        return redirect(url_for("marketplace"))

    conn = get_db()
    item = conn.execute(
        "SELECT * FROM inventory WHERE id = ?", (item_id,)
    ).fetchone()
    conn.close()

    if not item or item["quantity"] < quantity:
        flash("Not enough stock available.", "danger")
        return redirect(url_for("marketplace"))

    if not stripe.api_key:
        flash("Stripe is not configured. Contact the administrator.", "danger")
        return redirect(url_for("marketplace"))

    try:
        session = stripe.checkout.Session.create(
            payment_method_types=["card"],
            line_items=[
                {
                    "price_data": {
                        "currency": "usd",
                        "product_data": {
                            "name": item["name"],
                            "description": item["description"] or item["type"] or "",
                        },
                        "unit_amount": int(round(item["price"] * 100)),
                    },
                    "quantity": quantity,
                }
            ],
            mode="payment",
            success_url=url_for("payment_success", _external=True)
            + "?session_id={CHECKOUT_SESSION_ID}",
            cancel_url=url_for("marketplace", _external=True),
            metadata={
                "item_id": str(item_id),
                "quantity": str(quantity),
                "buyer_id": str(current_user.id),
            },
        )
        return redirect(session.url, code=303)
    except Exception as e:
        flash(f"Payment error: {str(e)}", "danger")
        return redirect(url_for("marketplace"))


@app.route("/payment-success")
@login_required
def payment_success():
    session_id = request.args.get("session_id")
    if not session_id:
        flash("Missing payment session.", "danger")
        return redirect(url_for("marketplace"))

    try:
        session = stripe.checkout.Session.retrieve(session_id)

        if session.payment_status != "paid":
            flash("Payment was not completed.", "warning")
            return redirect(url_for("marketplace"))

        item_id = int(session.metadata.get("item_id"))
        quantity = int(session.metadata.get("quantity"))
        buyer_id = int(session.metadata.get("buyer_id"))

        # Security: only the logged-in buyer who started the session can finalize
        if buyer_id != current_user.id:
            flash("Session mismatch.", "danger")
            return redirect(url_for("marketplace"))

        conn = get_db()
        item = conn.execute(
            "SELECT * FROM inventory WHERE id = ?", (item_id,)
        ).fetchone()

        if not item or item["quantity"] < quantity:
            flash("Stock changed during checkout. Please contact support.", "danger")
            conn.close()
            return redirect(url_for("marketplace"))

        new_qty = item["quantity"] - quantity
        total_amount = quantity * item["price"]

        conn.execute(
            "UPDATE inventory SET quantity = ? WHERE id = ?", (new_qty, item_id)
        )
        conn.execute(
            """INSERT INTO sales
               (item_id, buyer_id, quantity, total_amount, stripe_session_id)
               VALUES (?, ?, ?, ?, ?)""",
            (item_id, buyer_id, quantity, total_amount, session_id),
        )
        conn.commit()
        conn.close()

        # ----- Notifications -----
        buyer_info = get_user_info(buyer_id)
        seller_info = get_user_info(item["seller_id"])

        # Buyer confirmation email
        if buyer_info and buyer_info["email"]:
            try:
                msg = Message(
                    subject="Purchase Confirmation – Wood Market",
                    recipients=[buyer_info["email"]],
                )
                msg.body = f"""Thank you for your purchase!

Item: {item['name']}
Quantity: {quantity}
Unit price: ${item['price']:.2f}
Total: ${total_amount:.2f}
Description: {item['description'] or 'N/A'}

Your order has been confirmed.
"""
                mail.send(msg)
            except Exception as e:
                print(f"[Email error - buyer] {e}")

        # Seller sale notification
        if seller_info and seller_info["email"]:
            try:
                msg = Message(
                    subject="New Sale on Wood Market",
                    recipients=[seller_info["email"]],
                )
                msg.body = f"""You have a new sale!

Buyer: {current_user.username}
Item: {item['name']}
Quantity sold: {quantity}
Total revenue: ${total_amount:.2f}

Current stock level: {new_qty} units remaining.
"""
                mail.send(msg)
            except Exception as e:
                print(f"[Email error - seller] {e}")

        # Low-stock alert (email + SMS)
        if new_qty <= LOW_STOCK_THRESHOLD:
            send_low_stock_alert(item_id, new_qty, item["name"], item["seller_id"])

        flash(
            "Payment successful! Confirmation emails have been sent.", "success"
        )
    except Exception as e:
        flash(f"Error verifying payment: {str(e)}", "danger")

    return redirect(url_for("marketplace"))


# ---------------------------------------------------------------------------
# Stripe Webhook (more reliable fulfillment)
# ---------------------------------------------------------------------------
@app.route("/webhook", methods=["POST"])
def stripe_webhook():
    payload = request.data
    sig_header = request.headers.get("Stripe-Signature")

    if not STRIPE_ENDPOINT_SECRET:
        # Development: accept without verification
        event = stripe.Event.construct_from(
            request.get_json(force=True), stripe.api_key
        )
    else:
        try:
            event = stripe.Webhook.construct_event(
                payload, sig_header, STRIPE_ENDPOINT_SECRET
            )
        except ValueError:
            return jsonify(success=False), 400
        except stripe.error.SignatureVerificationError:
            return jsonify(success=False), 400

    if event["type"] == "checkout.session.completed":
        session = event["data"]["object"]
        if session.get("payment_status") == "paid":
            # In a real production system you would make this idempotent
            # by checking if the session_id already exists in the sales table.
            print(f"[Webhook] checkout.session.completed for session {session['id']}")
            # Fulfillment is already handled on the success page for simplicity.
            # For production you should move the stock deduction + emails here
            # and make the success page only show a thank-you message.

    return jsonify(success=True)


# ---------------------------------------------------------------------------
# Run
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    # Development only – never use this in production
    # Respects the PORT env var (used by Render, Railway, Heroku, etc.)
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port, debug=True)
