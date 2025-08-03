from flask import Flask, jsonify, request
from selenium import webdriver
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.common.by import By
from selenium.webdriver.chrome.service import Service as ChromeService
from selenium.webdriver.support.ui import WebDriverWait, Select
from selenium.webdriver.support import expected_conditions as EC
from webdriver_manager.chrome import ChromeDriverManager
from threading import Thread, Lock
import os
import time
import traceback
import datetime
import json

app = Flask(__name__)

# Global state management
scraping_state = {
    "status": "idle",  # idle, running, completed, error
    "start_time": None,
    "end_time": None,
    "progress": 0,
    "total_opportunities": 0,
    "current_page": 0,
    "error": None,
    "opportunities": []
}
state_lock = Lock()

def init_driver():
    chrome_options = Options()
    chrome_options.add_argument("--headless=new")
    chrome_options.add_argument("--no-sandbox")
    chrome_options.add_argument("--disable-dev-shm-usage")
    chrome_options.add_argument("--disable-blink-features=AutomationControlled")
    chrome_options.add_experimental_option("excludeSwitches", ["enable-automation"])
    chrome_options.add_experimental_option("useAutomationExtension", False)
    
    # Set user-agent to mimic regular browser
    user_agent = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/113.0.0.0 Safari/537.36"
    chrome_options.add_argument(f'user-agent={user_agent}')
    
    # Find Chrome automatically on Windows
    if os.name == 'nt':  # Windows
        # Common Chrome installation paths on Windows
        possible_paths = [
            os.path.expandvars(r"%ProgramFiles%\Google\Chrome\Application\chrome.exe"),
            os.path.expandvars(r"%ProgramFiles(x86)%\Google\Chrome\Application\chrome.exe"),
            os.path.expandvars(r"%LocalAppData%\Google\Chrome\Application\chrome.exe")
        ]
        
        for path in possible_paths:
            if os.path.exists(path):
                chrome_options.binary_location = path
                print(f"Using Chrome found at: {path}")
                break
    
    service = ChromeService(ChromeDriverManager().install())
    driver = webdriver.Chrome(service=service, options=chrome_options)
    
    # Additional stealth settings
    driver.execute_script("Object.defineProperty(navigator, 'webdriver', {get: () => undefined})")
    
    return driver

def safe_get_text(element, selector, default="N/A"):
    try:
        return element.find_element(By.CSS_SELECTOR, selector).text.strip()
    except:
        return default

