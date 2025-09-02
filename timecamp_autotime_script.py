import sys
from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.common.exceptions import TimeoutException, WebDriverException
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.chrome.options import Options
import time
import datetime
import random
import os

# --- IMPORTANT: Selenium Library Installation ---
# If you encounter "Import 'selenium' could not be resolved" errors,
# it means the Selenium library is not installed in your Python environment.
# To fix this, open your terminal or command prompt and run:
# pip install selenium
# After installation, restart your IDE/Python environment.
# -------------------------------------------------

# --- Configuration ---
# Explicit path for Brave browser
BRAVE_PATH = r"C:\Program Files\BraveSoftware\Brave-Browser\Application\brave.exe"

# ChromeDriver path: relative to the executable for better portability with PyInstaller
# Use _MEIPASS for onefile executables to point to the temporary extraction directory
if getattr(sys, 'frozen', False):
    # Running as a PyInstaller executable
    base_path = sys._MEIPASS
else:
    # Running as a normal Python script
    base_path = os.path.dirname(os.path.abspath(__file__))

CHROMEDRIVER_PATH = os.path.join(base_path, "chromedriver.exe")

TIMECAMP_SAML_URL = "https://app.timecamp.com/saml/auth"
EMAIL_ADDRESS = "lrojas@conversionia.com"
PASSWORD = "Noisrevnoc@Wr0ng?"
WAIT_TIMEOUT_SECONDS = 30
MAX_RETRIES = 3
SHORT_WAIT_SECONDS = 5
# Default polling interval for active shifts, and for long break checks if not sleeping precisely.
POLLING_INTERVAL_MINUTES = 8


# Define fixed time points for comparison (AM/PM)
# Weekday Schedule (Monday-Saturday) - New: 3:30 AM to 11:30 AM with a lunch break

# Start of the workday window
WEEKDAY_SCHEDULE_START_WINDOW_START = time(3, 25)  # New: Start window at 3:25 AM
WEEKDAY_SCHEDULE_START_WINDOW_END = time(3, 30)    # New: End window at 3:30 AM

# Lunch break stop window
WEEKDAY_LUNCH_BREAK_STOP_WINDOW_START = time(6, 55) # New: Stop window at 6:55 AM
WEEKDAY_LUNCH_BREAK_STOP_WINDOW_END = time(7, 0)    # New: End window at 7:00 AM

# Lunch break resume window
WEEKDAY_LUNCH_BREAK_RESUME_WINDOW_START = time(8, 0) # New: Resume window at 8:00 AM
WEEKDAY_LUNCH_BREAK_RESUME_WINDOW_END = time(8, 5)    # New: End window at 8:05 AM

# Final end of the workday window
WEEKDAY_SCHEDULE_END_WINDOW_START = time(11, 25) # New: End window at 11:25 AM
WEEKDAY_SCHEDULE_END_WINDOW_END = time(11, 30)    # New: End window at 11:30 AM

# Monday specific mid-morning stop (remains the same as before)
MONDAY_MID_MORNING_STOP_WINDOW_START = time(9, 29, 45) # 9:29 AM and 45 seconds for Monday's mid-morning stop
MONDAY_MID_MORNING_STOP_WINDOW_END = time(9, 29, 55) # 9:29 AM and 55 seconds for Monday's mid-morning stop

# Monday specific 10 AM restart after mid-morning stop (updated)
MONDAY_10AM_RESTART_WINDOW_START = time(10, 0, 0) # Exactly 10:00:00 AM for restart
MONDAY_10AM_RESTART_WINDOW_END = time(10, 0, 45) # The script will select a random time within this 45-second window.

# Sunday Schedule (remains unchanged)
SUNDAY_START_WINDOW_START = datetime.time(8, 55) # 8:55 AM
SUNDAY_START_WINDOW_END = datetime.time(9, 0) # 9:00 AM

SUNDAY_LUNCH_STOP_WINDOW_START = datetime.time(11, 57) # 11:57 AM
SUNDAY_LUNCH_STOP_WINDOW_END = datetime.time(12, 1) # 12:01 PM

SUNDAY_AFTERNOON_START_WINDOW_START = datetime.time(12, 57) # 12:57 PM
SUNDAY_AFTERNOON_START_WINDOW_END = datetime.time(13, 0) # 1:00 PM

SUNDAY_FINAL_STOP_WINDOW_START = datetime.time(17, 0) # 5:00 PM
SUNDAY_FINAL_STOP_WINDOW_END = datetime.time(17, 5) # 5:05 PM


# --- Global Variables for Daily Calculations (will be reset daily) ---
_last_calculated_date = None
_calculated_stop_times = {} # Stores datetime.time objects for precise stops
_event_executed_flags = {} # Stores boolean flags for each stop event to ensure it only triggers once per day


# --- Helper Functions ---
def get_random_time_in_window(start_time_obj, end_time_obj):
    """
    Generates a random datetime.time object within the specified time range.
    Assumes start_time_obj <= end_time_obj within a single day.
    If end_time_obj is before start_time_obj, returns start_time_obj.
    """
    start_seconds = start_time_obj.hour * 3600 + start_time_obj.minute * 60 + start_time_obj.second
    end_seconds = end_time_obj.hour * 3600 + end_time_obj.minute * 60 + end_time_obj.second
    
    time_diff_seconds = end_seconds - start_seconds
    
    if time_diff_seconds < 0:
        # This means end_time_obj is before start_time_obj.
        # This shouldn't happen with correctly defined windows, but handles the error.
        print(f"WARNING: Invalid time window provided to get_random_time_in_window: Start={start_time_obj}, End={end_time_obj}. Returning start time.")
        return start_time_obj
    elif time_diff_seconds == 0:
        return start_time_obj
    else:
        random_seconds_offset = random.randint(0, time_diff_seconds)
        
        random_total_seconds = start_seconds + random_seconds_offset
        
        hour = random_total_seconds // 3600
        minute = (random_total_seconds % 3600) // 60
        second = random_total_seconds % 60
        return datetime.time(hour, minute, second)


def is_timer_running(driver_instance):
    """
    Checks if the TimeCamp timer is currently running by looking for the 'Stop timer' button.
    Returns True if found, False otherwise.
    """
    try:
        WebDriverWait(driver_instance, SHORT_WAIT_SECONDS).until(
            EC.presence_of_element_located((By.XPATH, "//a[@id='timer-start-button' and .//span[contains(text(), 'Stop timer')]]"))
        )
        return True
    except TimeoutException:
        return False
    except WebDriverException as e:
        print(f"Warning: WebDriver error while checking timer status: {e}")
        return False # Assume not running or unable to check

def try_stop_timer(driver_instance):
    """Attempts to click the stop timer button if it's visible."""
    try:
        stop_btn = WebDriverWait(driver_instance, SHORT_WAIT_SECONDS).until(
            EC.element_to_be_clickable((By.XPATH, "//a[@id='timer-start-button' and .//span[contains(text(), 'Stop timer')]]"))
        )
        print("Found running timer. Attempting to stop it.")
        stop_btn.click()
        print("Timer stopped successfully.")
        return True
    except TimeoutException:
        print("Stop timer button not found or not clickable. Timer might not be running or already stopped.")
        return False
    except WebDriverException as e:
        print(f"Error stopping timer: {e}")
        return False

