import time
import json
import random
from datetime import datetime
import configparser
import os
import requests
import socket
from urllib3.exceptions import MaxRetryError, ProtocolError

from selenium import webdriver
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.support.ui import WebDriverWait as Wait
from selenium.webdriver.common.by import By
from webdriver_manager.chrome import ChromeDriverManager
from selenium.common.exceptions import WebDriverException, TimeoutException

from sendgrid import SendGridAPIClient
from sendgrid.helpers.mail import Mail

from embassy import *

config = configparser.ConfigParser()
config.read('config.ini')

# Personal Info
USERNAME = config['PERSONAL_INFO']['USERNAME']
PASSWORD = config['PERSONAL_INFO']['PASSWORD']
SCHEDULE_ID = config['PERSONAL_INFO']['SCHEDULE_ID']
PRIOD_START = config['PERSONAL_INFO']['PRIOD_START']
PRIOD_END = config['PERSONAL_INFO']['PRIOD_END']
YOUR_EMBASSY = config['PERSONAL_INFO']['YOUR_EMBASSY'] 
EMBASSY = Embassies[YOUR_EMBASSY][0]
FACILITY_ID = Embassies[YOUR_EMBASSY][1]
REGEX_CONTINUE = Embassies[YOUR_EMBASSY][2]

# Notification
SENDGRID_API_KEY = config['NOTIFICATION']['SENDGRID_API_KEY']
PUSHOVER_TOKEN = config['NOTIFICATION']['PUSHOVER_TOKEN']
PUSHOVER_USER = config['NOTIFICATION']['PUSHOVER_USER']
PERSONAL_SITE_USER = config['NOTIFICATION']['PERSONAL_SITE_USER']
PERSONAL_SITE_PASS = config['NOTIFICATION']['PERSONAL_SITE_PASS']
PUSH_TARGET_EMAIL = config['NOTIFICATION']['PUSH_TARGET_EMAIL']
PERSONAL_PUSHER_URL = config['NOTIFICATION']['PERSONAL_PUSHER_URL']

# Time Section
minute = 60
hour = 60 * minute
STEP_TIME = 0.5
RETRY_TIME_L_BOUND = config['TIME'].getfloat('RETRY_TIME_L_BOUND')
RETRY_TIME_U_BOUND = config['TIME'].getfloat('RETRY_TIME_U_BOUND')
WORK_LIMIT_TIME = config['TIME'].getfloat('WORK_LIMIT_TIME')
WORK_COOLDOWN_TIME = config['TIME'].getfloat('WORK_COOLDOWN_TIME')
BAN_COOLDOWN_TIME = config['TIME'].getfloat('BAN_COOLDOWN_TIME')

# CHROMEDRIVER
LOCAL_USE = config['CHROMEDRIVER'].getboolean('LOCAL_USE')
HUB_ADDRESS = config['CHROMEDRIVER']['HUB_ADDRESS']

# Base URL configuration (adjustable based on embassy)
BASE_URL = "https://ais.usvisa-info.com"  # Default, can be overridden
SIGN_IN_LINK = f"{BASE_URL}/{EMBASSY}/niv/users/sign_in"
APPOINTMENT_URL = f"{BASE_URL}/{EMBASSY}/niv/schedule/{SCHEDULE_ID}/appointment"
DATE_URL = f"{BASE_URL}/{EMBASSY}/niv/schedule/{SCHEDULE_ID}/appointment/days/{FACILITY_ID}.json?appointments[expedite]=false"
TIME_URL = f"{BASE_URL}/{EMBASSY}/niv/schedule/{SCHEDULE_ID}/appointment/times/{FACILITY_ID}.json?date=%s&appointments[expedite]=false"
SIGN_OUT_LINK = f"{BASE_URL}/{EMBASSY}/niv/users/sign_out"

