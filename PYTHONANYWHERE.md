# PythonAnywhere Deployment Guide

## Step 1: Create Account
1. Go to https://www.pythonanywhere.com
2. Sign up for a **free account**

## Step 2: Upload Code
1. Go to **Files** tab
2. Create a new directory: `sportybot`
3. Upload all files from this folder OR use Git:
   - Go to **Consoles** → Open a Bash console
   - Run: `git clone https://github.com/en3op/sportybot.git`

## Step 3: Set Up Virtual Environment
In the Bash console:
```bash
cd sportybot
mkvirtualenv sportybot-env --python=python3.11
pip install -r requirements.txt
```

## Step 4: Set Environment Variables
In Bash console:
```bash
echo 'export VIP_BOT_TOKEN="8791071506:AAGZv4Y3GWSMQ5mnj_vH2cT3p0BWEpxOOmk"' >> $HOME/.bashrc
echo 'export FREE_BOT_TOKEN="8784721708:AAFBp7_YbzpzeNvg-Y7lam_i8w6FhnJByHw"' >> $HOME/.bashrc
echo 'export API_FOOTBALL_KEY="932929ad49d522381384d69aec31fc99"' >> $HOME/.bashrc
source $HOME/.bashrc
```

## Step 5: Create Scheduled Tasks (IMPORTANT)
PythonAnywhere free tier uses scheduled tasks instead of always-running processes:

1. Go to **Tasks** tab
2. Create task 1:
   - **Command:** `cd /home/YOURUSERNAME/sportybot && /home/YOURUSERNAME/.virtualenvs/sportybot-env/bin/python run_vip_bot.py`
   - **Schedule:** Every hour (keeps bot alive)
3. Create task 2:
   - **Command:** `cd /home/YOURUSERNAME/sportybot && /home/YOURUSERNAME/.virtualenvs/sportybot-env/bin/python run_free_bot.py`
   - **Schedule:** Every hour (offset by 30 minutes from task 1)

## Step 6: Set Up Web Dashboard (Optional)
1. Go to **Web** tab
2. Create new web app (manual configuration, Python 3.11)
3. Set **Working directory:** `/home/YOURUSERNAME/sportybot`
4. Set **WSGI file:** Create `wsgi.py` with:
```python
import sys
sys.path.insert(0, '/home/YOURUSERNAME/sportybot')
from app import app as application
```
5. Add virtual environment path in web app settings

## Notes on PythonAnywhere Free Tier Limits:
- 1 web app (Flask dashboard)
- 2 scheduled tasks (perfect for 2 bots)
- 512MB storage
- CPU seconds limit (bots use very little)

## Troubleshooting:
- Check logs in **Files** → `/var/log/`
- Bots auto-restart every hour via scheduled tasks
- If bot stops, check task logs for errors