def scrape_opportunities_thread():
    global scraping_state
    
    with state_lock:
        scraping_state = {
            "status": "running",
            "start_time": datetime.datetime.now().isoformat(),
            "end_time": None,
            "progress": 0,
            "total_opportunities": 0,
            "current_page": 0,
            "error": None,
            "opportunities": []
        }
    
    driver = None
    try:
        url = "https://www.marchespublics.gov.ma/index.php?page=entreprise.EntrepriseAdvancedSearch&searchAnnCons"
        driver = init_driver()
        print("Navigating to URL...")
        driver.get(url)
        
        # Wait for page to load
        WebDriverWait(driver, 20).until(
            EC.presence_of_element_located((By.TAG_NAME, "body"))
        )
        print("Page loaded successfully")
        
        # Click the search button to reveal results
        try:
            search_button = WebDriverWait(driver, 10).until(
                EC.element_to_be_clickable((By.CSS_SELECTOR, "input[title='Lancer la recherche']"))
            )
            print("Clicking search button...")
            search_button.click()
            print("Search button clicked")
        except Exception as e:
            print(f"Search button not found or clickable: {str(e)}")
            with state_lock:
                scraping_state["status"] = "error"
                scraping_state["error"] = "Search button not found"
            return
        
        # Wait for results table
        print("Waiting for results table...")
        WebDriverWait(driver, 20).until(
            EC.presence_of_element_located((By.CSS_SELECTOR, "table.table-results"))
        )
        print("Results table found")
        
        # Set to 500 results per page
        try:
            print("Setting results per page to 500...")
            results_dropdown = WebDriverWait(driver, 10).until(
                EC.presence_of_element_located((By.CSS_SELECTOR, "select[title='Nombre de résultats par page']"))
            )
            select = Select(results_dropdown)
            select.select_by_value("500")
            print("Waiting for page to reload with more results...")
            
            # Wait for results to reload
            time.sleep(3)  # Additional wait for page to reload
            print("Page reloaded with 500 results")
        except Exception as e:
            print(f"Could not set results per page: {str(e)}")
        
        opportunities = []
        page_count = 1
        
        while True:
            with state_lock:
                scraping_state["current_page"] = page_count
                scraping_state["progress"] = page_count * 10  # Simplified progress
            
            print(f"Processing page {page_count}...")
            
            # Wait for rows to load
            rows = WebDriverWait(driver, 10).until(
                EC.presence_of_all_elements_located((By.CSS_SELECTOR, "table.table-results tbody tr"))
            )
            print(f"Found {len(rows)} opportunities on this page")
            
            for i, row in enumerate(rows):
                try:
                    # Extract all fields with error handling
                    type_procedure = safe_get_text(row, "div[id*='panelBlocTypesProc'] div", "N/A")
                    categorie = safe_get_text(row, "div[id*='panelBlocCategorie']", "N/A")
                    
                    # Published date - third div in the first column
                    try:
                        date_publication = row.find_element(By.CSS_SELECTOR, "td:nth-child(2) > div:nth-child(3)").text
                    except:
                        date_publication = "N/A"
                    
                    reference = safe_get_text(row, "span.ref", "N/A")
                    
                    # Object - remove "Objet : " prefix
                    objet = safe_get_text(row, "div[id*='panelBlocObjet']", "N/A").replace("Objet : ", "").strip()
                    
                    # Buyer - remove "Acheteur public : " prefix
                    acheteur = safe_get_text(row, "div[id*='panelBlocDenomination']", "N/A").replace("Acheteur public : ", "").strip()
                    
                    # Place - first line of location text
                    try:
                        lieu_execution_element = row.find_element(By.CSS_SELECTOR, "div[id*='panelBlocLieuxExec']")
                        lieu_execution = lieu_execution_element.text.split("\n")[0].strip()
                    except:
                        lieu_execution = "N/A"
                    
                    # Deadline
                    date_limite = safe_get_text(row, "div.cloture-line", "N/A")
                    
                    opportunity = {
                        "type_procedure": type_procedure,
                        "categorie": categorie,
                        "date_publication": date_publication,
                        "reference": reference,
                        "objet": objet,
                        "acheteur": acheteur,
                        "lieu_execution": lieu_execution,
                        "date_limite": date_limite
                    }
                    
                    opportunities.append(opportunity)
                    
                    # Update state with new opportunity
                    with state_lock:
                        scraping_state["opportunities"].append(opportunity)
                        scraping_state["total_opportunities"] = len(scraping_state["opportunities"])
                    
                    print(f"Processed row {i+1}/{len(rows)}")
                    
                except Exception as e:
                    print(f"Error processing row {i+1}: {str(e)}")
                    continue
            
            # Try to go to next page
            try:
                next_button = driver.find_element(By.CSS_SELECTOR, "input[title='Page suivante']")
                if next_button.is_enabled():
                    next_button.click()
                    print("Navigating to next page...")
                    
                    # Wait for next page to load
                    time.sleep(2)  # Wait for page transition
                    page_count += 1
                else:
                    print("Next page button disabled")
                    break
            except Exception as e:
                print(f"No more pages or error navigating: {str(e)}")
                break
        
        # Scraping completed successfully
        with state_lock:
            scraping_state["status"] = "completed"
            scraping_state["end_time"] = datetime.datetime.now().isoformat()
            scraping_state["progress"] = 100
            
        print("Scraping completed successfully")
                
    except Exception as e:
        print(f"Scraping failed: {str(e)}")
        traceback.print_exc()
        with state_lock:
            scraping_state["status"] = "error"
            scraping_state["error"] = str(e)
            scraping_state["end_time"] = datetime.datetime.now().isoformat()
        
    finally:
        if driver:
            driver.quit()
            print("Browser closed")