def send_notification(title, msg):
    print(f"Sending notification: {title}")
    if SENDGRID_API_KEY:
        message = Mail(from_email=USERNAME, to_emails=USERNAME, subject=title, html_content=msg)
        try:
            sg = SendGridAPIClient(SENDGRID_API_KEY)
            sg.send(message)
        except Exception as e:
            print(f"SendGrid error: {e}")
    if PUSHOVER_TOKEN:
        url = "https://api.pushover.net/1/messages.json"
        data = {"token": PUSHOVER_TOKEN, "user": PUSHOVER_USER, "message": msg, "title": title}
        requests.post(url, data)
    if PERSONAL_SITE_USER:
        url = PERSONAL_PUSHER_URL
        data = {"title": f"VISA - {title}", "user": PERSONAL_SITE_USER, "pass": PERSONAL_SITE_PASS, "email": PUSH_TARGET_EMAIL, "msg": msg}
        requests.post(url, data)

def auto_action(label, find_by, el_type, action, value, sleep_time=0):
    print(f"\t{label}:", end="")
    try:
        match find_by.lower():
            case 'id': item = driver.find_element(By.ID, el_type)
            case 'name': item = driver.find_element(By.NAME, el_type)
            case 'class': item = driver.find_element(By.CLASS_NAME, el_type)
            case 'xpath': item = driver.find_element(By.XPATH, el_type)
            case _: return False
        match action.lower():
            case 'send': 
                for char in value:
                    item.send_keys(char)
                    time.sleep(random.uniform(0.05, 0.15))
            case 'click': item.click()
            case _: return False
        print("\t\tSuccess!")
        if sleep_time:
            time.sleep(sleep_time)
        return True
    except Exception as e:
        print(f"\t\tFailed: {e}")
        return False

def start_process():
    driver.get(SIGN_IN_LINK)
    time.sleep(random.uniform(1, 3))
    Wait(driver, 60).until(EC.presence_of_element_located((By.NAME, "commit")))
    driver.execute_script("return document.readyState === 'complete'")
    auto_action("Click bounce", "xpath", '//a[@class="down-arrow bounce"]', "click", "", STEP_TIME)
    auto_action("Email", "id", "user_email", "send", USERNAME, STEP_TIME)
    auto_action("Password", "id", "user_password", "send", PASSWORD, STEP_TIME)
    auto_action("Privacy", "class", "icheckbox", "click", "", STEP_TIME)
    auto_action("Enter Panel", "name", "commit", "click", "", STEP_TIME)
    Wait(driver, 60).until(EC.presence_of_element_located((By.XPATH, "//a[contains(text(), '" + REGEX_CONTINUE + "')]")))
    print("\n\tLogin successful!\n")

def reschedule(date):
    driver.get(APPOINTMENT_URL)
    Wait(driver, 10).until(EC.presence_of_element_located((By.NAME, "appointments[consulate_appointment][date]")))
    auto_action("Select Date", "name", "appointments[consulate_appointment][date]", "send", date, STEP_TIME)
    time.sleep(1)
    time = get_time(date)
    auto_action("Select Time", "name", "appointments[consulate_appointment][time]", "send", time, STEP_TIME)
    auto_action("Submit", "name", "commit", "click", "", STEP_TIME)
    Wait(driver, 10).until(EC.presence_of_element_located((By.TAG_NAME, "body")))
    if "Successfully Scheduled" in driver.page_source:
        return ["SUCCESS", f"Rescheduled Successfully! {date} {time}"]
    return ["FAIL", f"Reschedule Failed! {date} {time}"]

