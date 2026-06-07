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
RESTART_DELAY_SECONDS = 5  # Short delay after stopping to attempt immediate restart
# Default polling interval for active shifts, and for long break checks if not sleeping precisely.
POLLING_INTERVAL_MINUTES = 8


# Define fixed time points for comparison (AM/PM)
# Weekday Schedule (Monday-Friday) - New: 3:30 AM to 11:30 AM with a lunch break

# Start of the workday window
WEEKDAY_SCHEDULE_START_WINDOW_START = datetime.time(3, 26)  # New: Start window at 3:25 AM
WEEKDAY_SCHEDULE_START_WINDOW_END = datetime.time(3, 30)    # New: End window at 3:30 AM

# Lunch break stop window (window used to pick a randomized STOP time during the morning)
WEEKDAY_LUNCH_BREAK_STOP_WINDOW_START = datetime.time(6, 59) # Example: randomized stop around 03:28
WEEKDAY_LUNCH_BREAK_STOP_WINDOW_END = datetime.time(7, 2)    # Example: randomized stop end range

# Lunch break resume window (window used to pick a randomized RESTART time after the short stop)
WEEKDAY_LUNCH_BREAK_RESUME_WINDOW_START = datetime.time(7, 58) # Example: randomized resume around 03:31
WEEKDAY_LUNCH_BREAK_RESUME_WINDOW_END = datetime.time(8, 0)    # Example: randomized resume end range

# Final end of the workday window (window used to pick the randomized end-of-shift STOP time)
WEEKDAY_SCHEDULE_END_WINDOW_START = datetime.time(11, 30) # Example: randomized end-of-shift around 03:34
WEEKDAY_SCHEDULE_END_WINDOW_END = datetime.time(11, 33)    # Example: randomized end-of-shift end range

# Monday specific mid-morning stop (remains the same as before)
MONDAY_MID_MORNING_STOP_WINDOW_START = datetime.time(9, 29, 45) # 9:29 AM and 45 seconds for Monday's mid-morning stop
MONDAY_MID_MORNING_STOP_WINDOW_END = datetime.time(9, 29, 55) # 9:29 AM and 55 seconds for Monday's mid-morning stop

# Monday specific 10 AM restart after mid-morning stop (updated)
MONDAY_10AM_RESTART_WINDOW_START = datetime.time(9, 45, 0) # Exactly 10:00:00 AM for restart
MONDAY_10AM_RESTART_WINDOW_END = datetime.time(9, 45, 45) # The script will select a random time within this 45-second window.

# Saturday Schedule (remains unchanged; uses SUNDAY_* variables)
SUNDAY_SCHEDULE_START_WINDOW_START = datetime.time(8, 55)
SUNDAY_SCHEDULE_START_WINDOW_END = datetime.time(9, 0)

SUNDAY_LUNCH_BREAK_STOP_WINDOW_START = datetime.time(11, 57)
SUNDAY_LUNCH_BREAK_STOP_WINDOW_END = datetime.time(12, 1)

SUNDAY_AFTERNOON_RESUME_WINDOW_START = datetime.time(12, 57)
SUNDAY_AFTERNOON_RESUME_WINDOW_END = datetime.time(13, 0)

SUNDAY_SCHEDULE_END_WINDOW_START = datetime.time(17, 0)
SUNDAY_SCHEDULE_END_WINDOW_END = datetime.time(17, 5)


# --- Global Variables for Daily Calculations (will be reset daily) ---
_last_calculated_date = None
_calculated_stop_times = {} # Stores datetime.time objects for precise stops
_event_executed_flags = {} # Stores boolean flags for each stop event to ensure it only triggers once per day
_shutdown_scheduled = False # Flag for autoshutdown after final stop


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

