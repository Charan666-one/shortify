# 🔗 FastAPI URL Shortener

A full-stack URL shortener built using **FastAPI**, **SQLite**, and **JavaScript**, allowing users to generate short links and redirect instantly.

---

## 🚀 Features

* 🔹 Shorten long URLs into unique short links
* 🔹 Redirect short URLs to original links
* 🔹 Track number of clicks per URL
* 🔹 Custom short codes (optional)
* 🔹 Simple and interactive frontend UI
* 🔹 Full-stack integration (Frontend + Backend)

---

## 🧠 Tech Stack

* **Backend:** FastAPI (Python)
* **Database:** SQLite + SQLAlchemy
* **Frontend:** HTML, CSS, JavaScript (Fetch API)
* **Server:** Uvicorn

---

## 📁 Project Structure

```
URL-SHORTNER/
│
├── main.py            # FastAPI app (routes & logic)
├── database.py        # Database connection setup
├── models.py          # Database schema (URL model)
├── urls.db            # SQLite database file
│
├── static/
│   └── index.html     # Frontend UI
│
├── .gitignore
└── README.md
```

---

## ⚙️ Installation & Setup

### 1️⃣ Clone the repository

```
git clone https://github.com/your-username/fastapi-url-shortener.git
cd fastapi-url-shortener
```

---

### 2️⃣ Create virtual environment

```
python -m venv venv
source venv/bin/activate   # Mac/Linux
```

---

### 3️⃣ Install dependencies

```
pip install fastapi uvicorn sqlalchemy
```

---

### 4️⃣ Run the server

```
uvicorn main:app --reload
```

---

### 5️⃣ Open in browser

```
http://127.0.0.1:8000
```

---

## 🧪 How It Works

### 🔹 Shorten URL

* Enter a long URL in the input box
* Click **Shorten**
* Get a short URL

### 🔹 Redirect

* Open the short URL
* Automatically redirected to original link

---

## 🔄 API Endpoints

### ➤ Create Short URL

```
POST /shorten?original_url=<your_url>
```

---

### ➤ Redirect

```
GET /{short_code}
```

---

## 🧠 Key Concepts Learned

* REST API design with FastAPI
* Database interaction using SQLAlchemy
* Frontend–backend communication using Fetch API
* Handling CORS
* Debugging real-world errors

---

## 🚀 Future Improvements

* 🔹 User authentication (login/signup)
* 🔹 Analytics dashboard (click tracking)
* 🔹 QR code generation
* 🔹 Expiry-based links
* 🔹 Custom domains
* 🔹 Deployment to cloud (Render/Vercel)

---

## 🤝 Contributing

Feel free to fork this repo and improve it 🚀

---