def get_date():
    try:
        print(f"Attempting to get dates from: {DATE_URL}")
        # Use requests with session cookies from Selenium for better reliability
        cookies = driver.get_cookies()
        session = requests.Session()
        for cookie in cookies:
            session.cookies.set(cookie['name'], cookie['value'])
        response = session.get(DATE_URL, timeout=10)
        response.raise_for_status()
        content = response.text
        print(f"Date content received: {content[:100]}...")
        return json.loads(content)
    except requests.exceptions.RequestException as e:
        msg = f"Network error getting dates: {str(e)}"
        print(msg)
        info_logger(LOG_FILE_NAME, msg)
        time.sleep(30)
        return None
    except json.JSONDecodeError as e:
        msg = f"JSON parsing error: {str(e)}, Content: {content[:200]}"
        print(msg)
        info_logger(LOG_FILE_NAME, msg)
        return None
    except Exception as e:
        msg = f"Failed to get dates: {str(e)}"
        print(msg)
        info_logger(LOG_FILE_NAME, msg)
        try:
            screenshot_path = f"error_screenshot_{datetime.now().strftime('%Y%m%d_%H%M%S')}.png"
            driver.save_screenshot(screenshot_path)
            print(f"Screenshot saved to {screenshot_path}")
        except:
            print("Failed to save screenshot")
        return None

def get_time(date):
    try:
        url = TIME_URL % date
        cookies = driver.get_cookies()
        session = requests.Session()
        for cookie in cookies:
            session.cookies.set(cookie['name'], cookie['value'])
        response = session.get(url, timeout=10)
        response.raise_for_status()
        content = response.text
        data = json.loads(content)
        time = data.get("available_times")[-1]
        print(f"Got time successfully! {date} {time}")
        return time
    except Exception as e:
        print(f"Failed to get time: {str(e)}")
        return None

def is_logged_in():
    try:
        driver.get(APPOINTMENT_URL)
        Wait(driver, 10).until(
            EC.any_of(
                EC.presence_of_element_located((By.XPATH, "//a[contains(text(), '" + REGEX_CONTINUE + "')]")),
                EC.presence_of_element_located((By.XPATH, "//a[contains(text(), 'Sign Out')]"))
            )
        )
        if driver.find_elements(By.ID, "user_email"):
            return False
        return True
    except TimeoutException:
        return False

def get_available_date(dates):
    PED = datetime.strptime(PRIOD_END, "%Y-%m-%d")
    PSD = datetime.strptime(PRIOD_START, "%Y-%m-%d")
    for d in dates:
        date = d.get('date')
        new_date = datetime.strptime(date, "%Y-%m-%d")
        if PED > new_date > PSD:
            return date
    print(f"\n\nNo available dates between ({PSD.date()}) and ({PED.date()})!")
    return None

def info_logger(file_path, log):
    with open(file_path, "a") as file:
        file.write(f"{datetime.now().time()}:\n{log}\n")

def get_date_with_retry(max_retries=3, initial_wait=5):
    for attempt in range(1, max_retries + 1):
        print(f"Date fetch attempt {attempt}/{max_retries}")
        result = get_date()
        if result is not None:
            return result
        if attempt < max_retries:
            wait_time = initial_wait * (2 ** (attempt - 1))
            random_factor = random.uniform(0.8, 1.2)
            adjusted_wait = wait_time * random_factor
            print(f"Retrying date fetch in {adjusted_wait:.2f} seconds...")
            time.sleep(adjusted_wait)
    return None

if LOCAL_USE:
    options = webdriver.ChromeOptions()
    options.add_argument("--disable-blink-features=AutomationControlled")
    options.add_argument("user-agent=Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/123.0.0.0 Safari/537.36")
    driver = webdriver.Chrome(service=Service(), options=options)
else:
    options = webdriver.ChromeOptions()
    options.add_argument("--disable-blink-features=AutomationControlled")
    options.add_argument("user-agent=Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/123.0.0.0 Safari/537.36")
    driver = webdriver.Remote(command_executor=HUB_ADDRESS, options=options)

