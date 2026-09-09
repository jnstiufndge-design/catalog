# 🪵 Wood Market

A full-stack web application that combines **inventory management** (QuickBooks-style) and an **online marketplace** (Facebook Marketplace-style) specifically for wood companies.

Sellers can track lumber stock, set prices, and receive automatic low-stock alerts.  
Buyers can browse available products and purchase them securely with Stripe.

---

## Features

| Feature                    | Description                                              |
|----------------------------|----------------------------------------------------------|
| **User roles**             | Seller (wood company) and Buyer                          |
| **Inventory management**   | Add, update, delete products with quantity & price       |
| **Public marketplace**     | Browse all available stock from every seller             |
| **Stripe Checkout**        | Real card payments (test & live mode)                    |
| **Email notifications**    | Purchase confirmation to buyer + sale notice to seller   |
| **Low-stock alerts**       | Email + SMS when quantity falls ≤ threshold (default 10) |
| **SMS via Twilio**         | Instant low-stock warnings to sellers’ phones            |
| **Clean modern UI**        | Responsive design, no external CSS frameworks needed     |

---

## Tech Stack

- **Backend**: Python 3 + Flask
- **Auth**: Flask-Login + Werkzeug password hashing
- **Database**: SQLite (easy local start; switch to PostgreSQL for production)
- **Payments**: Stripe Checkout
- **Email**: Flask-Mail (Gmail, SendGrid, Mailgun, etc.)
- **SMS**: Twilio
- **Frontend**: Server-rendered Jinja2 templates + plain CSS

---

## Quick Start (Local Development)

### 1. Clone / open the project

```bash
cd wood_market
```

### 2. Create a virtual environment

```bash
python3 -m venv venv
source venv/bin/activate          # macOS / Linux
# venv\Scripts\activate           # Windows
```

### 3. Install dependencies

```bash
pip install -r requirements.txt
```

### 4. Configure environment variables

```bash
cp .env.example .env
# then edit .env with your real keys
```

**Minimum for basic testing** (no payments / emails / SMS yet):

```
FLASK_SECRET_KEY=any-long-random-string
```

The app will still run. Stripe, email and SMS features simply become inactive until you add the corresponding keys.

### 5. Run the development server

```bash
python app.py
```

Open http://127.0.0.1:5000

**Default demo account**

| Username | Password   | Role   |
|----------|------------|--------|
| admin    | adminpass  | seller |

Register additional buyer and seller accounts from the UI.

---

## Testing the Full Flow

1. **As seller**
   - Log in as `admin` / `adminpass` (or register a new seller)
   - Go to **My Inventory**
   - Add a few wood products (try setting quantity ≤ 10 to trigger low-stock alert)

2. **As buyer**
   - Register a new account with role **Buyer**
   - Go to **Marketplace**
   - Click **Buy with Stripe**

3. **Stripe test card**
   - Number: `4242 4242 4242 4242`
   - Any future expiry date
   - Any 3-digit CVC
   - Any ZIP

4. After successful payment you should see:
   - Stock reduced
   - Buyer confirmation email
   - Seller sale notification email
   - Low-stock email + SMS (if quantity ≤ threshold and phone is set)

---

## Environment Variables Reference

See `.env.example` for the full list. Important ones:

| Variable                 | Required for          | Notes                                      |
|--------------------------|-----------------------|--------------------------------------------|
| `FLASK_SECRET_KEY`       | Always                | Session security                           |
| `STRIPE_SECRET_KEY`      | Payments              | Use `sk_test_...` first                    |
| `STRIPE_PUBLISHABLE_KEY` | Payments              | Use `pk_test_...` first                    |
| `STRIPE_ENDPOINT_SECRET` | Reliable webhooks     | From Stripe Dashboard → Webhooks           |
| `MAIL_*`                 | Emails                | Gmail App Password or transactional service|
| `TWILIO_*`               | SMS alerts            | Account SID, Auth Token, Twilio number     |
| `LOW_STOCK_THRESHOLD`    | Low-stock alerts      | Default `10`                               |

---

## Deploy to Render (Permanent Phone-Friendly Link)

This is the easiest free way to get a permanent public URL you can open from your phone anytime.

### Step-by-step

1. **Push the project to GitHub**
   - Create a new repository on GitHub.
   - Upload everything inside the `wood_market` folder (including `render.yaml` and `Procfile`).

2. **Create the service on Render**
   - Go to [https://render.com](https://render.com) and sign up / log in with GitHub.
   - Click **New → Web Service**.
   - Connect the repository you just created.
   - Render should automatically detect the `render.yaml` settings.
   - Or manually set:
     - **Build Command**: `pip install -r requirements.txt`
     - **Start Command**: `gunicorn app:app --bind 0.0.0.0:$PORT`
     - **Instance Type**: Free

3. **Add environment variables**
   - In the Render dashboard → your service → **Environment**.
   - Add the keys from `.env.example` (especially Stripe, Mail, and Twilio if you want those features).
   - `FLASK_SECRET_KEY` is auto-generated by the Blueprint.

4. **Deploy**
   - Click **Create Web Service**.
   - Wait 1–3 minutes. You will get a permanent URL like:
     ```
     https://wood-market.onrender.com
     ```

5. **Open it on your phone**
   - Just visit the Render URL in your phone’s browser. No computer needed after this.

> Free tier note: The free plan sleeps after ~15 minutes of inactivity. The first visit after sleep can take 30–50 seconds to wake up.

---

## Production Deployment Notes

1. **Never** run with `debug=True` or the built-in Flask server in production.
2. Use **Gunicorn** (already configured in `Procfile` and `render.yaml`).
3. Switch from SQLite to **PostgreSQL** for real multi-user production use.
4. Use **live** Stripe keys (`sk_live_...` / `pk_live_...`) when you’re ready for real payments.
5. Prefer a real transactional email provider (SendGrid, Mailgun, Postmark, Amazon SES) over Gmail.
6. After deploying, set your Stripe webhook endpoint to `https://your-render-url.onrender.com/webhook`.
7. Popular easy hosts: **Render**, **Railway**, **Fly.io**, **DigitalOcean App Platform**.

---

## Project Structure

```
wood_market/
├── app.py                 # Main application
├── requirements.txt
├── Procfile               # For Heroku / Render / Railway
├── render.yaml            # Render Blueprint (one-click deploy)
├── .env.example
├── README.md
├── wood_inventory.db      # Created automatically on first run (local only)
├── static/
│   └── style.css
└── templates/
    ├── base.html
    ├── index.html
    ├── login.html
    ├── register.html
    ├── inventory.html
    └── marketplace.html
```

---

## License

MIT – free to use, modify, and deploy for your wood business or as a learning project.

---

Built with ❤️ for wood companies that want a simple, modern way to manage and sell inventory online.