@app.route("/api/v1/scraping/start", methods=["GET"])
def start_scraping():
    global scraping_state
    
    # Check if scraping is already running
    with state_lock:
        if scraping_state["status"] == "running":
            return jsonify({"status": "error", "message": "Scraping is already in progress"}), 409
        
        # Reset state
        scraping_state = {
            "status": "running",
            "start_time": datetime.datetime.now().isoformat(),
            "end_time": None,
            "progress": 0,
            "total_opportunities": 0,
            "current_page": 0,
            "error": None,
            "opportunities": []
        }
    
    # Start scraping in a separate thread
    thread = Thread(target=scrape_opportunities_thread)
    thread.daemon = True
    thread.start()
    
    return jsonify({
        "status": "started",
        "message": "Scraping process started in background",
        "start_time": scraping_state["start_time"]
    })

@app.route("/api/v1/scraping/status", methods=["GET"])
def get_status():
    with state_lock:
        status = scraping_state.copy()
        # Don't include all opportunities in status response to keep it lightweight
        status.pop("opportunities", None)
    
    # Calculate duration if completed
    if status["end_time"] and status["start_time"]:
        start = datetime.datetime.fromisoformat(status["start_time"])
        end = datetime.datetime.fromisoformat(status["end_time"])
        status["duration_seconds"] = (end - start).total_seconds()
    
    return jsonify(status)

@app.route("/api/v1/scraping/opportunities", methods=["GET"])
def get_opportunities():
    with state_lock:
        if scraping_state["status"] == "idle":
            return jsonify({"status": "error", "message": "No scraping has been performed yet"}), 404
        
        # Return ALL opportunities without pagination
        return jsonify({
            "status": "success",
            "total_opportunities": len(scraping_state["opportunities"]),
            "opportunities": scraping_state["opportunities"]
        })

@app.route("/api/v1/scraping/search", methods=["GET"])
def search_opportunities():
    with state_lock:
        if scraping_state["status"] == "idle":
            return jsonify({"status": "error", "message": "No scraping has been performed yet"}), 404
        
        # Get search parameters
        query = request.args.get('query', '').lower()
        field = request.args.get('field', 'all')
        
        # Filter opportunities based on search query
        filtered = []
        for opp in scraping_state["opportunities"]:
            match = False
            
            if field == 'all':
                # Search in all fields
                for value in opp.values():
                    if query in str(value).lower():
                        match = True
                        break
            elif field in opp:
                # Search in specific field
                if query in str(opp[field]).lower():
                    match = True
            
            if match:
                filtered.append(opp)
        
        # Return ALL matching opportunities without pagination
        return jsonify({
            "status": "success",
            "query": query,
            "field": field,
            "total_results": len(filtered),
            "results": filtered
        })

@app.route("/api/v1/scraping/reset", methods=["POST"])
def reset_scraping():
    global scraping_state
    with state_lock:
        scraping_state = {
            "status": "idle",
            "start_time": None,
            "end_time": None,
            "progress": 0,
            "total_opportunities": 0,
            "current_page": 0,
            "error": None,
            "opportunities": []
        }
    return jsonify({"status": "success", "message": "Scraping state reset"})

@app.route("/")
def home():
    return """
    <h1>Public Markets Scraper API</h1>
    <p>Endpoints:</p>
    <ul>
        <li><strong>POST /api/v1/scraping/start</strong> - Start scraping process</li>
        <li><strong>GET /api/v1/scraping/status</strong> - Get scraping status</li>
        <li><strong>GET /api/v1/scraping/opportunities</strong> - Get all discovered opportunities</li>
        <li><strong>GET /api/v1/scraping/search</strong> - Search opportunities (query, field)</li>
        <li><strong>POST /api/v1/scraping/reset</strong> - Reset scraping state</li>
    </ul>
    """

if __name__ == "__main__":
    app.run(debug=True, port=5000, host='0.0.0.0')