if __name__ == "__main__":
    first_loop = True
    LOG_FILE_NAME = f"log_{datetime.now().date()}.txt"
    t0 = time.time()
    Req_count = 0

    # Allow overriding BASE_URL via config if needed
    if config.has_option('PERSONAL_INFO', 'BASE_URL'):
        BASE_URL = config['PERSONAL_INFO']['BASE_URL']
        SIGN_IN_LINK = f"{BASE_URL}/{EMBASSY}/niv/users/sign_in"
        APPOINTMENT_URL = f"{BASE_URL}/{EMBASSY}/niv/schedule/{SCHEDULE_ID}/appointment"
        DATE_URL = f"{BASE_URL}/{EMBASSY}/niv/schedule/{SCHEDULE_ID}/appointment/days/{FACILITY_ID}.json?appointments[expedite]=false"
        TIME_URL = f"{BASE_URL}/{EMBASSY}/niv/schedule/{SCHEDULE_ID}/appointment/times/{FACILITY_ID}.json?date=%s&appointments[expedite]=false"
        SIGN_OUT_LINK = f"{BASE_URL}/{EMBASSY}/niv/users/sign_out"

    while True:
        if first_loop:
            try:
                start_process()
                first_loop = False
            except Exception as e:
                msg = f"Failed to start process: {str(e)}"
                print(msg)
                info_logger(LOG_FILE_NAME, msg)
                send_notification("START_ERROR", msg)
                driver.quit()
                break

        Req_count += 1
        msg = f"{'-'*60}\nRequest count: {Req_count}, Log time: {datetime.now()}\n"
        print(msg)
        info_logger(LOG_FILE_NAME, msg)

        if not is_logged_in():
            msg = f"Session expired at {datetime.now()}. Restarting...\nURL: {driver.current_url}\nTitle: {driver.title}\nPage source: {driver.page_source[:500]}"
            print(msg)
            info_logger(LOG_FILE_NAME, msg)
            driver.quit()
            time.sleep(5)
            driver = webdriver.Chrome(service=Service(), options=options) if LOCAL_USE else webdriver.Remote(command_executor=HUB_ADDRESS, options=options)
            first_loop = True
            continue

        try:
            dates = get_date_with_retry(max_retries=3, initial_wait=5)
            if not dates:
                msg = f"Empty date list or error after retries, possibly banned! Sleeping for {BAN_COOLDOWN_TIME} hours."
                print(msg)
                info_logger(LOG_FILE_NAME, msg)
                send_notification("BAN", msg)
                driver.get(SIGN_OUT_LINK)
                time.sleep(BAN_COOLDOWN_TIME * hour)
                first_loop = True
                continue

            msg = "Available dates:\n" + ", ".join(d.get('date') for d in dates)
            print(msg)
            info_logger(LOG_FILE_NAME, msg)

            date = get_available_date(dates)
            if date:
                title, msg = reschedule(date)
                print(msg)
                info_logger(LOG_FILE_NAME, msg)
                send_notification(title, msg)
                break
            else:
                msg = f"No suitable dates found between {PRIOD_START} and {PRIOD_END}"
                print(msg)
                info_logger(LOG_FILE_NAME, msg)

            total_time = (time.time() - t0) / minute
            msg = f"Working Time: ~{total_time:.2f} minutes"
            print(msg)
            info_logger(LOG_FILE_NAME, msg)

            if total_time > WORK_LIMIT_TIME * 60:
                msg = f"Break time after {WORK_LIMIT_TIME} hours | Repeated {Req_count} times"
                send_notification("REST", msg)
                driver.get(SIGN_OUT_LINK)
                time.sleep(WORK_COOLDOWN_TIME * hour)
                first_loop = True
            else:
                wait_time = random.uniform(RETRY_TIME_L_BOUND, RETRY_TIME_U_BOUND)
                msg = f"Retrying in {wait_time:.2f} seconds"
                print(msg)
                info_logger(LOG_FILE_NAME, msg)
                time.sleep(wait_time)

        except WebDriverException as e:
            msg = f"Selenium error: {str(e)}"
            print(msg)
            info_logger(LOG_FILE_NAME, msg)
            send_notification("SELENIUM_ERROR", msg)
            break
        except Exception as e:
            msg = f"Unexpected error: {str(e)}"
            print(msg)
            info_logger(LOG_FILE_NAME, msg)
            send_notification("UNEXPECTED_ERROR", msg)
            break

    driver.get(SIGN_OUT_LINK)
    driver.quit()