def _calculate_daily_times_and_reset_flags(current_date, current_day_of_week):
    """
    Calculates random stop times for the day and resets execution flags.
    This function should be called once per new day.
    """
    global _last_calculated_date, _calculated_stop_times, _event_executed_flags

    if _last_calculated_date != current_date:
        print(f"New day detected: {current_date}. Recalculating daily stop times and resetting flags.")
        _last_calculated_date = current_date
        _calculated_stop_times = {}
        _event_executed_flags = {}

        if current_day_of_week == 6: # Sunday
            _calculated_stop_times['SUNDAY_LUNCH_STOP'] = get_random_time_in_window(SUNDAY_LUNCH_STOP_WINDOW_START, SUNDAY_LUNCH_STOP_WINDOW_END)
            _calculated_stop_times['SUNDAY_FINAL_STOP'] = get_random_time_in_window(SUNDAY_FINAL_STOP_WINDOW_START, SUNDAY_FINAL_STOP_WINDOW_END)
        else: # Weekday (Monday-Saturday)
            _calculated_stop_times['WEEKDAY_MORNING_STOP_1'] = get_random_time_in_window(WEEKDAY_MORNING_STOP_1_WINDOW_START, WEEKDAY_MORNING_STOP_1_WINDOW_END)
            _calculated_stop_times['WEEKDAY_LUNCH_STOP'] = get_random_time_in_window(WEEKDAY_LUNCH_STOP_WINDOW_START, WEEKDAY_LUNCH_STOP_WINDOW_END)
            
            # Use Monday specific mid-morning stop if it's Monday
            if current_day_of_week == 0: # Monday is 0
                _calculated_stop_times['MONDAY_MID_MORNING_STOP'] = get_random_time_in_window(MONDAY_MID_MORNING_STOP_WINDOW_START, MONDAY_MID_MORNING_STOP_WINDOW_END)
                _calculated_stop_times['MONDAY_10AM_RESTART'] = get_random_time_in_window(MONDAY_10AM_RESTART_WINDOW_START, MONDAY_10AM_RESTART_WINDOW_END)
            
            # This is the single final stop for all weekdays (2 PM)
            _calculated_stop_times['WEEKDAY_DAILY_FINAL_STOP'] = get_random_time_in_window(WEEKDAY_DAILY_FINAL_STOP_WINDOW_START, WEEKDAY_DAILY_FINAL_STOP_WINDOW_END)
        
        # Initialize all event flags to False for the new day
        for key in _calculated_stop_times:
            _event_executed_flags[key] = False

        # --- NEW LOGIC: Mark past events as executed for the current day ---
        # Get current time for comparison (using local time as requested)
        now_time = datetime.datetime.now().time()
        for event_key, event_time in _calculated_stop_times.items():
            if now_time >= event_time:
                _event_executed_flags[event_key] = True
                print(f"Info: Marked past event '{event_key}' as executed for today ({current_date}).")


def check_for_nan_and_recover(driver_instance):
    """
    Checks for 'NaNh NaNm' on the page, refreshes and retries if found.
    Returns True if the page is clean, False if unable to recover after retries.
    """
    MAX_RETRIES_NAN = 3
    for attempt in range(1, MAX_RETRIES_NAN + 1):
        try:
            # Look for the specific text "NaNh NaNm" within any element
            # Using a more general XPath to find text content anywhere on the page
            nan_element = driver_instance.find_elements(By.XPATH, "//*[contains(text(), 'NaNh NaNm')]")
            
            if nan_element:
                print(f"WARNING: 'NaNh NaNm' detected on page (Attempt {attempt}/{MAX_RETRIES_NAN}). Refreshing to clear...")
                driver_instance.refresh()
                time.sleep(5) # Give page time to load after refresh
            else:
                print("'NaNh NaNm' not detected. Page appears ready.")
                return True # Page is clean
        except WebDriverException as e:
            print(f"WebDriver error during 'NaNh NaNm' check (Attempt {attempt}/{MAX_RETRIES_NAN}): {e}. Refreshing.")
            driver_instance.refresh()
            time.sleep(5)
        except Exception as e:
            print(f"Unexpected error during 'NaNh NaNm' check (Attempt {attempt}/{MAX_RETRIES_NAN}): {e}. Refreshing.")
            driver_instance.refresh()
            time.sleep(5)
    
    print(f"ERROR: 'NaNh NaNm' persisted after {MAX_RETRIES_NAN} attempts. Continuing, but timer start might fail.")
    return False # Failed to recover

def _get_current_shift_type(current_time_of_day, current_day_of_week, calculated_stop_times):
    """
    Determines the current shift type: 'work' or 'long_break'.
    All periods within the 6 AM - 2 PM weekday window are now 'work',
    EXCEPT for the Monday 9:30 AM - 10:00 AM explicit break.
    """
    
    # Determine the correct daily final stop time for the current day
    weekday_daily_final_stop_time = calculated_stop_times.get('WEEKDAY_DAILY_FINAL_STOP', WEEKDAY_DAILY_FINAL_STOP_WINDOW_END)

    # Sunday Logic: Entire period from start to final stop is 'work'
    if current_day_of_week == 6: # Sunday
        if current_time_of_day >= SUNDAY_START_WINDOW_START and current_time_of_day < SUNDAY_FINAL_STOP_WINDOW_END:
            return 'work'
        else:
            return 'long_break'
    # Weekday Logic (Monday-Saturday)
    else: 
        # Specific Monday 9:30 AM - 10:00 AM 'long_break'
        if current_day_of_week == 0: # If Monday
            monday_mid_morning_stop_end = calculated_stop_times.get('MONDAY_MID_MORNING_STOP', MONDAY_MID_MORNING_STOP_WINDOW_END)
            monday_10am_restart_start = calculated_stop_times.get('MONDAY_10AM_RESTART', MONDAY_10AM_RESTART_WINDOW_START)
            
            if current_time_of_day >= monday_mid_morning_stop_end and \
               current_time_of_day < monday_10am_restart_start:
                return 'long_break' # This is the explicit 9:30 AM - 10:00 AM break on Monday

        # Overnight long break: Before morning start or after daily final stop
        if (current_time_of_day < WEEKDAY_MORNING_START_WINDOW_START or
              current_time_of_day >= weekday_daily_final_stop_time):
            return 'long_break'
        
        # All other times during weekdays (6 AM to 2 PM, and outside Monday's special break) are 'work'
        return 'work'


