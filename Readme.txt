t# Matrix Theme Email Verifier (only for Mac users rn)

This is a local cold email verification tool. Drag in a CSV and it will:
- Validate each email live (MX, SMTP, syntax)
- Show real-time progress per email
- Let you cancel jobs mid-run
- Persist your results even after refresh
- Filter the email status before download

---

You can play a small game I put while waiting.

## 🧱 Setup - step by step

1. Create a folder called:
```
Neverbounce Clone
```

2. Drag in these files:
- `verify-app.py`
- `index.html`
- Your test CSV with column called "emails", the other columns are not used yet. More features coming soon.

---

Open Terminal, then run:

```bash
cd "/Users/yourname/Desktop/Neverbounce Clone" - click enter
python3 -m venv venv
source venv/bin/activate
pip install flask flask-cors dnspython
```

Click enter

If didn't work, copy the folder Neverbounce Clone which you created
Replace with - "/Users/yourname/Desktop/Neverbounce Clone"

---

## 🚀 let the terminal run the App

### In the same Terminal, run:

```bash
source venv/bin/activate
python3 verify-app.py
```

Click enter 

You should see something like:
```
🔥 VERIFIER RUNNING
```

### Terminal Tab 2:
```bash
cd "/Users/yourname/Desktop/Neverbounce Clone" 
```

(Click enter)
```
python3 -m http.server 3000
```

(Click enter)

---

## 🌐 Use the Tool

Open in your browser:
```
http://localhost:3000/index.html
```
Or open the index.html file



If you want to see how it looks like, you can open https://html.onlineviewer.net and copy-paste the index.html code or file