def _calculate_daily_times_and_reset_flags(current_date, current_day_of_week, driver_instance):
    global _last_calculated_date, _calculated_stop_times, _event_executed_flags, _shutdown_scheduled

    if _last_calculated_date != current_date:
        print(f"New day detected: {current_date}. Recalculating daily stop times and resetting flags.")
        _last_calculated_date = current_date
        _calculated_stop_times = {}
        _event_executed_flags = {}
        _shutdown_scheduled = False  # Reset shutdown flag for new day

        # Define stop times based on day
        # NOTE: Saturday (weekday number 5) now uses the previous Sunday schedule variables.
        if current_day_of_week == 5:  # Saturday (was previously Sunday)
            _calculated_stop_times['SUNDAY_SCHEDULE_START'] = get_random_time_in_window(SUNDAY_SCHEDULE_START_WINDOW_START, SUNDAY_SCHEDULE_START_WINDOW_END)
            _calculated_stop_times['SUNDAY_LUNCH_BREAK_STOP'] = get_random_time_in_window(SUNDAY_LUNCH_BREAK_STOP_WINDOW_START, SUNDAY_LUNCH_BREAK_STOP_WINDOW_END)
            _calculated_stop_times['SUNDAY_AFTERNOON_STOP'] = get_random_time_in_window(SUNDAY_AFTERNOON_RESUME_WINDOW_START, SUNDAY_AFTERNOON_RESUME_WINDOW_END)
            _calculated_stop_times['SUNDAY_SCHEDULE_END'] = get_random_time_in_window(SUNDAY_SCHEDULE_END_WINDOW_START, SUNDAY_SCHEDULE_END_WINDOW_END)
        else:  # Weekday
            _calculated_stop_times['WEEKDAY_SCHEDULE_START'] = get_random_time_in_window(WEEKDAY_SCHEDULE_START_WINDOW_START, WEEKDAY_SCHEDULE_START_WINDOW_END)
            _calculated_stop_times['WEEKDAY_LUNCH_BREAK_STOP'] = get_random_time_in_window(WEEKDAY_LUNCH_BREAK_STOP_WINDOW_START, WEEKDAY_LUNCH_BREAK_STOP_WINDOW_END)
            # Add an afternoon stop for weekdays (acts as second brief stop similar to Sunday)
            _calculated_stop_times['WEEKDAY_AFTERNOON_STOP'] = get_random_time_in_window(WEEKDAY_LUNCH_BREAK_RESUME_WINDOW_START, WEEKDAY_LUNCH_BREAK_RESUME_WINDOW_END)
            _calculated_stop_times['WEEKDAY_SCHEDULE_END'] = get_random_time_in_window(WEEKDAY_SCHEDULE_END_WINDOW_START, WEEKDAY_SCHEDULE_END_WINDOW_END)

            if current_day_of_week == 0:  # Monday
                _calculated_stop_times['MONDAY_MID_MORNING_STOP'] = get_random_time_in_window(MONDAY_MID_MORNING_STOP_WINDOW_START, MONDAY_MID_MORNING_STOP_WINDOW_END)
                _calculated_stop_times['MONDAY_10AM_RESTART'] = get_random_time_in_window(MONDAY_10AM_RESTART_WINDOW_START, MONDAY_10AM_RESTART_WINDOW_END)

        # Reset all flags
        for key in _calculated_stop_times:
            _event_executed_flags[key] = False

        # Mark past events
        now_time = datetime.datetime.now().time()
        for event_key, event_time in _calculated_stop_times.items():
            if now_time >= event_time:
                _event_executed_flags[event_key] = True
                print(f"Info: Marked past event '{event_key}' as executed for today ({current_date}).")

        # Final stop enforcement
        final_key = 'WEEKDAY_SCHEDULE_END' if current_day_of_week != 5 else 'SUNDAY_SCHEDULE_END'
        final_stop_time = _calculated_stop_times.get(final_key)

        if final_stop_time and now_time >= final_stop_time:
            print(f"Current time ({now_time}) is past today's final stop ({final_stop_time}). Checking timer status...")
            if is_timer_running(driver_instance):
                print("Timer is still running after scheduled end. Attempting to stop.")
                try_stop_timer(driver_instance)
            else:
                print("Timer is already stopped.")
            # Initiate autoshutdown after final stop
            print("Autoshutdown scheduled for 5 minutes.")
            os.system('shutdown /s /t 300')
            response = input("Do you want to halt the shutdown? (y/n): ").strip().lower()
            if response == 'y':
                os.system('shutdown /a')
                print("Shutdown halted.")
            else:
                print("Shutdown proceeding.")
        
        
        
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
    # Use calculated randomized times for start/end
    # Saturday (5) uses the special weekend schedule variables (previously labeled 'SUNDAY_*')
    if current_day_of_week == 5:  # Saturday
        sunday_start = calculated_stop_times.get('SUNDAY_SCHEDULE_START', SUNDAY_SCHEDULE_START_WINDOW_START)
        sunday_end = calculated_stop_times.get('SUNDAY_SCHEDULE_END', SUNDAY_SCHEDULE_START_WINDOW_END)

        if sunday_start <= current_time_of_day < sunday_end:
            return 'work'
        else:
            return 'long_break'

    else:  # Weekday (Mon-Fri) and Sunday will be treated as long_break by default
        weekday_start = calculated_stop_times.get('WEEKDAY_SCHEDULE_START', WEEKDAY_SCHEDULE_START_WINDOW_START)
        weekday_end = calculated_stop_times.get('WEEKDAY_SCHEDULE_END', WEEKDAY_SCHEDULE_END_WINDOW_END)

        if current_time_of_day < weekday_start or current_time_of_day >= weekday_end:
            return 'long_break'
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

        _calculate_daily_times_and_reset_flags(current_date, current_day_of_week, driver_instance=driver)

        # Determine the current shift type at startup
        initial_shift_type = _get_current_shift_type(current_time_of_day, current_day_of_week, _calculated_stop_times)

        if initial_shift_type == 'work': # Only check for 'work' at startup now
            print(f"Script started at {now.strftime('%H:%M:%S')}. Current time is within an active work period. Proceeding directly to main polling loop.")
            # The initial perform_post_sleep_health_check is now covered by wait_for_main_dashboard_load
            # and the subsequent check_for_nan_and_recover in the loop.
            # No prompt, no initial deep sleep if within a active work block.
        else: # initial_shift_type is 'long_break'
            # Determine the *earliest upcoming start time* to wake up for
            next_calculated_start_datetime = None

            # Scenario 1: Current day's shift start (if it's still in the future)
            # Saturday now uses the special (previously Sunday) schedule
            if current_day_of_week == 5: # Saturday
                if current_time_of_day < SUNDAY_SCHEDULE_START_WINDOW_START:
                    next_calculated_start_datetime = datetime.datetime.combine(current_date, get_random_time_in_window(SUNDAY_SCHEDULE_START_WINDOW_START, SUNDAY_SCHEDULE_START_WINDOW_END))
            else: # Weekday (Mon-Fri) or Sunday (off)
                # --- NEW: If within weekday start window, start immediately ---
                if WEEKDAY_SCHEDULE_START_WINDOW_START <= current_time_of_day <= WEEKDAY_SCHEDULE_START_WINDOW_END:
                    print(f"Current time ({now.strftime('%H:%M:%S')}) is within the weekday start window ({WEEKDAY_SCHEDULE_START_WINDOW_START.strftime('%H:%M')} - {WEEKDAY_SCHEDULE_START_WINDOW_END.strftime('%H:%M')}). Starting work shift immediately.")
                    perform_post_sleep_health_check(driver, current_day_of_week)
                    if not check_for_nan_and_recover(driver):
                        print("Warning: Could not clear 'NaNh NaNm' at script start. Proceeding with caution.")
                    # Skip deep sleep and proceed to polling loop
                elif current_time_of_day < WEEKDAY_SCHEDULE_START_WINDOW_START:
                    next_calculated_start_datetime = datetime.datetime.combine(current_date, get_random_time_in_window(WEEKDAY_SCHEDULE_START_WINDOW_START, WEEKDAY_SCHEDULE_START_WINDOW_END))
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
                next_start_window_start_time = WEEKDAY_SCHEDULE_START_WINDOW_START
                next_start_window_end_time = WEEKDAY_SCHEDULE_START_WINDOW_END

                # If it's Saturday today, the next workday will be Monday (skip Sunday)
                if current_day_of_week == 5: # Saturday -> next start is Monday (in 2 days)
                    days_to_add = 2
                elif current_day_of_week == 6: # Sunday -> next start is Monday
                    days_to_add = 1
                
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
            if next_calculated_start_datetime > now:  # If the determined next start is in the future
                # Determine the configured start window (weekday vs saturday-special)
                if current_day_of_week == 5:
                    window_start_time = SUNDAY_SCHEDULE_START_WINDOW_START
                    window_end_time = SUNDAY_SCHEDULE_START_WINDOW_END
                else:
                    window_start_time = WEEKDAY_SCHEDULE_START_WINDOW_START
                    window_end_time = WEEKDAY_SCHEDULE_START_WINDOW_END

                window_start_dt = datetime.datetime.combine(current_date, window_start_time)

                # If we're before the start of the window, deep sleep until the window starts
                if now < window_start_dt:
                    time_to_window_start = (window_start_dt - now).total_seconds()
                    if time_to_window_start > 5:
                        print(f"Current time ({now.strftime('%H:%M:%S')}) is before the start window. Going into deep sleep for {int(time_to_window_start)} seconds until window start at {window_start_dt.strftime('%H:%M:%S')}.")
                        time.sleep(time_to_window_start)

                # At (or just after) window start: pick randomized start inside the window
                perform_post_sleep_health_check(driver, current_day_of_week)
                if not check_for_nan_and_recover(driver):
                    print("Warning: Could not clear 'NaNh NaNm' after deep sleep. Proceeding with caution.")

                randomized_start_time = get_random_time_in_window(window_start_time, window_end_time)
                randomized_start_dt = datetime.datetime.combine(current_date, randomized_start_time)
                now_after = datetime.datetime.now()

                # If randomized start is still in the future, sleep the small remaining seconds
                if randomized_start_dt > now_after:
                    sleep_seconds = (randomized_start_dt - now_after).total_seconds()
                    if sleep_seconds > 0:
                        print(f"Sleeping {int(sleep_seconds)} seconds until randomized start at {randomized_start_dt.strftime('%H:%M:%S')}.")
                        time.sleep(sleep_seconds)

                # Final wake at randomized start
                print(f"Woke up from deep sleep at {datetime.datetime.now().strftime('%H:%M:%S')}.")

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
                _calculate_daily_times_and_reset_flags(current_date, current_day_of_week, driver_instance=driver)

                # --- Perform NaN check at the start of each polling iteration ---
                if not check_for_nan_and_recover(driver):
                    print("Warning: 'NaNh NaNm' detected or recovery failed during regular polling. Attempting to continue.")

                # Determine current shift type for logging and action
                current_shift_type = _get_current_shift_type(current_time_of_day, current_day_of_week, _calculated_stop_times)
                # Build a descriptive label for logs (e.g., 'Start', 'Morning', 'Lunch (brief stop — will restart)', 'Lunch Resume', 'End')
                current_shift_label = current_shift_type

                # Prepare commonly used event times (fallback to configured windows)
                # Saturday uses the special weekend schedule variables (previously labeled 'SUNDAY_*')
                if current_day_of_week == 5:
                    start_time = _calculated_stop_times.get('SUNDAY_SCHEDULE_START', SUNDAY_SCHEDULE_START_WINDOW_START)
                    lunch_stop = _calculated_stop_times.get('SUNDAY_LUNCH_BREAK_STOP', SUNDAY_LUNCH_BREAK_STOP_WINDOW_START)
                    lunch_resume = _calculated_stop_times.get('SUNDAY_AFTERNOON_RESUME', SUNDAY_AFTERNOON_RESUME_WINDOW_START)
                    end_time = _calculated_stop_times.get('SUNDAY_SCHEDULE_END', SUNDAY_SCHEDULE_END_WINDOW_START)
                else:
                    start_time = _calculated_stop_times.get('WEEKDAY_SCHEDULE_START', WEEKDAY_SCHEDULE_START_WINDOW_START)
                    lunch_stop = _calculated_stop_times.get('WEEKDAY_LUNCH_BREAK_STOP', WEEKDAY_LUNCH_BREAK_STOP_WINDOW_START)
                    # Treat the previous 'resume' window as an afternoon stop so weekdays have two brief stops
                    afternoon_stop = _calculated_stop_times.get('WEEKDAY_AFTERNOON_STOP', WEEKDAY_LUNCH_BREAK_RESUME_WINDOW_START)
                    end_time = _calculated_stop_times.get('WEEKDAY_SCHEDULE_END', WEEKDAY_SCHEDULE_END_WINDOW_START)

                # Monday special mid-morning stop window
                mon_stop = _calculated_stop_times.get('MONDAY_MID_MORNING_STOP', MONDAY_MID_MORNING_STOP_WINDOW_START) if current_day_of_week == 0 else None
                mon_resume = _calculated_stop_times.get('MONDAY_10AM_RESTART', MONDAY_10AM_RESTART_WINDOW_START) if current_day_of_week == 0 else None

                # Determine label based on where current_time_of_day falls
                if current_day_of_week == 5:
                    if current_time_of_day < start_time:
                        current_shift_label = 'Pre-Saturday Start'
                    elif start_time <= current_time_of_day < end_time:
                        current_shift_label = 'Saturday Work Hours (Timer ON)'
                    else:
                        current_shift_label = 'Post-Saturday Hours (Long Break)'
                else:
                    # Weekday labeling
                    if mon_stop and mon_stop <= current_time_of_day < mon_resume:
                        current_shift_label = 'Monday Mid-Morning (brief stop — will restart)'
                    elif current_time_of_day < start_time:
                        current_shift_label = 'Pre-Shift (Idle)'
                    elif start_time <= current_time_of_day < lunch_stop:
                        current_shift_label = 'Morning (Timer ON)'
                    elif lunch_stop <= current_time_of_day < afternoon_stop:
                        current_shift_label = 'Lunch (brief stop — will restart)'
                    elif afternoon_stop <= current_time_of_day < end_time:
                        current_shift_label = 'Afternoon (Timer ON)'
                    elif current_time_of_day >= end_time:
                        current_shift_label = 'Post-Shift (Long Break)'
                    else:
                        current_shift_label = current_shift_type

                # Detect short in-shift stop windows so we don't restart during them
                in_stop_window = False
                if current_day_of_week == 5:
                    # Saturday lunch breaks now restart immediately, so no stop window needed
                    pass
                else:
                    # Consider brief stop windows for weekday lunch and afternoon stop
                    afternoon_stop = _calculated_stop_times.get('WEEKDAY_AFTERNOON_STOP', WEEKDAY_LUNCH_BREAK_RESUME_WINDOW_START)
                    if lunch_stop and afternoon_stop and lunch_stop <= current_time_of_day < afternoon_stop:
                        in_stop_window = True
                    # Monday mid-morning special stop
                    if current_day_of_week == 0 and mon_stop and mon_resume and mon_stop <= current_time_of_day < mon_resume:
                        in_stop_window = True

                timer_is_running = is_timer_running(driver) # Initial check for this iteration
                # Always attempt to run timer during 'work' periods except while inside a short stop window
                should_be_running_for_timer = (current_shift_type == 'work') and (not in_stop_window)
                # --- Action Phase ---
                action_performed_this_iteration = False

                # 1. Check for specific STOP triggers (based on calculated precise stop times)
                stop_event_to_trigger = None
                if current_day_of_week == 5:  # Saturday
                    if 'SUNDAY_LUNCH_BREAK_STOP' in _calculated_stop_times and not _event_executed_flags.get('SUNDAY_LUNCH_BREAK_STOP', False) and \
                       current_time_of_day >= _calculated_stop_times['SUNDAY_LUNCH_BREAK_STOP']:
                        stop_event_to_trigger = 'SUNDAY_LUNCH_BREAK_STOP'
                    elif 'SUNDAY_AFTERNOON_STOP' in _calculated_stop_times and not _event_executed_flags.get('SUNDAY_AFTERNOON_STOP', False) and \
                         current_time_of_day >= _calculated_stop_times['SUNDAY_AFTERNOON_STOP']:
                        stop_event_to_trigger = 'SUNDAY_AFTERNOON_STOP'
                    elif 'SUNDAY_SCHEDULE_END' in _calculated_stop_times and not _event_executed_flags.get('SUNDAY_SCHEDULE_END', False) and \
                         current_time_of_day >= _calculated_stop_times['SUNDAY_SCHEDULE_END']:
                        stop_event_to_trigger = 'SUNDAY_SCHEDULE_END'
                else:  # Weekday
                    # Monday specific mid-morning stop
                    if current_day_of_week == 0 and 'MONDAY_MID_MORNING_STOP' in _calculated_stop_times and not _event_executed_flags.get('MONDAY_MID_MORNING_STOP', False) and \
                       current_time_of_day >= _calculated_stop_times['MONDAY_MID_MORNING_STOP']:
                        stop_event_to_trigger = 'MONDAY_MID_MORNING_STOP'
                    # Weekday lunch break stop
                    elif 'WEEKDAY_LUNCH_BREAK_STOP' in _calculated_stop_times and not _event_executed_flags.get('WEEKDAY_LUNCH_BREAK_STOP', False) and \
                         current_time_of_day >= _calculated_stop_times['WEEKDAY_LUNCH_BREAK_STOP']:
                        stop_event_to_trigger = 'WEEKDAY_LUNCH_BREAK_STOP'
                    # Weekday afternoon stop (second brief stop)
                    elif 'WEEKDAY_AFTERNOON_STOP' in _calculated_stop_times and not _event_executed_flags.get('WEEKDAY_AFTERNOON_STOP', False) and \
                         current_time_of_day >= _calculated_stop_times['WEEKDAY_AFTERNOON_STOP']:
                        stop_event_to_trigger = 'WEEKDAY_AFTERNOON_STOP'
                    # Daily final stop
                    elif 'WEEKDAY_SCHEDULE_END' in _calculated_stop_times and not _event_executed_flags.get('WEEKDAY_SCHEDULE_END', False) and \
                         current_time_of_day >= _calculated_stop_times['WEEKDAY_SCHEDULE_END']:
                        stop_event_to_trigger = 'WEEKDAY_SCHEDULE_END'

                # If there's a scheduled stop event due now, stop timer briefly and mark it executed
                if stop_event_to_trigger and timer_is_running:
                    print(f"[{current_shift_label}] Time is {current_time_of_day.strftime('%H:%M:%S')}. Timer is Running. Triggered STOP action for {stop_event_to_trigger} at {_calculated_stop_times[stop_event_to_trigger].strftime('%H:%M:%S')}. Attempting to STOP timer.")
                    if try_stop_timer(driver):
                        timer_is_running = False
                        action_performed_this_iteration = True
                        _event_executed_flags[stop_event_to_trigger] = True # Mark as executed for today
                        if not check_for_nan_and_recover(driver):
                            print("Warning: Could not clear 'NaNh NaNm' after stopping timer. Proceeding with caution.")
                        # For final end-of-shift stops, schedule shutdown. For short stops, immediately restart timer.
                        if stop_event_to_trigger in ['WEEKDAY_SCHEDULE_END', 'SUNDAY_SCHEDULE_END']:
                            print("Autoshutdown scheduled for 5 minutes.")
                            os.system('shutdown /s /t 300')
                            response = input("Do you want to continue shutdown? (y/n): ").strip().lower()
                            yes_variants = {'y', 'yy', 'yyy', 'yes', 'ye', 'ys'}
                            if response.lower() in yes_variants:
                                print("Shutdown proceeding.")
                            else:
                                os.system('shutdown /a')
                                print("Shutdown halted.")
                        else:
                            # Immediately restart timer after a brief stop (applies to weekday lunch breaks, Monday mid-morning, and Sunday lunch break)
                            print("Waiting 5 seconds before attempting immediate restart after stop event.")
                            time.sleep(RESTART_DELAY_SECONDS)
                            if not check_for_nan_and_recover(driver):
                                print("Warning: Could not clear 'NaNh NaNm' before starting timer. Proceeding with caution.")
                            try:
                                start_timer_button = WebDriverWait(driver, SHORT_WAIT_SECONDS).until(
                                    EC.element_to_be_clickable((By.ID, "timer-start-button"))
                                )
                                start_timer_button.click()
                                print("Successfully clicked 'Start timer' button. Timer is now running.")
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

                # 2. Handle starting the timer if it should be running (for timer) but is not
                if should_be_running_for_timer and not timer_is_running:
                    print(f"[{current_shift_label}] Time is {current_time_of_day.strftime('%H:%M:%S')}. Timer is Stopped. Timer should be running. Attempting to START timer.")
                    
                    # Add 5-second initial wait before clicking to start timer
                    print("Waiting 5 seconds before attempting to start timer to ensure page stability...")
                    time.sleep(5)
                    
                    # NEW: Check for NaN after the wait, before attempting to start
                    if not check_for_nan_and_recover(driver):
                        print("Warning: Could not clear 'NaNh NaNm' before starting timer. Proceeding with caution.")

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

                # --- Enhanced Logging for Next Timer Stop/Event ---
                # Build a unified list of upcoming events (stops and starts) for clearer logging
                upcoming_events = []
                now_time = now.time()
                
                if current_day_of_week == 5:  # Saturday
                    if 'SUNDAY_LUNCH_BREAK_STOP' in _calculated_stop_times and not _event_executed_flags.get('SUNDAY_LUNCH_BREAK_STOP', False):
                        upcoming_events.append(('Stop: Saturday Lunch Break', _calculated_stop_times['SUNDAY_LUNCH_BREAK_STOP']))
                    if 'SUNDAY_AFTERNOON_STOP' in _calculated_stop_times and not _event_executed_flags.get('SUNDAY_AFTERNOON_STOP', False):
                        upcoming_events.append(('Stop: Saturday Afternoon Break', _calculated_stop_times['SUNDAY_AFTERNOON_STOP']))
                    if 'SUNDAY_SCHEDULE_END' in _calculated_stop_times and not _event_executed_flags.get('SUNDAY_SCHEDULE_END', False):
                        upcoming_events.append(('Stop: Saturday End of Shift', _calculated_stop_times['SUNDAY_SCHEDULE_END']))
                else:  # Weekday
                    # Monday special events
                    if current_day_of_week == 0:
                        if 'MONDAY_MID_MORNING_STOP' in _calculated_stop_times and not _event_executed_flags.get('MONDAY_MID_MORNING_STOP', False):
                            upcoming_events.append(('Stop: Monday Mid-Morning', _calculated_stop_times['MONDAY_MID_MORNING_STOP']))
                        if 'MONDAY_10AM_RESTART' in _calculated_stop_times and not _event_executed_flags.get('MONDAY_10AM_RESTART', False):
                            upcoming_events.append(('Start: Monday 10AM Restart', _calculated_stop_times['MONDAY_10AM_RESTART']))

                    # Lunch stop and resume
                    if 'WEEKDAY_LUNCH_BREAK_STOP' in _calculated_stop_times and not _event_executed_flags.get('WEEKDAY_LUNCH_BREAK_STOP', False):
                        upcoming_events.append(('Stop: Weekday Lunch Break', _calculated_stop_times['WEEKDAY_LUNCH_BREAK_STOP']))
                    if 'WEEKDAY_AFTERNOON_STOP' in _calculated_stop_times and not _event_executed_flags.get('WEEKDAY_AFTERNOON_STOP', False):
                        upcoming_events.append(('Stop: Weekday Afternoon Break', _calculated_stop_times['WEEKDAY_AFTERNOON_STOP']))

                    # End of shift
                    if 'WEEKDAY_SCHEDULE_END' in _calculated_stop_times and not _event_executed_flags.get('WEEKDAY_SCHEDULE_END', False):
                        upcoming_events.append(('Stop: Weekday End of Shift', _calculated_stop_times['WEEKDAY_SCHEDULE_END']))

                # Filter and pick earliest future event
                future_events = [(label, t) for label, t in upcoming_events if t and now_time < t]
                if future_events:
                    next_label, next_time = min(future_events, key=lambda x: x[1])
                    # Normalize label for earlier UX: show 'start'/'stop' compactly
                    display_label = next_label.replace('Stop: ', 'stop (').replace('Start: ', 'start (') + ')'
                    print(f"Next event: {display_label} at {next_time.strftime('%H:%M:%S')}")
                else:
                    print("No more scheduled events for today. Awaiting shift end or next day start.")

                # --- Determine Next Event and Log It (Revised for clarity and accuracy) ---
                next_event_datetime = None
                next_event_label = ""
                
                # List all potential future events for today (stops and starts)
                potential_events_today = []

                # Add calculated stop times if they haven't been executed and are in the future
                if current_day_of_week == 5:  # Saturday
                    if 'SUNDAY_LUNCH_BREAK_STOP' in _calculated_stop_times and not _event_executed_flags.get('SUNDAY_LUNCH_BREAK_STOP', False):
                        potential_events_today.append((datetime.datetime.combine(current_date, _calculated_stop_times['SUNDAY_LUNCH_BREAK_STOP']), "stop (saturday lunch stop)"))
                    if 'SUNDAY_AFTERNOON_STOP' in _calculated_stop_times and not _event_executed_flags.get('SUNDAY_AFTERNOON_STOP', False):
                        potential_events_today.append((datetime.datetime.combine(current_date, _calculated_stop_times['SUNDAY_AFTERNOON_STOP']), "stop (saturday afternoon stop)"))
                    if 'SUNDAY_SCHEDULE_END' in _calculated_stop_times and not _event_executed_flags.get('SUNDAY_SCHEDULE_END', False):
                        potential_events_today.append((datetime.datetime.combine(current_date, _calculated_stop_times['SUNDAY_SCHEDULE_END']), "stop (saturday final stop)"))
                else:  # Weekday
                    if current_day_of_week == 0:  # Monday
                        if 'MONDAY_MID_MORNING_STOP' in _calculated_stop_times and not _event_executed_flags.get('MONDAY_MID_MORNING_STOP', False):
                            potential_events_today.append((datetime.datetime.combine(current_date, _calculated_stop_times['MONDAY_MID_MORNING_STOP']), "stop (monday mid-morning stop)"))
                        if 'MONDAY_10AM_RESTART' in _calculated_stop_times and not _event_executed_flags.get('MONDAY_10AM_RESTART', False):
                            potential_events_today.append((datetime.datetime.combine(current_date, _calculated_stop_times['MONDAY_10AM_RESTART']), "start (monday 10am restart)"))
                    # Lunch stop and afternoon stop
                    if 'WEEKDAY_LUNCH_BREAK_STOP' in _calculated_stop_times and not _event_executed_flags.get('WEEKDAY_LUNCH_BREAK_STOP', False):
                        potential_events_today.append((datetime.datetime.combine(current_date, _calculated_stop_times['WEEKDAY_LUNCH_BREAK_STOP']), "stop (weekday lunch stop)"))
                    if 'WEEKDAY_AFTERNOON_STOP' in _calculated_stop_times and not _event_executed_flags.get('WEEKDAY_AFTERNOON_STOP', False):
                        potential_events_today.append((datetime.datetime.combine(current_date, _calculated_stop_times['WEEKDAY_AFTERNOON_STOP']), "stop (weekday afternoon stop)"))
                    # Daily final stop
                    if 'WEEKDAY_SCHEDULE_END' in _calculated_stop_times and not _event_executed_flags.get('WEEKDAY_SCHEDULE_END', False):
                        potential_events_today.append((datetime.datetime.combine(current_date, _calculated_stop_times['WEEKDAY_SCHEDULE_END']), "stop (weekday daily final stop)"))

                # If current shift is long_break, always consider current day's start/restart first
                if current_shift_type == 'long_break':
                    current_day_start_dt = None
                    if current_day_of_week == 5:
                        if 'SUNDAY_SCHEDULE_START' in _calculated_stop_times and current_time_of_day < _calculated_stop_times['SUNDAY_SCHEDULE_START']:
                            current_day_start_dt = datetime.datetime.combine(current_date, _calculated_stop_times['SUNDAY_SCHEDULE_START'])
                    else:
                        if 'WEEKDAY_SCHEDULE_START' in _calculated_stop_times and current_time_of_day < _calculated_stop_times['WEEKDAY_SCHEDULE_START']:
                            current_day_start_dt = datetime.datetime.combine(current_date, _calculated_stop_times['WEEKDAY_SCHEDULE_START'])
                        # Monday 10am restart
                        if current_day_of_week == 0 and 'MONDAY_10AM_RESTART' in _calculated_stop_times and current_time_of_day < _calculated_stop_times['MONDAY_10AM_RESTART']:
                            current_day_start_dt = datetime.datetime.combine(current_date, _calculated_stop_times['MONDAY_10AM_RESTART'])

                    if current_day_start_dt and current_day_start_dt > now:
                        potential_events_today.append((current_day_start_dt, "start (current day shift/restart)"))

                # Find the earliest future event for today
                future_events_today = [e for e in potential_events_today if e[0] > now]
                earliest_today_event = min(future_events_today, key=lambda x: x[0]) if future_events_today else None

                # If no more events today, calculate next day's morning start
                if earliest_today_event is None:
                    days_until_next_shift_start = 1
                    next_start_window_start_time = WEEKDAY_SCHEDULE_START_WINDOW_START
                    next_start_window_end_time = WEEKDAY_SCHEDULE_START_WINDOW_END

                    # If today is Saturday, skip Sunday (off day) and set next start to Monday
                    if current_day_of_week == 5:  # Saturday -> Monday
                        days_until_next_shift_start = 2
                    elif current_day_of_week == 6:  # Sunday -> Monday
                        days_until_next_shift_start = 1

                    next_day_date = now.date() + datetime.timedelta(days=days_until_next_shift_start)
                    next_event_datetime = datetime.datetime.combine(next_day_date, get_random_time_in_window(next_start_window_start_time, next_start_window_end_time))
                    next_event_label = "start (next day)"
                else:
                    next_event_datetime = earliest_today_event[0]
                    next_event_label = earliest_today_event[1]

                if next_event_datetime:
                    print(f"Next event ({next_event_label}) at {next_event_datetime.strftime('%H:%M:%S')} on {next_event_datetime.date()}.")
                else:
                    print("No clear next event determined for sleep calculation. Defaulting to polling interval.")
                    next_event_datetime = now + datetime.timedelta(minutes=POLLING_INTERVAL_MINUTES)
                    next_event_label = "fallback polling"

                # Find the randomized end time for the current shift (workday end)
                randomized_end_datetime = None
                randomized_end_event_key = None
                if current_shift_type == 'work':
                    if current_day_of_week == 5:
                        end_time = _calculated_stop_times.get('SUNDAY_SCHEDULE_END')
                        if end_time:
                            randomized_end_datetime = datetime.datetime.combine(current_date, end_time)
                            randomized_end_event_key = 'SUNDAY_SCHEDULE_END'
                    else:
                        end_time = _calculated_stop_times.get('WEEKDAY_SCHEDULE_END')
                        if end_time:
                            randomized_end_datetime = datetime.datetime.combine(current_date, end_time)
                            randomized_end_event_key = 'WEEKDAY_SCHEDULE_END'

                # --- NEW: Stop timer at randomized end time if needed ---
                if randomized_end_datetime and now >= randomized_end_datetime and timer_is_running:
                    if randomized_end_event_key and not _event_executed_flags.get(randomized_end_event_key, False):
                        print(f"--- Timer End Event ---\nAttempting to end timer at randomized shift end: {randomized_end_datetime.strftime('%H:%M:%S')} (Current time: {now.strftime('%H:%M:%S')})")
                        if try_stop_timer(driver):
                            timer_is_running = False
                            action_performed_this_iteration = True
                            _event_executed_flags[randomized_end_event_key] = True
                            if not check_for_nan_and_recover(driver):
                                print("Warning: Could not clear 'NaNh NaNm' after stopping timer at randomized end. Proceeding with caution.")
                            if randomized_end_event_key in ['WEEKDAY_SCHEDULE_END', 'SUNDAY_SCHEDULE_END']:
                                print("Autoshutdown scheduled for 5 minutes.")
                                os.system('shutdown /s /t 300')
                                response = input("Do you want to continue the shutdown? (y/n): ").strip().lower()
                                yes_variants = {'y', 'yy', 'yyy', 'yes', 'ye', 'ys'}
                                if response in yes_variants:
                                    print("Shutdown proceeding.")
                                else:
                                    os.system('shutdown /a')
                                    print("Shutdown halted.")

                # --- Sleep Determination Phase ---
                sleep_duration_for_this_iteration = 1 # Default to minimal sleep for responsiveness

                if action_performed_this_iteration:
                    sleep_duration_for_this_iteration = 1
                    print("Action performed this iteration. Re-evaluating immediately.")
                elif current_shift_type == 'long_break':
                    time_to_next_event_seconds = (next_event_datetime - now).total_seconds()
                    if time_to_next_event_seconds < 0:
                        time_to_next_event_seconds = 1
                    sleep_duration_for_this_iteration = time_to_next_event_seconds
                    print(f"In long break. Next event ({next_event_label}) at {next_event_datetime.strftime('%H:%M:%S')} on {next_event_datetime.date()}. Sleeping for {int(sleep_duration_for_this_iteration / 60)} minutes and {int(sleep_duration_for_this_iteration % 60)} seconds.")
                else:
                    time_to_next_event_seconds = (next_event_datetime - now).total_seconds()
                    if time_to_next_event_seconds < 0:
                        time_to_next_event_seconds = 1

                    # Calculate time to randomized end of shift
                    time_to_randomized_end_seconds = None
                    if randomized_end_datetime:
                        time_to_randomized_end_seconds = (randomized_end_datetime - now).total_seconds()

                    # If the next event is imminent (within polling interval), sleep precisely until then.
                    if time_to_next_event_seconds <= POLLING_INTERVAL_MINUTES * 60:
                        sleep_duration_for_this_iteration = time_to_next_event_seconds
                        print(f"Current shift type is '{current_shift_type}'. Next event ({next_event_label}) is imminent. Sleeping precisely until then.")
                    # If randomized end is sooner than 8 min, sleep until randomized end
                    elif time_to_randomized_end_seconds is not None and time_to_randomized_end_seconds <= POLLING_INTERVAL_MINUTES * 60:
                        sleep_duration_for_this_iteration = time_to_randomized_end_seconds
                        print(f"Current shift type is '{current_shift_type}'. Randomized end of shift is imminent. Sleeping precisely until then.")
                    elif timer_is_running:
                        sleep_duration_for_this_iteration = POLLING_INTERVAL_MINUTES * 60
                        print(f"Current shift type is '{current_shift_type}'. Timer is running and next event is far. Sleeping for {POLLING_INTERVAL_MINUTES} minutes.")
                    else:
                        sleep_duration_for_this_iteration = 1
                        print(f"Current shift type is '{current_shift_type}'. Timer is stopped but should be running. Checking for start action immediately.")

                sleep_duration_for_this_iteration = max(1, int(sleep_duration_for_this_iteration)) # Minimum 1 second sleep

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