def perform_post_sleep_health_check(driver_instance, current_day_of_week):
    """
    Performs health checks on the browser and TimeCamp timer after a sleep period.
    Refreshes the page if issues are detected.
    """
    try:
        # Check if the page is still on TimeCamp. If not, refresh.
        if TIMECAMP_SAML_URL not in driver_instance.current_url and "app.timecamp.com" not in driver_instance.current_url:
            print(f"WARNING: Browser navigated away from TimeCamp or crashed during sleep. Current URL: {driver_instance.current_url}. Refreshing page to recover.")
            driver_instance.get(TIMECAMP_SAML_URL) # Go back to the main URL
            time.sleep(5) # Give time to load
        
        # Re-check timer status after waking up, especially from long sleep
        re_check_timer_status = is_timer_running(driver_instance)
        
        # Determine what the timer *should* be doing at this exact moment after waking up
        now_after_sleep = datetime.datetime.now() # Using local time
        current_time_of_day_after_sleep = now_after_sleep.time()
        
        # Use the new _get_current_shift_type to determine desired state
        current_shift_type_after_sleep = _get_current_shift_type(current_time_of_day_after_sleep, current_day_of_week, _calculated_stop_times)
        should_be_running_after_sleep = (current_shift_type_after_sleep == 'work')


        if (should_be_running_after_sleep and not re_check_timer_status) or \
           (not should_be_running_after_sleep and re_check_timer_status):
            print(f"WARNING: Timer status is unexpected after waking up. Expected {'Running' if should_be_running_after_sleep else 'Stopped'}, but found {'Running' if re_check_timer_status else 'Stopped'}. Refreshing page to ensure correct state.")
            driver_instance.refresh()
            time.sleep(5) # Give time to load

        # NEW: Also check for the presence of a key element (e.g., the timer button)
        # if it's not a long break, as the page should be active.
        if current_shift_type_after_sleep != 'long_break':
            try:
                WebDriverWait(driver_instance, SHORT_WAIT_SECONDS).until(
                    EC.presence_of_element_located((By.ID, "timer-start-button"))
                )
                print("TimeCamp dashboard element (timer button) is present. Page appears responsive.")
            except TimeoutException:
                print(f"WARNING: TimeCamp dashboard element (timer button) not found within {SHORT_WAIT_SECONDS} seconds after sleep. Page might be stuck. Refreshing to recover.")
                driver_instance.refresh()
                time.sleep(5) # Give page time to load after refresh

    except WebDriverException as e:
        print(f"CRITICAL: WebDriver error during post-sleep health check: {e}. Attempting to refresh page.")
        driver_instance.refresh()
        time.sleep(5)
    except Exception as e:
        print(f"CRITICAL: Unexpected error during post-sleep health check: {e}. Attempting to refresh page.")
        driver_instance.refresh()
        time.sleep(5)

def wait_for_main_dashboard_load(driver_instance):
    """
    Waits for the main TimeCamp dashboard to load by checking for the timer button.
    Refreshes and retries if not found within the timeout.
    """
    MAX_LOAD_RETRIES = 3
    LOAD_TIMEOUT_SECONDS = 25 # User requested 25 seconds

    for attempt in range(1, MAX_LOAD_RETRIES + 1):
        try:
            print(f"Attempt {attempt}/{MAX_LOAD_RETRIES}: Waiting for TimeCamp dashboard (timer button) to load for {LOAD_TIMEOUT_SECONDS} seconds...")
            WebDriverWait(driver_instance, LOAD_TIMEOUT_SECONDS).until(
                EC.presence_of_element_located((By.ID, "timer-start-button"))
            )
            print("TimeCamp dashboard (timer button) found. Page loaded successfully.")
            return True
        except TimeoutException:
            print(f"WARNING: TimeCamp dashboard (timer button) not found within {LOAD_TIMEOUT_SECONDS} seconds (Attempt {attempt}/{MAX_LOAD_RETRIES}). Refreshing page...")
            driver_instance.refresh()
            time.sleep(5) # Give page time to reload
        except WebDriverException as e:
            print(f"WebDriver error during dashboard load check (Attempt {attempt}/{MAX_LOAD_RETRIES}): {e}. Refreshing page...")
            driver_instance.refresh()
            time.sleep(5)
        except Exception as e:
            print(f"Unexpected error during dashboard load check (Attempt {attempt}/{MAX_LOAD_RETRIES}): {e}. Refreshing page...")
            driver_instance.refresh()
            time.sleep(5)
    
    print(f"CRITICAL ERROR: TimeCamp dashboard did not load after {MAX_LOAD_RETRIES} attempts. Cannot proceed.")
    return False


