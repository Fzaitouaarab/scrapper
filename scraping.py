from flask import Flask, jsonify
from selenium import webdriver
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.common.by import By
from selenium.webdriver.chrome.service import Service as ChromeService
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from webdriver_manager.chrome import ChromeDriverManager
import time

app = Flask(__name__)

def init_driver():
    chrome_options = Options()
    chrome_options.add_argument("--headless=new")  # Nouvelle syntaxe headless
    chrome_options.add_argument("--no-sandbox")
    chrome_options.add_argument("--disable-dev-shm-usage")
    
    # Contournement de la détection headless
    chrome_options.add_argument("--disable-blink-features=AutomationControlled")
    chrome_options.add_experimental_option("excludeSwitches", ["enable-automation"])
    chrome_options.add_experimental_option('useAutomationExtension', False)
    
    driver = webdriver.Chrome(
        service=ChromeService(ChromeDriverManager().install()),
        options=chrome_options
    )
    
    # Modification du user-agent
    driver.execute_cdp_cmd('Network.setUserAgentOverride', {
        "userAgent": 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/113.0.0.0 Safari/537.36'
    })
    
    return driver

def scrape_opportunities():
    url = "https://www.marchespublics.gov.ma/pmmp/?lang=fr"
    driver = init_driver()
    
    try:
        driver.get(url)
        
        # Wait for opportunities container
        WebDriverWait(driver, 15).until(
            EC.presence_of_element_located((By.CLASS_NAME, "appels-offres"))
        )
        
        opportunities = []
        
        # Find all table rows with opportunities
        items = driver.find_elements(By.CSS_SELECTOR, "table.data tbody tr")
        
        for item in items:
            try:
                # Extract title from first column
                title = item.find_element(By.CSS_SELECTOR, "td:first-child").text
                opportunities.append({"title": title})
            except:
                continue
                
        return {"opportunities": opportunities}
        
    except Exception as e:
        return {"error": str(e), "message": "Vérifiez la structure HTML du site"}
        
    finally:
        driver.quit()

@app.route("/api/v1/scraping/opportunities", methods=["GET"])
def get_opportunities():
    result = scrape_opportunities()
    return jsonify(result)

if __name__ == "__main__":
    app.run(debug=True)