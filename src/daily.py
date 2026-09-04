from agent import run_agent
from telegram_notifier import send_telegram_message

result = run_agent(
    "Co ciekawego w Tychach, Katowicach i Gliwicach przez najbliższe 30 dni?"
)

print(result)
send_telegram_message(result)