def automate_timecamp_login():
    """
    Automates the login process for TimeCamp via SAML/SSO,
    handles the "Stay signed in?" prompt, and then clicks the "Start timer"
    and "Stop timer" buttons based on specified times, with retry logic.
    """
    driver = None
    try:
        print("Attempting to initialize browser and log in...")
        # Configure Chrome options for Brave browser
        chrome_options = Options()
        chrome_options.binary_location = BRAVE_PATH # Set Brave browser executable path
        print(f"Opening Brave browser from: {BRAVE_PATH}")
        print("Opening a new, temporary Brave profile.")

        # Initialize the Chrome WebDriver with the specified ChromeDriver path
        print(f"Using ChromeDriver from: {CHROMEDRIVER_PATH}")
        service = Service(executable_path=CHROMEDRIVER_PATH)
        driver = webdriver.Chrome(service=service, options=chrome_options)
        driver.maximize_window()

        # 1. Open TimeCamp SAML authentication page
        print(f"Navigating to: {TIMECAMP_SAML_URL}")
        driver.get(TIMECAMP_SAML_URL)

        retries = 0
        while retries < MAX_RETRIES:
            try:
                # Wait for the email input field on TimeCamp page
                email_input_timecamp = WebDriverWait(driver, WAIT_TIMEOUT_SECONDS).until(
                    EC.presence_of_element_located((By.NAME, "email"))
                )
                print("TimeCamp email input field found.")
                break
            except TimeoutException:
                retries += 1
                print(f"Error: TimeCamp email input field not found within {WAIT_TIMEOUT_SECONDS} seconds. Retrying ({retries}/{MAX_RETRIES})...")
                driver.refresh()
                time.sleep(2)
            except WebDriverException as e:
                print(f"WebDriver error during login email input check: {e}. Refreshing page and retrying.")
                driver.refresh()
                time.sleep(5)
        else:
            print(f"Failed to find TimeCamp email input field after {MAX_RETRIES} attempts. Exiting.")
            return

        # 2. Type in the email address on TimeCamp page
        print(f"Typing email: {EMAIL_ADDRESS} into TimeCamp field.")
        email_input_timecamp.send_keys(EMAIL_ADDRESS)

        retries = 0
        while retries < MAX_RETRIES:
            try:
                # 3. Click the "Log in with SSO" button on TimeCamp page
                sso_button = WebDriverWait(driver, WAIT_TIMEOUT_SECONDS).until(
                    EC.element_to_be_clickable((By.XPATH, "//button[contains(., 'Log in with SSO')]"))
                )
                print("TimeCamp 'Log in with SSO' button found and clickable.")
                print("Clicking 'Log in with SSO' button...")
                sso_button.click()
                break
            except TimeoutException:
                retries += 1
                print(f"Error: 'Log in with SSO' button not found or not clickable within {WAIT_TIMEOUT_SECONDS} seconds. Retrying ({retries}/{MAX_RETRIES})...")
                driver.refresh()
                time.sleep(2)
                try:
                    email_input_timecamp = WebDriverWait(driver, WAIT_TIMEOUT_SECONDS).until(
                        EC.presence_of_element_located((By.NAME, "email"))
                    )
                    email_input_timecamp.send_keys(EMAIL_ADDRESS)
                except TimeoutException:
                    print("Could not re-find email input after refresh. Exiting.")
                    return
            except WebDriverException as e:
                print(f"WebDriver error during SSO button click: {e}. Refreshing page and retrying.")
                driver.refresh()
                time.sleep(5)
                try:
                    email_input_timecamp = WebDriverWait(driver, WAIT_TIMEOUT_SECONDS).until(
                        EC.presence_of_element_located((By.NAME, "email"))
                    )
                    email_input_timecamp.send_keys(EMAIL_ADDRESS)
                except TimeoutException:
                    print("Could not re-find email input after refresh. Exiting.")
                    return
        else:
            print(f"Failed to click 'Log in with SSO' button after {MAX_RETRIES} attempts. Exiting.")
            return

        # 4. Handle Microsoft login redirection (directly enter email and password as it's a new browser)
        print("Waiting for redirection to Microsoft login page to enter email and password...")
        retries = 0
        while retries < MAX_RETRIES:
            try:
                email_input_microsoft = WebDriverWait(driver, WAIT_TIMEOUT_SECONDS).until(
                    EC.presence_of_element_located((By.ID, "i0116"))
                )
                print("Microsoft email input field (id='i0116') found.")
                print(f"Typing email: {EMAIL_ADDRESS} into Microsoft field.")
                email_input_microsoft.send_keys(EMAIL_ADDRESS)

                next_button = WebDriverWait(driver, WAIT_TIMEOUT_SECONDS).until(
                    EC.element_to_be_clickable((By.XPATH, "//input[@id='idSIButton9' and @value='Next']"))
                )
                print("Microsoft 'Next' button (id='idSIButton9', value='Next') found and clickable.")
                print("Clicking 'Next' button...")
                next_button.click()
                break
            except TimeoutException:
                retries += 1
                print(f"Error: Microsoft email input field or 'Next' button not found within {WAIT_TIMEOUT_SECONDS} seconds. Retrying ({retries}/{MAX_RETRIES})...")
                driver.get(TIMECAMP_SAML_URL)
                time.sleep(2)
                try:
                    email_input_timecamp = WebDriverWait(driver, WAIT_TIMEOUT_SECONDS).until(
                        EC.presence_of_element_located((By.NAME, "email"))
                    )
                    email_input_timecamp.send_keys(EMAIL_ADDRESS)
                    sso_button = WebDriverWait(driver, WAIT_TIMEOUT_SECONDS).until(
                        EC.element_to_be_clickable((By.XPATH, "//button[contains(., 'Log in with SSO')]"))
                    )
                    sso_button.click()
                except TimeoutException:
                    print("Could not re-initiate TimeCamp login after refresh. Exiting.")
                    return
            except WebDriverException as e:
                print(f"WebDriver error during SSO button click: {e}. Refreshing page and retrying.")
                driver.refresh()
                time.sleep(5)
                try:
                    email_input_timecamp = WebDriverWait(driver, WAIT_TIMEOUT_SECONDS).until(
                        EC.presence_of_element_located((By.NAME, "email"))
                    )
                    email_input_timecamp.send_keys(EMAIL_ADDRESS)
                    sso_button = WebDriverWait(driver, WAIT_TIMEOUT_SECONDS).until(
                        EC.element_to_be_clickable((By.XPATH, "//button[contains(., 'Log in with SSO')]"))
                    )
                    sso_button.click()
                except TimeoutException:
                    print("Could not re-initiate TimeCamp login after refresh. Exiting.")
                    return
        else:
            print(f"Failed to complete Microsoft email entry after {MAX_RETRIES} attempts. Exiting.")
            return

        # 5. Input password and click Sign in
        print("Attempting to input password on Microsoft login page...")
        retries = 0
        while retries < MAX_RETRIES:
            try:
                password_input = WebDriverWait(driver, WAIT_TIMEOUT_SECONDS).until(
                    EC.presence_of_element_located((By.ID, "i0118"))
                )
                print("Microsoft password input field (id='i0118') found.")
                print("Typing password...")
                password_input.send_keys(PASSWORD)

                signin_button = WebDriverWait(driver, WAIT_TIMEOUT_SECONDS).until(
                    EC.element_to_be_clickable((By.XPATH, "//input[@id='idSIButton9' and @value='Sign in']"))
                )
                print("Microsoft 'Sign in' button (id='idSIButton9', value='Sign in') found and clickable.")
                print("Clicking 'Sign in' button...")
                signin_button.click()
                break
            except TimeoutException:
                retries += 1
                print(f"Error: Microsoft password input field or 'Sign in' button not found within {WAIT_TIMEOUT_SECONDS} seconds. Retrying ({retries}/{MAX_RETRIES})...")
                driver.refresh()
                time.sleep(2)
                try:
                    email_input_timecamp = WebDriverWait(driver, WAIT_TIMEOUT_SECONDS).until(
                        EC.presence_of_element_located((By.NAME, "email"))
                    )
                    email_input_timecamp.send_keys(EMAIL_ADDRESS)
                    sso_button = WebDriverWait(driver, WAIT_TIMEOUT_SECONDS).until(
                        EC.element_to_be_clickable((By.XPATH, "//button[contains(., 'Log in with SSO')]"))
                    )
                    sso_button.click()
                except TimeoutException:
                    print("Could not re-initiate TimeCamp login after refresh for password step. Exiting.")
                    return
            except WebDriverException as e:
                print(f"WebDriver error during Microsoft password/signin button: {e}. Refreshing page and retrying.")
                driver.refresh()
            except Exception as e:
                print(f"WebDriver error during Microsoft password/signin button: {e}. Refreshing page and retrying.")
                driver.refresh()
                time.sleep(5)
                try:
                    email_input_timecamp = WebDriverWait(driver, WAIT_TIMEOUT_SECONDS).until(
                        EC.presence_of_element_located((By.NAME, "email"))
                    )
                    email_input_timecamp.send_keys(EMAIL_ADDRESS)
                    sso_button = WebDriverWait(driver, WAIT_TIMEOUT_SECONDS).until(
                        EC.element_to_be_clickable((By.XPATH, "//button[contains(., 'Log in with SSO')]"))
                    )
                    sso_button.click()
                except TimeoutException:
                    print("Could not re-initiate TimeCamp login after refresh for password step. Exiting.")
                    return
        else:
            print(f"Failed to complete Microsoft password entry after {MAX_RETRIES} attempts. Exiting.")
            return

        # 6. Handle "Stay signed in?" prompt
        print("Checking for 'Stay signed in?' prompt...")
        retries = 0
        while retries < MAX_RETRIES:
            try:
                dont_show_again_checkbox = WebDriverWait(driver, WAIT_TIMEOUT_SECONDS).until(
                    EC.element_to_be_clickable((By.ID, "KmsiCheckboxField"))
                )
                print("'Don't show this again' checkbox found.")
                if not dont_show_again_checkbox.is_selected():
                    print("Clicking 'Don't show this again' checkbox...")
                    dont_show_again_checkbox.click()
                else:
                    print("'Don't show this again' checkbox is already selected.")

                yes_button = WebDriverWait(driver, WAIT_TIMEOUT_SECONDS).until(
                    EC.element_to_be_clickable((By.XPATH, "//input[@id='idSIButton9' and @value='Yes']"))
                )
                print("Microsoft 'Yes' button found and clickable.")
                print("Clicking 'Yes' button...")
                yes_button.click()
                break
            except TimeoutException:
                retries += 1
                print(f"Timeout: 'Stay signed in?' prompt (checkbox or 'Yes' button) not found within {WAIT_TIMEOUT_SECONDS} seconds. Retrying ({retries}/{MAX_RETRIES})...")
                driver.refresh()
                time.sleep(2)
            except WebDriverException as e:
                print(f"WebDriver error during 'Stay signed in?' prompt: {e}. Refreshing page and retrying.")
                driver.refresh()
                time.sleep(5)
        else:
            print(f"Failed to handle 'Stay signed in?' prompt after {MAX_RETRIES} attempts. Continuing, as it might be skipped.")
            pass

        # NEW: After successful login, wait for the main TimeCamp dashboard to load properly
        if not wait_for_main_dashboard_load(driver):
            print("Failed to load TimeCamp dashboard after login. Exiting script.")
            return # Exit the function if dashboard doesn't load

        # --- Initial Daily Setup ---
        now = datetime.datetime.now()
        current_time_of_day = now.time()
        current_date = now.date()
        current_day_of_week = now.weekday()

        _calculate_daily_times_and_reset_flags(current_date, current_day_of_week)

        # Determine the current shift type at startup
        initial_shift_type = _get_current_shift_type(current_time_of_day, current_day_of_week, _calculated_stop_times)

        if initial_shift_type == 'work': # Only check for 'work' at startup now
            print(f"Script started at {now.strftime('%H:%M:%S')}. Current time is within an active work period. Proceeding directly to main polling loop.")
            # The initial perform_post_sleep_health_check is now covered by wait_for_main_dashboard_load
            # and the subsequent check_for_nan_and_recover in the loop.
            # No prompt, no initial deep sleep if within an active work block.
        else: # initial_shift_type is 'long_break'
            # Determine the *earliest upcoming start time* to wake up for
            next_calculated_start_datetime = None
            
            # Scenario 1: Current day's shift start (if it's still in the future)
            # This covers Sunday's specific start, and weekday's 6 AM start.
            if current_day_of_week == 6: # Sunday
                if current_time_of_day < SUNDAY_START_WINDOW_START:
                    next_calculated_start_datetime = datetime.datetime.combine(current_date, get_random_time_in_window(SUNDAY_START_WINDOW_START, SUNDAY_START_WINDOW_END))
            else: # Weekday (Mon-Sat)
                if current_time_of_day < WEEKDAY_MORNING_START_WINDOW_START:
                    next_calculated_start_datetime = datetime.datetime.combine(current_date, get_random_time_in_window(WEEKDAY_MORNING_START_WINDOW_START, WEEKDAY_MORNING_START_WINDOW_END))
                # For Monday, if currently in the 9:30-10 AM explicit long break.
                elif current_day_of_week == 0 and \
                     current_time_of_day >= _calculated_stop_times.get('MONDAY_MID_MORNING_STOP', MONDAY_MID_MORNING_STOP_WINDOW_END) and \
                     current_time_of_day < _calculated_stop_times.get('MONDAY_10AM_RESTART', MONDAY_10AM_RESTART_WINDOW_START):
                    next_calculated_start_datetime = datetime.datetime.combine(current_date, _calculated_stop_times.get('MONDAY_10AM_RESTART', MONDAY_10AM_RESTART_WINDOW_START))

            # Scenario 2: Next day's morning shift start (if no relevant start today, or today's shifts are done)
            # This handles cases where initial_shift_type is 'long_break' because it's after today's final stop,
            # or if next_calculated_start_datetime was not set in Scenario 1 because it's already past.
            if next_calculated_start_datetime is None or next_calculated_start_datetime <= now:
                days_to_add = 1
                next_start_window_start_time = WEEKDAY_MORNING_START_WINDOW_START
                next_start_window_end_time = WEEKDAY_MORNING_START_WINDOW_END

                if current_day_of_week == 5: # If Saturday, next start is Sunday
                    days_to_add = 1
                    next_start_window_start_time = SUNDAY_START_WINDOW_START
                    next_start_window_end_time = SUNDAY_START_WINDOW_END
                elif current_day_of_week == 6: # If Sunday, next start is Monday
                    days_to_add = 1 # Already Sunday, next day is Monday
                    # next_start_window_start_time and next_start_window_end_time are already for weekday
                
                next_day_date = now.date() + datetime.timedelta(days=days_to_add)
                next_calculated_start_datetime = datetime.datetime.combine(next_day_date, get_random_time_in_window(next_start_window_start_time, next_start_window_end_time))

            # --- Rest of the initial deep sleep logic ---
            time_until_next_shift_start_seconds = (next_calculated_start_datetime - now).total_seconds()

            # Define the threshold for "too early" (e.g., more than 5 hours before next shift)
            TOO_EARLY_THRESHOLD_SECONDS = 5 * 3600 # 5 hours

            # Removed the user input prompt. Script will now automatically wait.
            if time_until_next_shift_start_seconds > TOO_EARLY_THRESHOLD_SECONDS:
                print(f"It's currently {now.strftime('%Y-%m-%d %H:%M:%S')}. Your next shift is scheduled to start on {next_calculated_start_datetime.date()} at {next_calculated_start_datetime.strftime('%H:%M:%S')}.")
                print("It's too early for the next shift. Automatically waiting for it to start.")


            # --- Initial Deep Sleep Logic (re-using next_calculated_start_datetime) ---
            if next_calculated_start_datetime > now: # If the determined next start is in the future
                sleep_seconds = (next_calculated_start_datetime - now).total_seconds()
                if sleep_seconds > 5: # Only deep sleep if more than 5 seconds
                    print(f"Current time ({now.strftime('%H:%M:%S')}) is before the first shift. Going into deep sleep for {int(sleep_seconds / 60)} minutes until randomized start at {next_calculated_start_datetime.strftime('%H:%M')} on {next_calculated_start_datetime.date()}.")
                    time.sleep(sleep_seconds)
                    print(f"Woke up from deep sleep at {datetime.datetime.now().strftime('%H:%M:%S')}.")
                    perform_post_sleep_health_check(driver, current_day_of_week)
                    if not check_for_nan_and_recover(driver):
                        print("Warning: Could not clear 'NaNh NaNm' after deep sleep. Proceeding with caution.")
                else:
                    print("Current time is very close to the first shift start. Starting polling immediately.")
                    perform_post_sleep_health_check(driver, current_day_of_week)
                    if not check_for_nan_and_recover(driver):
                        print("Warning: Could not clear 'NaNh NaNm' at script start. Proceeding with caution.")
            else:
                # This case means next_calculated_start_datetime is in the past or current time,
                # which means we should just proceed to the main loop.
                print(f"Script started at {now.strftime('%H:%M:%S')}, and the determined next start time is in the past or current. Proceeding to main polling loop.")
                perform_post_sleep_health_check(driver, current_day_of_week)
                if not check_for_nan_and_recover(driver):
                    print("Warning: Could not clear 'NaNh NaNm' at script start. Proceeding with caution.")

    except Exception as e:
        # This catches any general exception during the initial login/setup phase
        print(f"CRITICAL ERROR during initial browser setup or login: {e}")
        print("Please check your BRAVE_PATH, CHROMEDRIVER_PATH, and network connection.")
        return # Exit the function if initial setup fails
    
    # This 'else' block will execute ONLY if the 'try' block above completes without an exception
    else: 
        # --- Main Polling Loop ---
        print("TimeCamp dashboard loaded. Starting continuous time and timer check.")
        
        while True: # This loop is intended to run indefinitely
            try: # This try-except is for general WebDriver issues within the polling loop
                now = datetime.datetime.now() # Using local time for current time
                current_time_of_day = now.time()
                current_date = now.date()
                current_day_of_week = now.weekday() # Monday is 0, Sunday is 6
                
                # Recalculate daily times and reset flags if it's a new day
                _calculate_daily_times_and_reset_flags(current_date, current_day_of_week)

                # --- Perform NaN check at the start of each polling iteration ---
                if not check_for_nan_and_recover(driver):
                    print("Warning: 'NaNh NaNm' detected or recovery failed during regular polling. Attempting to continue.")

                # Determine current shift type for logging and action
                current_shift_type = _get_current_shift_type(current_time_of_day, current_day_of_week, _calculated_stop_times)
                current_shift_label = ""
                if current_shift_type == 'work':
                    if current_day_of_week == 6: # Sunday
                        current_shift_label = "Sunday Work Shift"
                    else: # Weekday (Monday-Saturday)
                        # All are 'work' type, but labels indicate timer expectation for stops/restarts
                        # Check specific windows for more precise labeling
                        is_monday_mid_morning_stop_window = (current_day_of_week == 0 and 
                                                             current_time_of_day >= MONDAY_MID_MORNING_STOP_WINDOW_START and 
                                                             current_time_of_day < MONDAY_MID_MORNING_STOP_WINDOW_END)
                        is_weekday_mid_morning_stop_window = (current_day_of_week != 0 and 
                                                              current_time_of_day >= WEEKDAY_MORNING_STOP_1_WINDOW_START and 
                                                              current_time_of_day < WEEKDAY_MORNING_STOP_1_WINDOW_END)
                        is_lunch_stop_window = (current_time_of_day >= WEEKDAY_LUNCH_STOP_WINDOW_START and 
                                                current_time_of_day < WEEKDAY_LUNCH_STOP_WINDOW_END)

                        if is_monday_mid_morning_stop_window or is_weekday_mid_morning_stop_window or is_lunch_stop_window:
                            current_shift_label = "Scheduled Timer Stop Window (Timer OFF, will immediately restart)"
                        elif current_day_of_week == 0 and current_time_of_day < MONDAY_MID_MORNING_STOP_WINDOW_START:
                            current_shift_label = "Monday Early Morning Shift (Timer ON)"
                        elif current_day_of_week != 0 and current_time_of_day < WEEKDAY_MORNING_STOP_1_WINDOW_START:
                            current_shift_label = "Weekday Early Morning Shift (Timer ON)"
                        elif current_time_of_day >= WEEKDAY_MORNING_STOP_1_WINDOW_END and current_time_of_day < WEEKDAY_LUNCH_STOP_WINDOW_START:
                            current_shift_label = "Pre-Lunch Segment (Timer ON)"
                        elif current_time_of_day >= WEEKDAY_LUNCH_STOP_WINDOW_END and current_time_of_day < WEEKDAY_DAILY_FINAL_STOP_WINDOW_START:
                            current_shift_label = "Post-Lunch Segment (Timer ON)"
                        else:
                            current_shift_label = "Work Shift (Timer ON - Fallback)" # Fallback, should ideally not be hit
                else: # 'long_break'
                    # Determine the correct daily final stop time for the current day for labeling
                    weekday_daily_final_stop_time_for_label = _calculated_stop_times.get('WEEKDAY_DAILY_FINAL_STOP', WEEKDAY_DAILY_FINAL_STOP_WINDOW_END)

                    # Specific Monday 9:30 AM - 10:00 AM break
                    if current_day_of_week == 0 and \
                       current_time_of_day >= _calculated_stop_times.get('MONDAY_MID_MORNING_STOP', MONDAY_MID_MORNING_STOP_WINDOW_END) and \
                       current_time_of_day < _calculated_stop_times.get('MONDAY_10AM_RESTART', MONDAY_10AM_RESTART_WINDOW_START):
                        current_shift_label = "Monday Mid-Morning Explicit Break (Timer OFF, restarts 10 AM)"
                    elif current_day_of_week == 6:
                        if current_time_of_day < SUNDAY_START_WINDOW_START:
                            current_shift_label = "Pre-Sunday Shift (Long Break)"
                        else: # After Sunday's final stop
                            current_shift_label = "Post-Sunday Work Hours (Long Break)"
                    else: # Weekday long breaks (primarily overnight or after 2 PM)
                        if current_time_of_day < WEEKDAY_MORNING_START_WINDOW_START:
                            current_shift_label = "Pre-Work Hours (Long Break)"
                        elif current_time_of_day >= weekday_daily_final_stop_time_for_label:
                            current_shift_label = "Post-Work Hours (Long Break)"
                        else: # This should not be hit if _get_current_shift_type logic is tight
                            current_shift_label = "Unexpected Long Break State" 
                
                print(f"\n--- Polling at {now.strftime('%Y-%m-%d %H:%M:%S')} - Current Shift: {current_shift_label} ---")

                timer_is_running = is_timer_running(driver) # Initial check for this iteration
                print(f"TimeCamp timer status: {'Running' if timer_is_running else 'Stopped'}")

                # Determine if the timer *should* be running based on the current shift type
                # It should always be running during 'work' periods, unless it's a long break.
                should_be_running_for_timer = (current_shift_type == 'work')

                print(f"Timer should be running: {'Yes' if should_be_running_for_timer else 'No'}")


                # --- Action Phase: Prioritize immediate action ---
                action_performed_this_iteration = False # Flag to indicate if a start/stop occurred

                # 1. Check for specific STOP triggers (based on calculated precise stop times)
                stop_event_to_trigger = None
                if current_day_of_week == 6: # Sunday
                    if 'SUNDAY_LUNCH_STOP' in _calculated_stop_times and not _event_executed_flags['SUNDAY_LUNCH_STOP'] and \
                       current_time_of_day >= _calculated_stop_times['SUNDAY_LUNCH_STOP']:
                        stop_event_to_trigger = 'SUNDAY_LUNCH_STOP'
                    elif 'SUNDAY_FINAL_STOP' in _calculated_stop_times and not _event_executed_flags['SUNDAY_FINAL_STOP'] and \
                         current_time_of_day >= _calculated_stop_times['SUNDAY_FINAL_STOP']:
                        stop_event_to_trigger = 'SUNDAY_FINAL_STOP'
                else: # Weekday
                    # Check for Monday's specific mid-morning stop
                    if current_day_of_week == 0 and 'MONDAY_MID_MORNING_STOP' in _calculated_stop_times and not _event_executed_flags['MONDAY_MID_MORNING_STOP'] and \
                       current_time_of_day >= _calculated_stop_times['MONDAY_MID_MORNING_STOP']:
                        stop_event_to_trigger = 'MONDAY_MID_MORNING_STOP'
                    # Check for other weekdays' mid-morning stop
                    elif current_day_of_week != 0 and 'WEEKDAY_MORNING_STOP_1' in _calculated_stop_times and not _event_executed_flags['WEEKDAY_MORNING_STOP_1'] and \
                         current_time_of_day >= _calculated_stop_times['WEEKDAY_MORNING_STOP_1']:
                        stop_event_to_trigger = 'WEEKDAY_MORNING_STOP_1'
                    
                    elif 'WEEKDAY_LUNCH_STOP' in _calculated_stop_times and not _event_executed_flags['WEEKDAY_LUNCH_STOP'] and \
                         current_time_of_day >= _calculated_stop_times['WEEKDAY_LUNCH_STOP']:
                        stop_event_to_trigger = 'WEEKDAY_LUNCH_STOP'
                    
                    # Check for the daily final stop (2 PM)
                    elif 'WEEKDAY_DAILY_FINAL_STOP' in _calculated_stop_times and not _event_executed_flags['WEEKDAY_DAILY_FINAL_STOP'] and \
                         current_time_of_day >= _calculated_stop_times['WEEKDAY_DAILY_FINAL_STOP']:
                        stop_event_to_trigger = 'WEEKDAY_DAILY_FINAL_STOP'
                
                if stop_event_to_trigger and timer_is_running:
                    print(f"[{current_shift_label}] Time is {current_time_of_day.strftime('%H:%M:%S')}. Timer is Running. Triggered STOP action for {stop_event_to_trigger} at {_calculated_stop_times[stop_event_to_trigger].strftime('%H:%M:%S')}. Attempting to STOP timer.")
                    if try_stop_timer(driver):
                        timer_is_running = False
                        action_performed_this_iteration = True
                        _event_executed_flags[stop_event_to_trigger] = True # Mark as executed for today
                        # NEW: Check for NaN after stopping the timer
                        if not check_for_nan_and_recover(driver):
                            print("Warning: Could not clear 'NaNh NaNm' after stopping timer. Proceeding with caution.")


                # 2. Handle starting the timer if it should be running (for timer) but is not
                if should_be_running_for_timer and not timer_is_running:
                    print(f"[{current_shift_label}] Time is {current_time_of_day.strftime('%H:%M:%S')}. Timer is Stopped. Timer should be running. Attempting to START timer.")
                    
                    # Add 5-second initial wait before clicking to start timer
                    print("Waiting 5 seconds before attempting to start timer to ensure page stability...")
                    time.sleep(5)
                    
                    # NEW: Check for NaN after the wait, before attempting to start
                    if not check_for_nan_and_recover(driver):
                        print("Warning: Could not clear 'NaNh NaNm' before starting timer. Proceeding with caution.")
                        # If NaN persists, it might be better to skip this start attempt and retry on next poll
                        # or implement more aggressive recovery. For now, we proceed.

                    try:
                        start_timer_button = WebDriverWait(driver, SHORT_WAIT_SECONDS).until(
                            EC.element_to_be_clickable((By.ID, "timer-start-button"))
                        )
                        start_timer_button.click()
                        print("Successfully clicked 'Start timer' button. Timer is now running.") # Explicit restart message
                        timer_is_running = True
                        action_performed_this_iteration = True
                    except TimeoutException:
                        print(f"Error: 'Start timer' button not found or clickable within {SHORT_WAIT_SECONDS} seconds. Refreshing page and retrying on next poll.")
                        driver.refresh()
                        time.sleep(5)
                    except WebDriverException as e:
                        print(f"WebDriver Error starting timer: {e}. Refreshing page and retrying on next poll.")
                        driver.refresh()
                        time.sleep(5)

                # 3. If no action was performed, but timer is in desired state (for logging consistency)
                if not action_performed_this_iteration:
                    if timer_is_running == should_be_running_for_timer:
                        print(f"[{current_shift_label}] Time is {current_time_of_day.strftime('%H:%M:%S')}. Timer is in desired state ({'Running' if timer_is_running else 'Stopped'}). No action needed.")
                    else:
                        # This case means timer is running but should be off, or vice versa,
                        # but no action was triggered (e.g., due to a previous error or very brief overlap).
                        print(f"[{current_shift_label}] Time is {current_time_of_day.strftime('%H:%M:%S')}. WARNING: Timer state ({'Running' if timer_is_running else 'Stopped'}) does not match desired state ({'Running' if should_be_running_for_timer else 'Stopped'}), but no action was triggered. This might indicate a logic error or a very brief window.")

                # --- Determine Next Event and Log It (Revised for clarity and accuracy) ---
                next_event_datetime = None
                next_event_label = ""
                
                # List all potential future events for today (stops and starts)
                potential_events_today = []

                # Add calculated stop times if they haven't been executed and are in the future
                # For weekdays, check all three stop types based on the day
                if current_day_of_week == 6: # Sunday stops
                    if 'SUNDAY_LUNCH_STOP' in _calculated_stop_times and not _event_executed_flags['SUNDAY_LUNCH_STOP']:
                        potential_events_today.append((datetime.datetime.combine(current_date, _calculated_stop_times['SUNDAY_LUNCH_STOP']), "stop (sunday lunch stop)"))
                    if 'SUNDAY_FINAL_STOP' in _calculated_stop_times and not _event_executed_flags['SUNDAY_FINAL_STOP']:
                        potential_events_today.append((datetime.datetime.combine(current_date, _calculated_stop_times['SUNDAY_FINAL_STOP']), "stop (sunday final stop)"))
                else: # Weekday stops
                    # Mid-morning stop (Monday specific vs. general weekday)
                    if current_day_of_week == 0: # Monday
                        if 'MONDAY_MID_MORNING_STOP' in _calculated_stop_times and not _event_executed_flags['MONDAY_MID_MORNING_STOP']:
                            potential_events_today.append((datetime.datetime.combine(current_date, _calculated_stop_times['MONDAY_MID_MORNING_STOP']), "stop (monday mid-morning stop)"))
                        # Monday 10 AM restart
                        if 'MONDAY_10AM_RESTART' in _calculated_stop_times and not _event_executed_flags['MONDAY_10AM_RESTART']:
                            potential_events_today.append((datetime.datetime.combine(current_date, _calculated_stop_times['MONDAY_10AM_RESTART']), "start (monday 10am restart)"))
                    else: # Other weekdays
                        if 'WEEKDAY_MORNING_STOP_1' in _calculated_stop_times and not _event_executed_flags['WEEKDAY_MORNING_STOP_1']:
                            potential_events_today.append((datetime.datetime.combine(current_date, _calculated_stop_times['WEEKDAY_MORNING_STOP_1']), "stop (weekday mid-morning stop)"))
                    
                    # Lunch stop
                    if 'WEEKDAY_LUNCH_STOP' in _calculated_stop_times and not _event_executed_flags['WEEKDAY_LUNCH_STOP']:
                        potential_events_today.append((datetime.datetime.combine(current_date, _calculated_stop_times['WEEKDAY_LUNCH_STOP']), "stop (weekday lunch stop)"))
                    
                    # Daily final stop (2 PM)
                    if 'WEEKDAY_DAILY_FINAL_STOP' in _calculated_stop_times and not _event_executed_flags['WEEKDAY_DAILY_FINAL_STOP']:
                        potential_events_today.append((datetime.datetime.combine(current_date, _calculated_stop_times['WEEKDAY_DAILY_FINAL_STOP']), "stop (weekday daily final stop)"))

                # If current shift is long_break, always consider current day's start first
                # This covers the Monday 9:30-10 AM explicit break as well
                if current_shift_type == 'long_break':
                    current_day_start_dt = None
                    if current_day_of_week == 6: # Sunday
                        if current_time_of_day < SUNDAY_START_WINDOW_END: # If before or within Sunday start window
                            current_day_start_dt = datetime.datetime.combine(current_date, get_random_time_in_window(SUNDAY_START_WINDOW_START, SUNDAY_START_WINDOW_END))
                    elif current_day_of_week == 0: # Monday, check for 10 AM restart
                         if current_time_of_day < _calculated_stop_times.get('MONDAY_10AM_RESTART', MONDAY_10AM_RESTART_WINDOW_START):
                            current_day_start_dt = datetime.datetime.combine(current_date, _calculated_stop_times.get('MONDAY_10AM_RESTART', MONDAY_10AM_RESTART_WINDOW_START))
                    else: # Other weekdays
                        if current_time_of_day < WEEKDAY_MORNING_START_WINDOW_END: # If before or within Weekday morning start window
                            current_day_start_dt = datetime.datetime.combine(current_date, get_random_time_in_window(WEEKDAY_MORNING_START_WINDOW_START, WEEKDAY_MORNING_START_WINDOW_END))
                    
                    if current_day_start_dt and current_day_start_dt > now:
                        # Only add if it's the actual next event and not past.
                        # This avoids adding duplicate 'start' events if already covered by potential_events_today.
                        if next_event_datetime is None or current_day_start_dt < next_event_datetime:
                            potential_events_today.append((current_day_start_dt, "start (current day shift/restart)"))

                # Find the earliest event for today
                earliest_today_event = None
                if potential_events_today:
                    # Filter out events that are in the past relative to 'now'
                    future_events_today = [e for e in potential_events_today if e[0] > now]
                    if future_events_today:
                        earliest_today_event = min(future_events_today, key=lambda x: x[0])
                
                # If no more events today, or if we are after all shifts today, calculate next day's morning start
                if earliest_today_event is None:
                    days_until_next_shift_start = 1
                    next_start_window_start_time = WEEKDAY_MORNING_START_WINDOW_START
                    next_start_window_end_time = WEEKDAY_MORNING_START_WINDOW_END

                    if current_day_of_week == 5: # If Saturday, next start is Sunday
                        days_until_next_shift_start = 1
                        next_start_window_start_time = SUNDAY_START_WINDOW_START
                        next_start_window_end_time = SUNDAY_START_WINDOW_END
                    elif current_day_of_week == 6: # If Sunday, next start is Monday
                        days_until_next_shift_start = 1 # Already Sunday, next day is Monday
                        # next_start_window_start_time and next_start_window_end_time are already for weekday
                    
                    next_day_date = now.date() + datetime.timedelta(days=days_until_next_shift_start)
                    next_event_datetime = datetime.datetime.combine(next_day_date, get_random_time_in_window(next_start_window_start_time, next_start_window_end_time))
                    next_event_label = "start (next day)"
                else:
                    next_event_datetime = earliest_today_event[0]
                    next_event_label = earliest_today_event[1]


                if next_event_datetime:
                    print(f"Next event ({next_event_label}) at {next_event_datetime.strftime('%H:%M:%S')} on {next_event_datetime.date()}.")
                else:
                    print("No clear next event determined for sleep calculation. This should not happen. Defaulting to polling interval.")
                    # Fallback to default polling if somehow next_event_datetime is not set
                    next_event_datetime = now + datetime.timedelta(minutes=POLLING_INTERVAL_MINUTES)
                    next_event_label = "fallback polling"


                # --- Sleep Determination Phase ---
                sleep_duration_for_this_iteration = 1 # Default to minimal sleep for responsiveness

                if action_performed_this_iteration:
                    # If an action (start/stop) just occurred, sleep minimally to re-evaluate quickly
                    sleep_duration_for_this_iteration = 1
                    print("Action performed this iteration. Re-evaluating immediately.")
                elif current_shift_type == 'long_break':
                    # If in a long break, sleep precisely until the next start event (next day or afternoon).
                    time_to_next_event_seconds = (next_event_datetime - now).total_seconds()
                    if time_to_next_event_seconds < 0:
                        time_to_next_event_seconds = 1
                    sleep_duration_for_this_iteration = time_to_next_event_seconds
                    print(f"In long break. Next event ({next_event_label}) at {next_event_datetime.strftime('%H:%M:%S')} on {next_event_datetime.date()}. Sleeping for {int(sleep_duration_for_this_iteration / 60)} minutes and {int(sleep_duration_for_this_iteration % 60)} seconds.")
                    if "next day" in next_event_label or "current day shift" in next_event_label or "monday 10am restart" in next_event_label:
                        print(f"CONFIRMATION: All shifts for today ({current_date.strftime('%Y-%m-%d')}) are complete (or not started yet). Script is now sleeping until the next shift starts on {next_event_datetime.date()} at {next_event_datetime.strftime('%H:%M:%S')}.")
                else: # current_shift_type is 'work' (this covers all periods that are not 'long_break')
                    # During a 'work' period:
                    time_to_next_event_seconds = (next_event_datetime - now).total_seconds()
                    if time_to_next_event_seconds < 0:
                        time_to_next_event_seconds = 1

                    # If the next event is imminent (within polling interval + buffer), sleep precisely until then.
                    if time_to_next_event_seconds <= POLLING_INTERVAL_MINUTES * 60 + 5:
                        sleep_duration_for_this_iteration = time_to_next_event_seconds
                        print(f"Current shift type is '{current_shift_type}'. Next event ({next_event_label}) is imminent. Sleeping precisely until then.")
                    elif timer_is_running: # If timer is running and next event is far, use 8-min polling.
                        sleep_duration_for_this_iteration = POLLING_INTERVAL_MINUTES * 60
                        print(f"Current shift type is '{current_shift_type}'. Timer is running and next event is far. Sleeping for {POLLING_INTERVAL_MINUTES} minutes.")
                    else: # Timer is not running, but should be (because current_shift_type is 'work'), and next event is far. Need to be responsive to start it.
                        sleep_duration_for_this_iteration = 1
                        print(f"Current shift type is '{current_shift_type}'. Timer is stopped but should be running. Checking for start action immediately.")


                # Ensure sleep duration is not negative or zero
                sleep_duration_for_this_iteration = max(1, sleep_duration_for_this_iteration) # Minimum 1 second sleep

                # Wait for the calculated duration
                print(f"Waiting for {int(sleep_duration_for_this_iteration / 60)} minutes and {int(sleep_duration_for_this_iteration % 60)} seconds before next check...")
                time.sleep(sleep_duration_for_this_iteration)

            except WebDriverException as e:
                print(f"A WebDriver-related error occurred during this polling iteration: {e}")
                print("Refreshing page to attempt recovery and continue the loop.")
                driver.refresh()
                time.sleep(5) # Give time to load after refresh
            except Exception as e:
                print(f"An unexpected error occurred during this polling iteration: {e}")
                print("Refreshing page to attempt recovery and continue the loop.")
                driver.refresh()
                time.sleep(5) # Give time to load after refresh

        print("Automation loop finished for the day.") # This line will only be reached if the while True loop has a 'break' condition.

    finally: # This 'finally' block is at the top-level of the function
        if driver:
            print(f"Keeping browser open for {WAIT_TIMEOUT_SECONDS} seconds before closing...")
            time.sleep(WAIT_TIMEOUT_SECONDS)
            driver.quit()
            print("Browser closed.")
        input("Press Enter to exit...") # Keeps the console open for viewing output

if __name__ == "__main__":
    try:
        automate_timecamp_login()
    except Exception as e:
        print(f"\nCRITICAL ERROR: The script encountered an unhandled exception: {e}")
        print("Please review the error message and ensure all paths and dependencies are correct.")
    finally:
        # This ensures the console stays open regardless of what happens
        input("\nPress Enter to exit...")
